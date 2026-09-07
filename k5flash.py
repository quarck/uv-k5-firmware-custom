#!/usr/bin/env python3
"""
k5flash.py -- flash firmware to a UV-K5 running losehu's custom bootloader.

K5TOOL speaks the stock Quansheng flash protocol (its Packet2/Packet5 Flash*
packets) which this bootloader does not implement, so -wrflash cannot be used.
This talks the custom bootloader's protocol instead. Everything here is taken
from uv-k5-bootloader-custom 0.02: app/uart.c (framing, CMD_0519, CMD_0530,
payload_xor) and main.c (the 0x0518 beacon).

The envelope is identical to the running firmware's UART protocol, so the
framing helpers are shared with k5eeprom.py:

    AB CD | size(LE16) | obfuscate(payload ++ crc16_xmodem(payload)) | DC BA

Flash sequence:
    1. wait for the bootloader's repeating 0x0518 beacon (proves flash mode)
    2. 0x0530  -- erase the application area; stops the beacon, sends no reply
    3. 0x0519  -- write 256 bytes at an offset, acked with 0x051A
    4. the bootloader resets itself once offset + 0x100 == total

Accepts either the raw build output (firmware.bin) or the packed image the
uploaders use (QRCK*.bin) -- packed images are unpacked in memory, since the
bootloader programs whatever bytes it is handed straight to flash.

Only the application area (flash pages 8..127) is erased; the bootloader itself
lives below that and is never touched, so a failed run is always retryable.
"""

import argparse
import os
import random
import struct
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial is required:  pip install pyserial")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from k5eeprom import OBFUSCATION, HDR, FTR, obfuscate, frame, crc16
except ImportError:
    sys.exit("k5flash.py needs k5eeprom.py beside it (shared packet framing)")

BEACON_ID = 0x0518   # bootloader -> host, repeats while idle in flash mode
ERASE_ID = 0x0530    # host -> bootloader, erases the application area
WRITE_ID = 0x0519    # host -> bootloader, one 256-byte block
WRITE_ACK = 0x051A

BLOCK = 256          # CMD_0519 programs exactly 256 bytes (64 words)
FLASH_LIMIT = 61440  # 60K application area

# Packed-image obfuscation key, from fw-pack.py. Note this is the 128-byte
# *image* key and has nothing to do with the 16-byte UART key in k5eeprom.py.
PACK_KEY = bytes((
    0x47, 0x22, 0xC0, 0x52, 0x5D, 0x57, 0x48, 0x94, 0xB1, 0x60, 0x60, 0xDB, 0x6F, 0xE3, 0x4C, 0x7C,
    0xD8, 0x4A, 0xD6, 0x8B, 0x30, 0xEC, 0x25, 0xE0, 0x4C, 0xD9, 0x00, 0x7F, 0xBF, 0xE3, 0x54, 0x05,
    0xE9, 0x3A, 0x97, 0x6B, 0xB0, 0x6E, 0x0C, 0xFB, 0xB1, 0x1A, 0xE2, 0xC9, 0xC1, 0x56, 0x47, 0xE9,
    0xBA, 0xF1, 0x42, 0xB6, 0x67, 0x5F, 0x0F, 0x96, 0xF7, 0xC9, 0x3C, 0x84, 0x1B, 0x26, 0xE1, 0x4E,
    0x3B, 0x6F, 0x66, 0xE6, 0xA0, 0x6A, 0xB0, 0xBF, 0xC6, 0xA5, 0x70, 0x3A, 0xBA, 0x18, 0x9E, 0x27,
    0x1A, 0x53, 0x5B, 0x71, 0xB1, 0x94, 0x1E, 0x18, 0xF2, 0xD6, 0x81, 0x02, 0x22, 0xFD, 0x5A, 0x28,
    0x91, 0xDB, 0xBA, 0x5D, 0x64, 0xC6, 0xFE, 0x86, 0x83, 0x9C, 0x50, 0x1C, 0x73, 0x03, 0x11, 0xD6,
    0xAF, 0x30, 0xF4, 0x2C, 0x77, 0xB2, 0x7D, 0xBB, 0x3F, 0x29, 0x28, 0x57, 0x22, 0xD6, 0x92, 0x8B,
))
VERSION_OFFSET = 0x2000   # where fw-pack.py inserts the 16-byte version block


def unpack_image(data):
    """Reverse fw-pack.py: verify the trailing CRC, de-obfuscate, and remove the
    16-byte version block inserted at 0x2000. Returns (raw_image, version)."""
    if len(data) < VERSION_OFFSET + 0x12:
        raise ValueError("too small to be a packed image")
    body, crc = data[:-2], data[-2:]
    want = int.from_bytes(crc, "little")   # fw-pack.py writes the digest byte-swapped
    if crc16(body) != want:
        raise ValueError(f"packed CRC mismatch (got 0x{crc16(body):04X}, file says 0x{want:04X})")
    plain = bytes(b ^ PACK_KEY[i % len(PACK_KEY)] for i, b in enumerate(body))
    version = plain[VERSION_OFFSET:VERSION_OFFSET + 16].split(b"\x00")[0].decode("latin1")
    raw = plain[:VERSION_OFFSET] + plain[VERSION_OFFSET + 16:]
    return raw, version


def looks_like_raw_firmware(data):
    """A raw image starts with a Cortex-M0 vector table: an initial stack
    pointer in RAM and an odd (thumb) reset vector. A *packed* image is
    obfuscated and will not match -- which is exactly what we want to catch."""
    if len(data) < 8:
        return False, "file is too small to be a firmware image"
    sp, pc = struct.unpack("<II", data[:8])
    if (sp & 0xFFFF0000) != 0x20000000:
        return False, f"initial SP is 0x{sp:08X}, expected 0x2000xxxx"
    if not (pc & 1) or pc >= FLASH_LIMIT:
        return False, f"reset vector is 0x{pc:08X}, expected an odd address below flash top"
    return True, f"SP=0x{sp:08X} reset=0x{pc:08X}"


class Bootloader:
    def __init__(self, port, baud=38400, timeout=1.0, verbose=False):
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.timestamp = random.getrandbits(32)
        self.verbose = verbose

    def close(self):
        self.ser.close()

    def _send(self, payload):
        if self.verbose:
            head = payload[:16].hex()
            print(f"    TX {head}{'...' if len(payload) > 16 else ''} ({len(payload)} B)")
        self.ser.write(frame(payload))
        self.ser.flush()

    def _recv(self, deadline_s=3.0):
        """Read one reply/beacon frame; returns the de-obfuscated payload."""
        deadline = time.time() + deadline_s
        window = b""
        while time.time() < deadline:
            b = self.ser.read(1)
            if not b:
                continue
            window = (window + b)[-2:]
            if window == HDR:
                break
        else:
            raise TimeoutError("no frame from the radio")

        raw = self.ser.read(2)
        if len(raw) != 2:
            raise TimeoutError("truncated frame size")
        size = struct.unpack("<H", raw)[0]
        if size > 512:
            raise ValueError(f"implausible frame size {size}")
        body = self.ser.read(size + 4)   # payload + 2 pad + 2 footer
        if len(body) < size + 4:
            raise TimeoutError("truncated frame body")
        if body[size + 2:size + 4] != FTR:
            raise ValueError("bad frame footer")
        return obfuscate(body[:size])

    def wait_for_beacon(self, timeout_s=10.0):
        """The bootloader repeats 0x0518 while it is idle in flash mode."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                payload = self._recv(deadline_s=2.0)
            except (TimeoutError, ValueError):
                continue
            if struct.unpack("<H", payload[:2])[0] == BEACON_ID:
                # version string sits in the beacon payload as plain ASCII
                text = "".join(chr(c) if 32 <= c < 127 else " " for c in payload[4:32])
                return " ".join(text.split())
        return None

    def _recv_expect(self, want, deadline_s=3.0):
        """Read frames until one matches `want`.

        The bootloader beacons in a tight loop with no delay (main.c), so
        several 0x0518 frames are usually already buffered by the time a
        command is answered. Skip those; anything else is a real error."""
        deadline = time.time() + deadline_s
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"no 0x{want:04X} reply")
            payload = self._recv(deadline_s=max(0.2, remaining))
            cmd = struct.unpack("<H", payload[:2])[0]
            if cmd == want:
                return payload
            if cmd != BEACON_ID:
                raise ValueError(f"unexpected reply 0x{cmd:04X}")

    def erase(self):
        """0x0530 -- erases the application area. No reply is sent."""
        self._send(struct.pack("<HHI", ERASE_ID, 4, self.timestamp))

    def drain(self):
        """Drop beacons buffered before the erase stopped them."""
        self.ser.reset_input_buffer()

    def write_block(self, offset, total, data):
        """0x0519 -- program 256 bytes. Offset and total are BIG endian."""
        assert len(data) == BLOCK
        payload = (struct.pack("<HH", WRITE_ID, 4 + 8 + BLOCK)
                   + struct.pack("<I", self.timestamp)
                   + struct.pack(">HH", offset, total)
                   + b"\x00\x00\x00\x00"
                   + data)
        self._send(payload)
        reply = self._recv_expect(WRITE_ACK)
        echoed = struct.unpack(">H", reply[8:10])[0]
        if echoed != offset:
            raise ValueError(f"radio acked offset 0x{echoed:04X}, sent 0x{offset:04X}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="firmware image, raw (firmware.bin) or packed (QRCK*.bin)")
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--no-beacon", action="store_true",
                    help="do not wait for the beacon (use if the radio is already mid-session)")
    args = ap.parse_args()

    data = open(args.file, "rb").read()

    # Accept either the raw build output or the packed image the uploaders use.
    ok, detail = looks_like_raw_firmware(data)
    if ok:
        image, kind = data, "raw image"
    else:
        raw_problem = detail
        try:
            image, version = unpack_image(data)
        except ValueError as e:
            sys.exit(f"{args.file} is not a firmware image.\n"
                     f"  as raw:    {raw_problem}\n"
                     f"  as packed: {e}")
        ok, detail = looks_like_raw_firmware(image)
        if not ok:
            sys.exit(f"{args.file} unpacked cleanly but the result is not firmware ({detail})")
        kind = f"packed image, version {version!r}"

    if len(image) > FLASH_LIMIT:
        sys.exit(f"{len(image)} bytes exceeds the {FLASH_LIMIT} byte application area")

    padded = image + b"\xFF" * (-len(image) % BLOCK)
    total = len(padded)
    print(f"{args.file}: {len(image)} bytes [{kind}] ({detail})")
    print(f"  padded to {total} bytes = {total // BLOCK} blocks of {BLOCK}")

    if not args.yes:
        print("\nThis ERASES the application area before writing.")
        print("The bootloader is not touched, so a failed run can simply be repeated.")
        if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("aborted")

    radio = Bootloader(args.port, verbose=args.verbose)
    try:
        print(f"\nOpening {args.port}")
        if not args.no_beacon:
            print("  waiting for bootloader beacon (power on holding the flash key)...")
            version = radio.wait_for_beacon()
            if version is None:
                sys.exit("  no 0x0518 beacon seen -- is the radio in flash mode?")
            print(f"  bootloader: {version!r}")

        print("  erasing application area...")
        radio.erase()
        time.sleep(2.0)          # 120 page erases, and no reply to wait on
        radio.drain()            # discard beacons buffered before the erase landed

        for i in range(total // BLOCK):
            off = i * BLOCK
            radio.write_block(off, total, padded[off:off + BLOCK])
            pct = 100 * (i + 1) // (total // BLOCK)
            print(f"\r  writing {off + BLOCK}/{total} bytes ({pct}%)", end="", flush=True)
        print()
        print("  done -- the radio reboots into the new firmware")
        return 0
    except Exception as e:
        print(f"\n  FAILED: {e}")
        print("  The application area may be partially written. The bootloader is")
        print("  intact, so power-cycle into flash mode and run this again.")
        return 1
    finally:
        radio.close()


if __name__ == "__main__":
    sys.exit(main())

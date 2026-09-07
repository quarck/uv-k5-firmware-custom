#!/usr/bin/env python3
"""
k5eeprom.py -- read/write UV-K5 EEPROM over the programming cable.

K5TOOL is hard-limited to the stock 8 KB EEPROM (it rejects any offset >= 0x2000).
The radio's own protocol is not: commands 0x051B (read) and 0x051D (write) carry a
16-bit offset, so every byte below 64 KB is reachable. This talks to that protocol
directly.

Wire frame:
    AB CD | size(LE16) | obfuscate(payload ++ crc16_xmodem(payload)) | DC BA

Replies use the same envelope but carry two obfuscation-derived padding bytes in
place of the CRC.

Every constant here is taken from this repo: the key and framing from app/uart.c,
the CRC from driver/crc.c, and the 128-byte transfer cap from REPLY_051B_t.
"""

import argparse
import random
import struct
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial is required:  pip install pyserial")

# app/uart.c: static const uint8_t Obfuscation[16]
OBFUSCATION = bytes(
    (0x16, 0x6C, 0x14, 0xE6, 0x2E, 0x91, 0x0D, 0x40,
     0x21, 0x35, 0xD5, 0x40, 0x13, 0x03, 0xE9, 0x80)
)

HDR = b"\xAB\xCD"
FTR = b"\xDC\xBA"

# REPLY_051B_t caps a read at Data[128]; use the same for writes so both
# directions stay well inside UART_Command.Buffer[256].
BLOCK = 128

# 0x051B/0x051D carry a 16-bit offset. 0x052B/0x0538 carry a full 32-bit address
# (high half in Offset, low half in the trailing bytes) but only exist when the
# firmware is built with ENABLE_EEPROM_32BIT=1 (or ENABLE_CHINESE_FULL=4).
EEPROM_16BIT_LIMIT = 0x10000
EEPROM_LIMIT = 0x80000  # 4 Mbit: all driver/eeprom.c can page to


def crc16(data: bytes) -> int:
    """CRC-16/XMODEM, matching CRC_Calculate1() in driver/crc.c."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def obfuscate(data: bytes) -> bytes:
    return bytes(b ^ OBFUSCATION[i % 16] for i, b in enumerate(data))


def frame(payload: bytes) -> bytes:
    body = payload + struct.pack("<H", crc16(payload))
    return HDR + struct.pack("<H", len(payload)) + obfuscate(body) + FTR


class Radio:
    def __init__(self, port, baud=38400, timeout=2.0, verbose=False):
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.timestamp = random.getrandbits(32)
        self.verbose = verbose

    def close(self):
        self.ser.close()

    def _send(self, payload):
        if self.verbose:
            print(f"    TX {payload[:12].hex()}{'...' if len(payload) > 12 else ''}")
        self.ser.reset_input_buffer()
        self.ser.write(frame(payload))
        self.ser.flush()

    def _recv(self, deadline_s=3.0):
        """Read one reply frame and return its de-obfuscated payload."""
        # Resynchronise on the AB CD header; the radio emits unsolicited chatter.
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
            raise TimeoutError("no reply header (radio not in programming mode?)")

        raw = self.ser.read(2)
        if len(raw) != 2:
            raise TimeoutError("truncated reply size")
        size = struct.unpack("<H", raw)[0]
        if size > 512:
            raise ValueError(f"implausible reply size {size}")

        body = self.ser.read(size + 4)  # payload + 2 padding + 2 footer
        if len(body) < size + 4:
            raise TimeoutError("truncated reply body")
        if body[size + 2:size + 4] != FTR:
            raise ValueError("bad reply footer")
        return obfuscate(body[:size])

    def hello(self):
        """0x0514 -- establishes the session timestamp the radio expects."""
        self._send(struct.pack("<HHI", 0x0514, 4, self.timestamp))
        reply = self._recv()
        cmd = struct.unpack("<H", reply[:2])[0]
        if cmd != 0x0515:
            raise ValueError(f"unexpected hello reply 0x{cmd:04X}")
        version = reply[4:20].split(b"\x00")[0].decode("ascii", "replace")
        return version

    def read(self, offset, size):
        """0x051B -- read up to BLOCK bytes."""
        payload = struct.pack("<HHHBBI", 0x051B, 8, offset, size, 0, self.timestamp)
        self._send(payload)
        reply = self._recv()
        cmd = struct.unpack("<H", reply[:2])[0]
        if cmd != 0x051C:
            raise ValueError(f"unexpected read reply 0x{cmd:04X}")
        got_off, got_size = struct.unpack("<HB", reply[4:7])
        if got_off != offset:
            raise ValueError(f"radio answered offset 0x{got_off:04X}, wanted 0x{offset:04X}")
        return reply[8:8 + got_size]

    def read32(self, offset, size):
        """0x052B -- read with a full 32-bit address.

        CMD_051B_t puts the high half in Offset and the low half in ADD[2]
        (little endian); the firmware reassembles
        (Offset << 16) + (ADD[1] << 8) + ADD[0]."""
        payload = (struct.pack("<HHHBBI", 0x052B, 10, offset >> 16,
                               size, 0, self.timestamp)
                   + struct.pack("<H", offset & 0xFFFF))
        self._send(payload)
        reply = self._recv()
        cmd = struct.unpack("<H", reply[:2])[0]
        if cmd != 0x051C:
            raise ValueError(f"unexpected read reply 0x{cmd:04X}")
        return reply[8:8 + reply[6]]

    def write32(self, offset, data):
        """0x0538 -- write with a full 32-bit address.

        CMD_051D_t reuses Data[0..1] as the low half of the address, so the
        payload carries two extra bytes and Size counts them."""
        payload = (struct.pack("<HH", 0x0538, 4 + 2 + len(data) + 4)
                   + struct.pack("<HBB", offset >> 16, 2 + len(data), 0)
                   + struct.pack("<I", self.timestamp)
                   + struct.pack("<H", offset & 0xFFFF)
                   + data)
        self._send(payload)
        reply = self._recv(deadline_s=5.0)   # each write re-runs SETTINGS_InitEEPROM()
        cmd = struct.unpack("<H", reply[:2])[0]
        if cmd != 0x051E:
            raise ValueError(f"unexpected write reply 0x{cmd:04X}")

    def write(self, offset, data):
        """0x051D -- write up to BLOCK bytes."""
        payload = struct.pack("<HHHBBI", 0x051D, 8 + len(data), offset,
                              len(data), 0, self.timestamp) + data
        self._send(payload)
        reply = self._recv()
        cmd = struct.unpack("<H", reply[:2])[0]
        if cmd != 0x051E:
            raise ValueError(f"unexpected write reply 0x{cmd:04X}")


    def do_read(self, offset, size, use32):
        return self.read32(offset, size) if use32 else self.read(offset, size)

    def do_write(self, offset, data, use32):
        return self.write32(offset, data) if use32 else self.write(offset, data)


def needs_32bit(offset, length):
    """0x051B/0x051D can only carry a 16-bit offset."""
    return offset + length > EEPROM_16BIT_LIMIT


def chunks(offset, total):
    done = 0
    while done < total:
        n = min(BLOCK, total - done)
        yield offset + done, n
        done += n


def check_range(offset, length):
    end = offset + length
    if offset < 0 or end > EEPROM_LIMIT:
        sys.exit(f"range 0x{offset:X}..0x{end:X} exceeds the addressable "
                 f"EEPROM space of 0x{EEPROM_LIMIT:X}")


def progress(done, total, label):
    pct = 100 * done // total if total else 100
    print(f"\r  {label} {done}/{total} bytes ({pct}%)", end="", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("read", help="read EEPROM to a file")
    p.add_argument("offset", type=lambda s: int(s, 0))
    p.add_argument("size", type=lambda s: int(s, 0))
    p.add_argument("file")

    p = sub.add_parser("write", help="write a file to EEPROM (verifies afterwards)")
    p.add_argument("offset", type=lambda s: int(s, 0))
    p.add_argument("file")
    p.add_argument("--no-verify", action="store_true")

    p = sub.add_parser("verify", help="compare EEPROM against a file")
    p.add_argument("offset", type=lambda s: int(s, 0))
    p.add_argument("file")

    args = ap.parse_args()

    radio = Radio(args.port, verbose=args.verbose)
    try:
        print(f"Opening {args.port}")
        version = radio.hello()
        print(f"  Firmware: {version!r}")

        if args.cmd == "read":
            check_range(args.offset, args.size)
            use32 = needs_32bit(args.offset, args.size)
            print(f"  using {'32' if use32 else '16'}-bit EEPROM commands")
            out = bytearray()
            for off, n in chunks(args.offset, args.size):
                out += radio.do_read(off, n, use32)
                progress(len(out), args.size, "read")
            print()
            open(args.file, "wb").write(bytes(out))
            print(f"  wrote {len(out)} bytes to {args.file}")
            return 0

        data = open(args.file, "rb").read()
        check_range(args.offset, len(data))
        use32 = needs_32bit(args.offset, len(data))
        print(f"  using {'32' if use32 else '16'}-bit EEPROM commands"
              + (" (needs ENABLE_EEPROM_32BIT=1 firmware)" if use32 else ""))

        if args.cmd == "write":
            print(f"  writing {len(data)} bytes at 0x{args.offset:X}")
            done = 0
            for off, n in chunks(args.offset, len(data)):
                radio.do_write(off, data[done:done + n], use32)
                done += n
                progress(done, len(data), "write")
            print()
            if args.no_verify:
                return 0

        # verify (also the tail of a write)
        print(f"  verifying {len(data)} bytes at 0x{args.offset:X}")
        got = bytearray()
        for off, n in chunks(args.offset, len(data)):
            got += radio.do_read(off, n, use32)
            progress(len(got), len(data), "verify")
        print()
        if bytes(got) == data:
            print("  OK - EEPROM matches the file exactly")
            return 0
        bad = [i for i, (a, b) in enumerate(zip(got, data)) if a != b]
        print(f"  MISMATCH - {len(bad)} of {len(data)} bytes differ; "
              f"first at file offset {bad[0]} (EEPROM 0x{args.offset + bad[0]:X})")
        return 1
    finally:
        radio.close()


if __name__ == "__main__":
    sys.exit(main())

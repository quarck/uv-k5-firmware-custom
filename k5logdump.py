#!/usr/bin/env python3
"""
k5logdump.py -- pull a spectrum-logger session out of the radio's EEPROM.

The logger build (ENABLE_SPECTRUM_LOGGER=1) records one 64-byte frame every 30
seconds: the mean power of each of 128 bins over that window, one byte per bin,
as an absolute dBm (byte = dBm + 185) with the band correction already applied. This reads the
header, works out how much is valid, fetches only that, and writes CSV.

The wire protocol is k5eeprom.py's -- same session, same 128-byte transfers --
so this is only the layout on top of it. Layout is defined in app/speclog.c and
must be changed in both places together.

    python k5logdump.py -p /dev/ttyUSB0 info
    python k5logdump.py -p /dev/ttyUSB0 dump session.csv
    python k5logdump.py -p /dev/ttyUSB0 wipe                  # forget the old session
    python k5logdump.py --image eeprom.bin dump session.csv   # offline
"""

import argparse
import struct
import sys

from k5eeprom import Radio, BLOCK

# --- app/speclog.h / app/speclog.c ------------------------------------------
HEADER_ADDR = 0x03000
STAMP = 128                        # header record, and each block's first record
BLOCK_SIZE = STAMP * 128           # 16 KiB
BINS = 128
BIN_BITS = 8                       # one byte per bin
FRAME_BYTES = BINS * BIN_BITS // 8                      # 128
FRAMES_PER_BLOCK = (BLOCK_SIZE - STAMP) // FRAME_BYTES  # 127
FORMAT_VERSION = 4

# Level ladder, as the firmware currently builds it. These are only a sanity
# reference: the real ladder and the frame geometry are read from each file's
# header, so a radio built with a different step or bin width still reads here.
DBM_BASE = -185
DBM_STEP = 1
LEVELS = 1 << BIN_BITS

# One contiguous run, ending at 0x3C000 to leave the SI4732 SSB patch at
# 0x3C228 alone. Must match LOG_BLOCK_BASE / LOG_BLOCKS_TOTAL in app/speclog.h.
BLOCK_BASE = 0x04000
BLOCKS_TOTAL = 14
FRAMES_TOTAL = BLOCKS_TOTAL * FRAMES_PER_BLOCK

HEADER_MAGIC = b"K5SL"
BLOCK_MAGIC = b"K5LB"


def block_addr(index):
    """Same as BlockAddr() in app/speclog.c."""
    if not 0 <= index < BLOCKS_TOTAL:
        raise IndexError(f"block {index} is past the end of the store")
    return BLOCK_BASE + index * BLOCK_SIZE


def frame_addr(frame):
    """Absolute address of global frame number `frame`."""
    block, within = divmod(frame, FRAMES_PER_BLOCK)
    return block_addr(block) + STAMP + within * FRAME_BYTES


def unpack(frame, bits):
    """Frame bytes to one level per bin.

    8 bits is a byte a bin. 4 bits packs two, bin 2n in the low nibble of byte n
    and bin 2n+1 in the high nibble - kept so logs from the 4-bit firmware still
    read.
    """
    if bits == 8:
        return list(frame)

    out = []
    for b in frame:
        out.append(b & 0x0F)
        out.append(b >> 4)
    return out


class Source:
    """Either a live radio or a previously saved EEPROM image."""

    def __init__(self, port=None, image=None, verbose=False):
        self.radio = None
        self.image = None
        self.image_path = image
        self.dirty = False
        if image:
            self.image = bytearray(open(image, "rb").read())
        else:
            self.radio = Radio(port, verbose=verbose)
            print(f"Opening {port}")
            print(f"  Firmware: {self.radio.hello()!r}")

    def read(self, offset, size):
        if self.image is not None:
            if offset + size > len(self.image):
                sys.exit(f"image is only {len(self.image)} bytes, "
                         f"need 0x{offset + size:X}")
            return self.image[offset:offset + size]

        out = bytearray()
        while len(out) < size:
            n = min(BLOCK, size - len(out))
            # Everything above 64 KiB needs the 32-bit commands, which is most
            # of the store, so ask for them whenever the address requires it.
            off = offset + len(out)
            out += (self.radio.read32(off, n) if off + n > 0x10000
                    else self.radio.read(off, n))
        return bytes(out)

    def write(self, offset, data):
        if self.image is not None:
            self.image[offset:offset + len(data)] = data
            self.dirty = True
            return

        done = 0
        while done < len(data):
            n = min(BLOCK, len(data) - done)
            off = offset + done
            chunk = data[done:done + n]
            # Above 64 KiB only the 32-bit command can reach, and that needs an
            # ENABLE_EEPROM_32BIT firmware -- which the logger build is.
            if off + n > 0x10000:
                self.radio.write32(off, chunk)
            else:
                self.radio.write(off, chunk)
            done += n

    def close(self):
        if self.radio:
            self.radio.close()
        elif self.dirty:
            open(self.image_path, "wb").write(bytes(self.image))


class Header:
    def __init__(self, raw):
        if raw[:4] != HEADER_MAGIC:
            sys.exit(f"no logger header at 0x{HEADER_ADDR:X} "
                     f"(found {raw[:4]!r}) -- was anything ever logged?")
        self.version = raw[4]
        self.bins = raw[5]
        self.bin_bits = raw[6]
        self.flags = raw[7]
        self.f_start, self.f_step = struct.unpack_from("<II", raw, 0x08)
        self.avg_seconds, self.frames_per_block = struct.unpack_from("<HH", raw, 0x10)
        self.blocks = raw[0x14]
        self.band = raw[0x15]
        self.dbm_corr = struct.unpack_from("<b", raw, 0x16)[0]
        self.start_clock, self.session = struct.unpack_from("<II", raw, 0x18)
        self.frames, self.seconds = struct.unpack_from("<II", raw, 0x20)
        self.dbm_base = struct.unpack_from("<h", raw, 0x28)[0]
        self.dbm_step = raw[0x2A]
        self.levels = 1 << self.bin_bits      # 256 would not fit in a header byte

        if self.version not in (3, 4):
            sys.exit(f"header says format version {self.version}, this tool "
                     f"speaks 3 and 4. Versions 1 and 2 never ran outside "
                     f"the workbench.")
        if self.bins != BINS or self.bin_bits not in (4, 8):
            sys.exit(f"unexpected frame shape: {self.bins} bins x "
                     f"{self.bin_bits} bits")

        # Geometry follows the header, not this tool's defaults, so a log made
        # by a differently built radio still reads.
        self.frame_bytes = self.bins * self.bin_bits // 8
        if self.frames_per_block != (BLOCK_SIZE - STAMP) // self.frame_bytes:
            sys.exit(f"header says {self.frames_per_block} frames of "
                     f"{self.frame_bytes} B per {BLOCK_SIZE} B block, which "
                     f"does not fit")
        # The ladder is taken from the header rather than assumed, so changing
        # LOG_DBM_STEP in the firmware needs no change here. Only reject a
        # ladder that cannot be right.
        if not 0 < self.dbm_step <= 50:
            sys.exit(f"implausible ladder: {self.levels} levels of "
                     f"{self.dbm_step} dB from {self.dbm_base} dBm")
        if (self.dbm_base, self.dbm_step) != (DBM_BASE, DBM_STEP):
            print(f"  note: this file's ladder ({self.dbm_step} dB from "
                  f"{self.dbm_base} dBm) is not the one the firmware builds "
                  f"today ({DBM_STEP} dB from {DBM_BASE} dBm)")
        # The block count has to match - it is where the frames physically are.
        # frames_per_block does not: it follows from the bin width, checked below.
        if self.blocks != BLOCKS_TOTAL:
            sys.exit(f"radio says {self.blocks} blocks, this tool is built for "
                     f"{BLOCKS_TOTAL} (0x{BLOCK_BASE:X} upwards)")

    @property
    def closed(self):
        return bool(self.flags & 1)



    def bin_hz(self, i):
        """Centre frequency of bin i, in Hz. Firmware works in 10 Hz units."""
        return (self.f_start + i * self.f_step) * 10

    def dbm(self, level):
        """Level to dBm. Level 0 means "at or below", level 15 "at or above"."""
        return self.dbm_base + level * self.dbm_step


def hhmmss(seconds):
    seconds %= 86400
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def describe(hdr):
    span = hdr.f_step * BINS * 10
    print(f"  session      0x{hdr.session:08X}"
          f"{'  (closed cleanly)' if hdr.closed else '  (NOT closed -- still running, or cut short)'}")
    print(f"  started      {hhmmss(hdr.start_clock)}")
    print(f"  band         {hdr.bin_hz(0) / 1e6:.4f} - {hdr.bin_hz(BINS - 1) / 1e6:.4f} MHz"
          f"  ({hdr.f_step * 10 / 1000:g} kHz bins, {span / 1e6:g} MHz span)")
    print(f"  frames       {hdr.frames} of {FRAMES_TOTAL}"
          f"  ({hdr.avg_seconds}s each, {hdr.seconds}s logged)")
    print(f"  values       mean power, {hdr.bin_bits} bits/bin, "
          f"{hdr.dbm_step} dB steps"
          f" ({hdr.dbm(0)} to {hdr.dbm(hdr.levels - 1)} dBm)")
    if not hdr.closed:
        print(f"  the counter is only rewritten at a 16 KiB boundary, so up to "
              f"{hdr.frames_per_block - 1} more frames may be present than it "
              f"says; pass --frames to reach them")


def read_blocks(src, hdr, frames):
    """Yield (frame_index, wall_clock, [values]) for the first `frames` frames."""
    blocks = (frames + hdr.frames_per_block - 1) // hdr.frames_per_block

    for b in range(blocks):
        base = block_addr(b)
        stamp = src.read(base, 32)
        if stamp[:4] != BLOCK_MAGIC:
            print(f"  warning: block {b} at 0x{base:X} has no {BLOCK_MAGIC!r} "
                  f"stamp; stopping here", file=sys.stderr)
            return
        idx, = struct.unpack_from("<H", stamp, 4)
        wall, elapsed, before = struct.unpack_from("<III", stamp, 8)
        if idx != b:
            print(f"  warning: block {b} stamped as {idx}; leftovers from an "
                  f"older session? stopping", file=sys.stderr)
            return

        first = b * hdr.frames_per_block
        n = min(hdr.frames_per_block, frames - first)
        data = src.read(base + STAMP, n * hdr.frame_bytes)

        for i in range(n):
            # Within a block the time is interpolated from its stamp, so the
            # clock stays honest even though EEPROM writes steal time from the
            # 30 s cadence.
            yield (first + i, wall + i * hdr.avg_seconds,
                   unpack(data[i * hdr.frame_bytes:(i + 1) * hdr.frame_bytes],
                          hdr.bin_bits))


def wipe(src):
    """Zero the header and every block stamp.

    That is 9 records rather than the whole 128 KiB: without a header the store
    reads as empty, and without its stamp a block cannot be walked, so the old
    frames become unreachable even with --frames. Zeroing all of it would mean
    16k page writes at 10 ms each -- about three minutes -- for no more effect.
    """
    blank = bytes(STAMP)
    src.write(HEADER_ADDR, blank)
    for b in range(BLOCKS_TOTAL):
        src.write(block_addr(b), blank)
    print(f"  wiped the header and {BLOCKS_TOTAL} block stamps "
          f"({(BLOCKS_TOTAL + 1) * STAMP} bytes); the store now reads as empty")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    ap.add_argument("--image", help="read from a saved EEPROM image instead of a radio")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show the header and stop")

    p = sub.add_parser("wipe", help="make the stored session unreadable")
    p.add_argument("--yes", action="store_true", help="do not ask")

    p = sub.add_parser("dump", help="write the session out as CSV")
    p.add_argument("file")
    p.add_argument("--frames", type=int,
                   help="read this many frames instead of what the header claims")
    p.add_argument("--raw", action="store_true",
                   help="emit the stored 0-15 levels rather than dBm")

    p = sub.add_parser("save", help="save the raw log region to a file")
    p.add_argument("file")

    args = ap.parse_args()
    src = Source(None if args.image else args.port, args.image, args.verbose)
    try:
        if args.cmd == "wipe":
            raw = src.read(HEADER_ADDR, STAMP)
            if raw[:4] != HEADER_MAGIC:
                print("  no logger header found -- nothing to wipe")
                return 0
            describe(Header(raw))
            if not args.yes:
                if input("  wipe this session? [y/N] ").strip().lower() != "y":
                    print("  left alone")
                    return 1
            wipe(src)
            return 0

        hdr = Header(src.read(HEADER_ADDR, STAMP))
        describe(hdr)

        if args.cmd == "info":
            return 0

        if args.cmd == "save":
            out = bytearray(src.read(HEADER_ADDR, STAMP))
            for b in range(BLOCKS_TOTAL):
                out += src.read(block_addr(b), BLOCK_SIZE)
            open(args.file, "wb").write(bytes(out))
            print(f"  wrote {len(out)} bytes to {args.file}")
            return 0

        frames = args.frames if args.frames is not None else hdr.frames
        if frames > FRAMES_TOTAL:
            sys.exit(f"asked for {frames} frames, the store holds {FRAMES_TOTAL}")
        if frames == 0:
            sys.exit("header says zero frames -- nothing to dump")

        with open(args.file, "w") as f:
            f.write("time," + ",".join(f"{hdr.bin_hz(i) / 1e6:.5f}"
                                       for i in range(BINS)) + "\n")
            written = 0
            for _, wall, values in read_blocks(src, hdr, frames):
                row = (values if args.raw else [hdr.dbm(v) for v in values])
                f.write(hhmmss(wall) + "," + ",".join(str(v) for v in row) + "\n")
                written += 1
                if written % 16 == 0 or written == frames:
                    print(f"\r  read {written}/{frames} frames", end="", flush=True)
        print()
        print(f"  wrote {written} rows x {BINS} bins to {args.file}")
        return 0
    finally:
        src.close()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
k5logdump.py -- pull a spectrum-logger session out of the radio's EEPROM.

The logger build (ENABLE_SPECTRUM_LOGGER=1) records one 64-byte frame every 30
seconds: for each of 128 bins, either the mean power over that window or the
strongest reading in it, whichever mode the operator chose. One byte per bin, an
absolute dBm (byte = dBm + 185) with the band correction already applied. This reads the
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

# --- app/speclog.h (narrow, v6) and app/widelog.h (wide, v7) ---------------
# Two loggers share the store but not its layout, so the header's version says
# which to expect:
#
#   v6 NARROW  128 bins, 30 s frames. 15 blocks of 16 KiB from 0x04000, each a
#              128-byte stamp then 127 frames.
#   v7 WIDE    8192 bins, 1 h frames. A stamp table at 0x03080, then frames
#              packed back to back from 0x04000.
#
# Geometry comes from the header in both cases; these are the sanity reference.
HEADER_ADDR = 0x03000
HEADER_BYTES = 128
FRAME_BASE = 0x04000
STORE_BYTES = 0x40000 - FRAME_BASE          # 245,760

# v6
BLOCK_SIZE = 16384
BLOCK_STAMP = 128

# v7
STAMP_BASE = 0x03080
STAMP_BYTES = 32
STAMP_MAX = (FRAME_BASE - STAMP_BASE) // STAMP_BYTES        # 124

DBM_BASE = -185
DBM_STEP = 1

HEADER_MAGIC = b"K5SL"
BLOCK_MAGIC = b"K5LB"


def unpack(frame, bits):
    """Frame bytes to one level per bin. 8 bits is a byte a bin; 4 bits packs
    two, low nibble first - kept so logs from the 4-bit firmware still read."""
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
    """The common fields, then whichever layout the version implies."""

    def __init__(self, raw):
        if raw[:4] != HEADER_MAGIC:
            sys.exit(f"no logger header at 0x{HEADER_ADDR:X} "
                     f"(found {raw[:4]!r}) -- was anything ever logged?")
        self.version = raw[4]
        if self.version not in (6, 7):
            sys.exit(f"header says format version {self.version}; this tool "
                     f"speaks 6 (narrow) and 7 (wide)")

        self.flags = raw[0x07]
        self.f_start, self.f_step = struct.unpack_from("<II", raw, 0x08)
        self.start_clock, self.session = struct.unpack_from("<II", raw, 0x18)
        self.frames, self.seconds = struct.unpack_from("<II", raw, 0x20)
        self.dbm_base = struct.unpack_from("<h", raw, 0x28)[0]
        self.dbm_step = raw[0x2A]

        if self.version == 6:
            self.name = "NARROW"
            self.bins = raw[0x05]
            self.bin_bits = raw[0x06]
            self.window = struct.unpack_from("<H", raw, 0x10)[0]
            self.per_block = struct.unpack_from("<H", raw, 0x12)[0]
            self.blocks = raw[0x14]
            self.frame_bytes = self.bins * self.bin_bits // 8
            self.frames_total = self.per_block * self.blocks
            self.stamp_every = self.per_block
            if self.per_block != (BLOCK_SIZE - BLOCK_STAMP) // self.frame_bytes:
                sys.exit(f"v6 header says {self.per_block} frames of "
                         f"{self.frame_bytes} B per {BLOCK_SIZE} B block, "
                         f"which does not fit")
        else:
            self.name = "WIDE"
            self.bins = struct.unpack_from("<H", raw, 0x05)[0]
            self.bin_bits = raw[0x2B]
            self.window, self.frames_total = struct.unpack_from("<HH", raw, 0x10)
            self.stamp_every = raw[0x14]
            self.frame_bytes = self.bins * self.bin_bits // 8
            self.frame_base, self.stamp_base = struct.unpack_from("<II", raw, 0x2C)
            if self.frame_base + self.frames_total * self.frame_bytes > 0x40000:
                sys.exit(f"{self.frames_total} frames of {self.frame_bytes} B "
                         f"from 0x{self.frame_base:X} would run off the chip")

        if not 0 < self.bins <= 8192 or self.bin_bits not in (4, 8):
            sys.exit(f"implausible frame shape: {self.bins} bins x "
                     f"{self.bin_bits} bits")
        if not 0 < self.dbm_step <= 50:
            sys.exit(f"implausible ladder: {self.dbm_step} dB from {self.dbm_base}")
        if not 0 < self.stamp_every <= max(1, self.frames_total):
            sys.exit(f"implausible stamp interval {self.stamp_every}")

    # --- where things are, per layout --------------------------------------
    def frame_addr(self, i):
        if self.version == 6:
            blk, within = divmod(i, self.per_block)
            return (FRAME_BASE + blk * BLOCK_SIZE + BLOCK_STAMP
                    + within * self.frame_bytes)
        return self.frame_base + i * self.frame_bytes

    def stamp_addr(self, i):
        """i is the stamp index, not the frame index."""
        if self.version == 6:
            return FRAME_BASE + i * BLOCK_SIZE
        return self.stamp_base + i * STAMP_BYTES

    @property
    def stamp_count(self):
        return (self.frames_total + self.stamp_every - 1) // self.stamp_every

    @property
    def closed(self):
        return bool(self.flags & 1)

    @property
    def statistic(self):
        return ("strongest reading in each window" if self.flags & 2
                else "mean power over each window")

    def bin_hz(self, i):
        """Centre frequency of bin i, in Hz. Firmware counts in 10 Hz units."""
        return (self.f_start + i * self.f_step) * 10

    def dbm(self, level):
        return self.dbm_base + level * self.dbm_step


def hhmmss(seconds):
    seconds %= 86400
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def describe(hdr):
    span = hdr.bins * hdr.f_step * 10
    print(f"  profile      {hdr.name} (v{hdr.version}): {hdr.bins} bins x "
          f"{hdr.f_step * 10 / 1000:g} kHz = {span / 1e6:g} MHz, "
          f"{hdr.window} s per frame")
    print(f"  session      0x{hdr.session:08X}"
          f"{'  (closed cleanly)' if hdr.closed else '  (NOT closed -- still running, or cut short)'}")
    print(f"  started      {hhmmss(hdr.start_clock)}")
    print(f"  band         {hdr.bin_hz(0) / 1e6:.4f} - "
          f"{hdr.bin_hz(hdr.bins - 1) / 1e6:.4f} MHz")
    print(f"  frames       {hdr.frames} of {hdr.frames_total}"
          f"  ({hdr.seconds} s logged)")
    print(f"  values       {hdr.statistic}, {hdr.bin_bits} bits/bin, "
          f"{hdr.dbm_step} dB steps"
          f" ({hdr.dbm(0)} to {hdr.dbm((1 << hdr.bin_bits) - 1)} dBm)")
    if not hdr.closed:
        print(f"  the counter is only rewritten every {hdr.stamp_every} frames, so "
              f"up to {hdr.stamp_every - 1} more may be present than it says;"
              f" pass --frames to reach them")


def read_frames(src, hdr, count):
    """Yield (index, wall_clock, [levels]) for the first `count` frames.

    Each stamp covers hdr.stamp_every frames and carries the real clock for the
    first of them, so time inside a group is interpolated from the window - the
    writes steal seconds from the cadence and the stamps are what correct it."""
    wall = hdr.start_clock
    first_of_group = 0

    for i in range(count):
        if i % hdr.stamp_every == 0:
            idx = i // hdr.stamp_every
            if idx >= hdr.stamp_count:
                print(f"  warning: stamp {idx} is past the last one; stopping",
                      file=sys.stderr)
                return
            st = src.read(hdr.stamp_addr(idx), STAMP_BYTES)
            if st[:4] != BLOCK_MAGIC:
                print(f"  warning: frame {i} has no {BLOCK_MAGIC!r} stamp at "
                      f"0x{hdr.stamp_addr(idx):X}; stopping here", file=sys.stderr)
                return
            got_idx, = struct.unpack_from("<H", st, 4)
            if got_idx != idx:
                print(f"  warning: stamp {idx} is labelled {got_idx} -- leftovers "
                      f"from an older session? stopping", file=sys.stderr)
                return
            wall, _elapsed, _frame = struct.unpack_from("<III", st, 8)
            first_of_group = i

        raw = src.read(hdr.frame_addr(i), hdr.frame_bytes)
        yield (i, wall + (i - first_of_group) * hdr.window,
               unpack(raw, hdr.bin_bits))


def wipe(src, hdr):
    """Zero the header and every stamp, whichever layout they are in.

    A few hundred page writes rather than 240 KiB: with no header the store
    reads as empty, and with no stamps the frames carry no time, so nothing can
    be made of them. It is also how either logger reformats a store the other
    wrote - the radio's own start screen does the same thing."""
    src.write(HEADER_ADDR, bytes(HEADER_BYTES))
    n = hdr.stamp_count
    for i in range(n):
        src.write(hdr.stamp_addr(i), bytes(32))
    print(f"  wiped the header and {n} stamps; the store now reads as empty")


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
            raw = src.read(HEADER_ADDR, HEADER_BYTES)
            if raw[:4] != HEADER_MAGIC:
                print("  no logger header found -- nothing to wipe")
                return 0
            hdr = Header(raw)
            describe(hdr)
            if not args.yes:
                if input("  wipe this session? [y/N] ").strip().lower() != "y":
                    print("  left alone")
                    return 1
            wipe(src, hdr)
            return 0

        hdr = Header(src.read(HEADER_ADDR, HEADER_BYTES))
        describe(hdr)

        if args.cmd == "info":
            return 0

        if args.cmd == "save":
            out = bytearray(src.read(HEADER_ADDR, FRAME_BASE - HEADER_ADDR))
            out += src.read(FRAME_BASE, STORE_BYTES)
            open(args.file, "wb").write(bytes(out))
            print(f"  wrote {len(out)} bytes to {args.file}")
            return 0

        frames = args.frames if args.frames is not None else hdr.frames
        if frames > hdr.frames_total:
            sys.exit(f"asked for {frames} frames, the store holds "
                     f"{hdr.frames_total}")
        if frames == 0:
            sys.exit("header says zero frames -- nothing to dump")

        with open(args.file, "w") as f:
            f.write("time," + ",".join(f"{hdr.bin_hz(i) / 1e6:.5f}"
                                       for i in range(hdr.bins)) + "\n")
            written = 0
            for _, wall, values in read_frames(src, hdr, frames):
                row = (values if args.raw else [hdr.dbm(v) for v in values])
                f.write(hhmmss(wall) + "," + ",".join(str(v) for v in row) + "\n")
                written += 1
                if written % 16 == 0 or written == frames:
                    print(f"\r  read {written}/{frames} frames", end="", flush=True)
        print()
        print(f"  wrote {written} rows x {hdr.bins} bins to {args.file}")
        return 0
    finally:
        src.close()


if __name__ == "__main__":
    sys.exit(main())

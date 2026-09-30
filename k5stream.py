#!/usr/bin/env python3
"""
k5stream.py -- record the spectrum logger's live UART stream.

F+7 opens the spectrum analyser with its live stream on: once a second it pushes
out the strongest reading each bin saw in that second. This reads that stream,
checks each frame, and appends it to a CSV in exactly the shape k5logdump.py
writes - so k5logview.py renders a stream recording and a stored log the same
way.

Frames are timestamped by this host, not the radio, which has no clock.

The analyser is interactive, so its scan plan can change mid-capture. A CSV has
one fixed set of columns, so when the plan changes this starts a new numbered
file rather than silently mixing two bands into one.

    python k5stream.py -p /dev/ttyUSB0 stream.csv
    python k5stream.py -p /dev/ttyUSB0 stream.csv --quiet
    python k5stream.py --replay capture.bin stream.csv     # offline

Ctrl-C to stop; the CSV is flushed after every frame, so it survives being
killed, unplugged or run for days.
"""

import argparse
import struct
import sys
import time
from datetime import datetime

MAGIC = b"K5"
HEAD = 22
BINS = 128                        # the payload is always this long...
PACKET = HEAD + BINS + 2          # app/spectrum.h: SPECTRUM_STREAM_BYTES
VERSION = 2                       # 2 = per-bin maximum over one second


def crc16(data):
    """CRC-16/XMODEM, the same one CRC_Calculate1() in driver/crc.c computes."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class Frame:
    __slots__ = ("bins", "seq", "elapsed", "f_start", "f_step", "sweeps",
                 "dbm_base", "dbm_step", "corr", "levels")

    def __init__(self, pkt):
        # ...but only the first `bins` bytes of it mean anything: the analyser's
        # bin count is selectable, 16 to 128, and the packet stays a fixed size.
        self.bins = pkt[3]
        (self.seq, self.elapsed, self.f_start, self.f_step, self.sweeps,
         self.dbm_base, self.dbm_step, self.corr) = struct.unpack_from(
            "<HIIHHhBb", pkt, 4)
        self.levels = pkt[HEAD:HEAD + self.bins]

    @property
    def plan(self):
        return (self.f_start, self.f_step, self.bins)

    @property
    def dbm(self):
        return [self.dbm_base + v * self.dbm_step for v in self.levels]

    def freqs(self):
        """Bin centres in MHz. The radio counts in 10 Hz units."""
        return [(self.f_start + i * self.f_step) * 10 / 1e6
                for i in range(self.bins)]


def parse(pkt):
    """Validate one candidate packet; None if it is not a good frame."""
    if len(pkt) != PACKET or pkt[:2] != MAGIC:
        return None
    if pkt[2] != VERSION or not 0 < pkt[3] <= BINS:
        return None
    if crc16(pkt[:HEAD + BINS]) != struct.unpack_from("<H", pkt, HEAD + BINS)[0]:
        return None
    return Frame(pkt)


class Reader:
    """Pulls packets out of a byte stream, resynchronising on the magic.

    The cable can be plugged in mid-frame, and the radio answers nothing while
    streaming, so anything that is not a valid frame is simply skipped a byte
    at a time until one lines up.
    """

    def __init__(self, read, stop_on_empty=False):
        self.read = read
        # A live port returns nothing whenever the radio is between frames,
        # which is most of the time; a replay file returning nothing is the end
        # of it. Same loop, opposite meaning, so the caller says which.
        self.stop_on_empty = stop_on_empty
        self.buf = bytearray()

    def frames(self):
        while True:
            chunk = self.read(PACKET)
            done = self.stop_on_empty and not chunk
            self.buf += chunk or b""

            while len(self.buf) >= PACKET:
                at = self.buf.find(MAGIC)
                if at < 0:
                    self.buf = self.buf[-1:]      # keep a possible split magic
                    break
                if at:
                    del self.buf[:at]
                    continue
                if len(self.buf) < PACKET:
                    break
                frame = parse(bytes(self.buf[:PACKET]))
                if frame is None:
                    del self.buf[:1]              # false magic; slide on
                    yield None
                    continue
                del self.buf[:PACKET]
                yield frame

            if done:
                return


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="CSV to append to (created if new)")
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    ap.add_argument("-b", "--baud", type=int, default=38400)
    ap.add_argument("--replay", help="read raw bytes from a file instead of a port")
    ap.add_argument("--raw", help="also save the raw stream to this file")
    ap.add_argument("--quiet", action="store_true", help="no per-frame line")
    args = ap.parse_args()

    if args.replay:
        src = open(args.replay, "rb")
        read = lambda n: src.read(n)
    else:
        try:
            import serial
        except ImportError:
            sys.exit("pyserial is required:  pip install pyserial")
        try:
            src = serial.Serial(args.port, args.baud, timeout=1)
        except Exception as exc:                      # OSError, SerialException
            sys.exit(f"cannot open {args.port}: {exc}")
        read = lambda n: src.read(max(1, src.in_waiting or 1))
        print(f"Listening on {args.port} at {args.baud} baud. Ctrl-C to stop.")

    raw = open(args.raw, "ab") if args.raw else None

    def open_csv(path):
        f = open(path, "a+")
        f.seek(0)
        started_empty = not f.read(1)
        f.seek(0, 2)
        return f, started_empty

    out, empty = open_csv(args.csv)
    name = args.csv
    part = 1

    n = bad = lost = quiet_frames = 0
    prev_seq = None
    plan = None
    started = time.time()
    try:
        for frame in Reader(read, stop_on_empty=bool(args.replay)).frames():
            if frame is None:
                bad += 1
                continue

            if plan is not None and frame.plan != plan:
                # Someone turned the dial. A CSV has one set of columns, so
                # roll to a new file rather than mix two bands in one table.
                part += 1
                base = args.csv.rsplit(".", 1)
                name = (f"{base[0]}.{part}.{base[1]}" if len(base) == 2
                        else f"{args.csv}.{part}")
                print(f"  ! scan plan changed; continuing in {name}",
                      file=sys.stderr)
                out.close()
                out, empty = open_csv(name)
                plan = None

            if plan is None:
                plan = frame.plan
                if empty:
                    out.write("time," + ",".join(f"{f:.5f}" for f in frame.freqs())
                              + "\n")
                    empty = False

            if prev_seq is not None:
                gap = (frame.seq - prev_seq - 1) & 0xFFFF
                if gap:
                    lost += gap
                    print(f"  ! {gap} frame(s) lost before seq {frame.seq}",
                          file=sys.stderr)
            prev_seq = frame.seq

            now = datetime.now()
            out.write(now.strftime("%H:%M:%S") + "," +
                      ",".join(str(v) for v in frame.dbm) + "\n")
            out.flush()
            if raw:
                raw.flush()
            n += 1

            if frame.sweeps == 0:
                # The analyser stops sweeping while it listens to a signal, so
                # a second can pass with only a partial sweep or none at all.
                quiet_frames += 1

            if not args.quiet:
                peak = max(frame.dbm)
                at = frame.freqs()[frame.dbm.index(peak)]
                print(f"  {now:%H:%M:%S}  seq {frame.seq:5d}  "
                      f"{frame.sweeps:2d} swp  peak {peak:4d} dBm @ {at:.4f} MHz"
                      f"  [{n} frames, {bad} bad, {lost} lost]")
    except KeyboardInterrupt:
        print()
    finally:
        out.close()
        if raw:
            raw.close()
        src.close()

    mins = (time.time() - started) / 60
    print(f"  {n} frames written to {name} over {mins:.1f} min"
          f"  ({bad} rejected, {lost} lost"
          + (f", {quiet_frames} with no complete sweep" if quiet_frames else "")
          + ")")
    print(f"  render it with:  python k5logview.py {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

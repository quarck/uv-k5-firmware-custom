#!/usr/bin/env python3
"""
k5logview.py -- turn a k5logdump CSV into a self-contained HTML report.

One heat map for the whole recording: time down, frequency across, one pixel per
bin per frame. Shading is relative to the session's own noise floor rather than
an absolute level, because the floor moves with the band, the antenna and the
AGC - what matters is what rose out of it. Below the map is the text summary:
what the session was, and every bin that flared at least FLARE dB over that
floor, with when it was first and last seen.

The map is an inline PNG written by a small pure-Python encoder, so a 16-hour
session is one image rather than two hundred thousand table cells, and nothing
is fetched: the report is one file that works offline.

    python k5logview.py session.csv                 # -> session.html
    python k5logview.py session.csv -o report.html
    python k5logview.py session.csv --row-px 2      # taller map
    python k5logview.py session.csv --text          # terminal view
"""

import argparse
import base64
import csv
import html
import struct
import sys
import zlib
from datetime import datetime
from statistics import median

# Terminal view only.
STEP = 5
RAMP = " .:+*#@"
COLOURS = (244, 250, 228, 220, 208, 202, 199)

# Heat-map ramp, keyed by dB over the hour's floor. Dark and desaturated at the
# floor so that noise recedes, bright and warm where something stood up.
STOPS = ((0, (16, 20, 30)), (4, (26, 48, 92)), (8, (24, 106, 138)),
         (14, (32, 160, 112)), (20, (148, 194, 62)), (28, (246, 204, 60)),
         (38, (250, 124, 44)), (50, (255, 74, 74)))

# The byte a level is stored as in the report's hover data, matching the
# logger's own encoding so the two never disagree about what a byte means.
HOVER_BASE = -185


def hhmmss(seconds):
    seconds = int(seconds) % 86400
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def parse_time(text):
    h, m, s = (int(p) for p in text.split(":"))
    return h * 3600 + m * 60 + s


def load(path):
    """-> (freqs_mhz, [(timestamp, [dBm per bin])]), timestamps made monotonic."""
    with open(path) as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        sys.exit(f"{path}: need a header row and at least one frame")

    try:
        freqs = [float(x) for x in rows[0][1:]]
    except ValueError:
        sys.exit(f"{path}: first row must be the frequency header k5logdump writes")

    out, day, prev = [], 0, None
    for n, row in enumerate(rows[1:], 2):
        if len(row) != len(freqs) + 1:
            sys.exit(f"{path}:{n}: {len(row) - 1} values, header says {len(freqs)}")
        t = parse_time(row[0])
        if prev is not None and t < prev:
            day += 1          # the log carries time of day only; spot the wrap
        prev = t
        out.append((day * 86400 + t, [int(v) for v in row[1:]]))
    return freqs, out


def noise_floor(flat):
    """The hour's floor, and a note if the log clipped it.

    When the band is quieter than the lowest level the logger can store, most
    bins read that level and the median becomes the rail itself rather than a
    measurement - everything then looks 10 dB "over the floor". Where that
    happens, take the floor from the samples that did measure something and say
    so; the answer is a lower bound either way.
    """
    rail = min(flat)
    clipped = flat.count(rail) / len(flat)
    if clipped < 0.25:
        return int(median(flat)), None

    above = [v for v in flat if v > rail]
    floor = int(median(above)) if above else rail
    return floor, (f"{clipped:.0%} of samples sit at {rail} dBm, the bottom of "
                   f"the log's range - the true floor is below it, so this "
                   f"hour's floor is taken from the rest and flare sizes are "
                   f"lower bounds")


def analyse(frames, freqs, flare_db):
    """One pass over the whole recording: floor, flares, and when each was up."""
    flat = [v for _, values in frames for v in values]
    floor, clipping = noise_floor(flat)

    flares = []
    for i, f in enumerate(freqs):
        column = [values[i] for _, values in frames]
        peak = max(column)
        if peak - floor < flare_db:
            continue
        hits = [n for n, v in enumerate(column) if v - floor >= flare_db]
        flares.append({"freq": f, "peak": peak, "over": peak - floor,
                       "hits": len(hits), "frames": len(frames),
                       "first": frames[hits[0]][0], "last": frames[hits[-1]][0]})
    flares.sort(key=lambda d: (-d["peak"], d["freq"]))

    return {"floor": floor, "clipping": clipping, "flares": flares}


def hour_marks(frames):
    """Row indices where the clock hour changes, for the time axis."""
    marks = [(0, frames[0][0])]
    for n in range(1, len(frames)):
        if frames[n][0] // 3600 != frames[n - 1][0] // 3600:
            marks.append((n, frames[n][0]))
    if len(frames) > 1:
        marks.append((len(frames) - 1, frames[-1][0]))
    return marks


# ------------------------------------------------------------------- image ---

def ramp(delta):
    """dB over the floor -> rgb, linear between the stops."""
    if delta <= STOPS[0][0]:
        return STOPS[0][1]
    for (d0, c0), (d1, c1) in zip(STOPS, STOPS[1:]):
        if delta <= d1:
            k = (delta - d0) / (d1 - d0)
            return tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
    return STOPS[-1][1]


def png(width, height, rows_rgb):
    """Minimal 8-bit truecolour PNG. No dependencies, and small: a heat map is
    mostly flat colour, which is exactly what zlib is good at."""
    raw = b"".join(b"\x00" + row for row in rows_rgb)    # filter 0 per scanline

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def heat_png(frames, floor, bins):
    lut = {}
    rows = []
    for _, values in frames:
        row = bytearray()
        for v in values:
            d = v - floor
            if d not in lut:
                lut[d] = bytes(ramp(d))
            row += lut[d]
        rows.append(bytes(row))
    return png(bins, len(rows), rows)


def b64(data):
    return base64.b64encode(data).decode("ascii")


# -------------------------------------------------------------------- html ---

CSS = """
:root{--bg:#fbfbfa;--fg:#1a1a18;--dim:#6b6b66;--line:#e0e0dc;--card:#fff;
      --warn-bg:#fff6e0;--warn-fg:#7a5200;--accent:#2a5f8f}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
      --bg:#14161a;--fg:#e8e8e4;--dim:#9a9a94;--line:#2a2e35;--card:#1b1e24;
      --warn-bg:#3a2e12;--warn-fg:#f0cd7a;--accent:#7fb3e0}}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px 64px;background:var(--bg);color:var(--fg);
     font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:16px;margin:0 0 2px;font-variant-numeric:tabular-nums}
.sub{color:var(--dim);margin:0 0 24px}
.meta{font-weight:400;color:var(--dim);font-size:13px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;
        padding:16px;margin:0 0 18px}
.warn{background:var(--warn-bg);color:var(--warn-fg);border-radius:6px;
      padding:8px 10px;margin:10px 0 0;font-size:13px}
.map{display:grid;grid-template-columns:58px 1fr;margin-top:14px}
.tcol{position:relative}
.tcol span{position:absolute;right:8px;transform:translateY(-50%);
           font-size:11px;color:var(--dim);font-variant-numeric:tabular-nums;
           white-space:nowrap}
.tcol span::after{content:"";position:absolute;right:-6px;top:50%;width:4px;
                  height:1px;background:var(--rule)}
.img{position:relative}
.img img{display:block;width:100%;max-width:100%;min-height:48px;
         image-rendering:pixelated;image-rendering:crisp-edges;border-radius:2px}
.ruler{display:grid;grid-template-columns:58px 1fr;margin-top:3px}
.ruler div{position:relative;height:18px}
.ruler span{position:absolute;transform:translateX(-50%);font-size:11px;
            color:var(--dim);font-variant-numeric:tabular-nums;white-space:nowrap}
.readout{position:absolute;top:4px;right:6px;background:rgba(0,0,0,.72);
         color:#fff;font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
         padding:3px 6px;border-radius:4px;opacity:0;pointer-events:none;
         transition:opacity .1s;white-space:nowrap}
.tscroll{overflow-x:auto;margin-top:16px;border:1px solid var(--rule);
         border-radius:3px;background:var(--card)}
table{border-collapse:collapse;width:100%;margin-top:14px;font-size:13px;
      font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:4px 8px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
th{color:var(--dim);font-weight:600;font-size:12px}
tbody tr:last-child td{border-bottom:none}
.bar{display:inline-block;height:8px;background:var(--accent);border-radius:2px;
     vertical-align:middle}
.none{color:var(--dim);margin-top:14px}
.legend{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:12px;
        color:var(--dim);flex-wrap:wrap}
.legend .grad{height:10px;flex:1;min-width:180px;border-radius:3px}
@media (max-width:560px){.map,.ruler{grid-template-columns:44px 1fr}}
"""

JS = """
document.querySelectorAll('.img').forEach(function(el){
  var out=el.querySelector('.readout'), img=el.querySelector('img');
  var bins=+el.dataset.bins, rows=+el.dataset.rows;
  var f0=+el.dataset.f0, df=+el.dataset.df;
  var times=el.dataset.times.split(',');
  var raw=atob(el.dataset.levels);
  el.addEventListener('mousemove', function(e){
    var r=img.getBoundingClientRect();
    var x=Math.min(bins-1,Math.max(0,Math.floor((e.clientX-r.left)/r.width*bins)));
    var y=Math.min(rows-1,Math.max(0,Math.floor((e.clientY-r.top)/r.height*rows)));
    var dbm=raw.charCodeAt(y*bins+x)+(HOVER_BASE);
    out.textContent=(f0+x*df).toFixed(4)+' MHz  '+times[y]+'  '+dbm+' dBm';
    out.style.opacity=1;
  });
  el.addEventListener('mouseleave',function(){out.style.opacity=0;});
});
"""


def esc(text):
    return html.escape(str(text), quote=True)


def heat_map(frames, freqs, floor, args):
    """The whole recording as one image, with a time gutter and a frequency
    ruler. One row per frame, so one row per averaging window - a lost frame
    shortens the map rather than leaving a gap in it."""
    bins = len(freqs)
    rows = len(frames)
    img = b64(heat_png(frames, floor, bins))
    levels = bytes(max(0, min(255, v - HOVER_BASE))
                   for _, values in frames for v in values)
    times = ",".join(hhmmss(t) for t, _ in frames)

    tlabels = "".join(
        f'<span style="top:{(n + 0.5) / rows * 100:.4f}%">{hhmmss(t)}</span>'
        for n, t in hour_marks(frames))

    flabels = "".join(
        f'<span style="left:{(i + 0.5) / bins * 100:.4f}%">{freqs[i]:.3f}</span>'
        for i in (k * (bins - 1) // 4 for k in range(5)))

    # The map's natural aspect is one pixel per bin by one per frame. Scaling to
    # the page width stretches it ~6.6x horizontally, and letting the height
    # follow would make a long session absurdly tall - so set the aspect ratio
    # directly: yscale 1.0 is the natural shape, 0.5 half as tall. CSS does the
    # arithmetic, so it stays right at any page width.
    ratio = f"{bins} / {rows * args.yscale:.3f}"
    return (f'<div class="map"><div class="tcol">{tlabels}</div>'
            f'<div class="img" data-bins="{bins}" data-rows="{rows}" '
            f'data-f0="{freqs[0]:.6f}" '
            f'data-df="{(freqs[1] - freqs[0]) if bins > 1 else 0:.6f}" '
            f'data-times="{esc(times)}" data-levels="{b64(levels)}">'
            f'<img alt="heat map of the whole session" '
            f'style="aspect-ratio:{ratio}" '
            f'src="data:image/png;base64,{img}">'
            f'<div class="readout"></div></div></div>'
            f'<div class="ruler"><div></div><div>{flabels}</div></div>')


def render_html(path, freqs, frames, session, args):
    floor = session["floor"]
    grad = ",".join(f"rgb{ramp(d)} {min(100, d / STOPS[-1][0] * 100):.0f}%"
                    for d, _ in STOPS)
    span = frames[-1][0] - frames[0][0]

    body = [f'<div class="wrap"><h1>{esc(path)}</h1>',
            f'<p class="sub">{len(frames)} frames &middot; '
            f'{hhmmss(frames[0][0])} to {hhmmss(frames[-1][0])} '
            f'({span // 3600} h {span % 3600 // 60:02d} min) &middot; '
            f'{len(freqs)} bins &middot; {freqs[0]:.4f}&ndash;{freqs[-1]:.4f} MHz '
            f'&middot; rendered {datetime.now():%Y-%m-%d %H:%M}</p>']

    if session["clipping"]:
        body.append(f'<p class="warn">{esc(session["clipping"])}</p>')

    body.append(heat_map(frames, freqs, floor, args))
    body.append(f'<div class="legend"><span>noise floor {floor} dBm</span>'
                f'<div class="grad" style="background:linear-gradient(90deg,{grad})">'
                f'</div><span>+{STOPS[-1][0]} dB</span></div>')

    body.append('<h2>Summary</h2>')
    if not session["flares"]:
        body.append(f'<p class="none">Nothing rose {args.flare} dB above the '
                    f'{floor} dBm floor in the whole recording.</p>')
    else:
        body.append(
            f'<p class="sub">{len(session["flares"])} of {len(freqs)} bins rose at '
            f'least {args.flare} dB above the floor at some point. "Up" counts the '
            f'frames in which a bin was that far above it.</p>'
            '<div class="tscroll"><table><thead><tr><th>frequency</th><th>peak</th>'
            '<th>over floor</th><th>up</th><th>of session</th><th>first</th>'
            '<th>last</th><th></th></tr></thead><tbody>')
        for f in session["flares"]:
            pct = 100 * f["hits"] / f["frames"]
            body.append(
                f'<tr><td>{f["freq"]:.4f} MHz</td><td>{f["peak"]} dBm</td>'
                f'<td>+{f["over"]}</td><td>{f["hits"]}</td>'
                f'<td>{pct:.1f}%</td><td>{hhmmss(f["first"])}</td>'
                f'<td>{hhmmss(f["last"])}</td>'
                f'<td><span class="bar" style="width:{max(2, pct * 0.6):.0f}px">'
                f'</span></td></tr>')
        body.append('</tbody></table></div>')

    body.append('</div>')

    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(path)} – spectrum log</title><style>{CSS}</style></head>"
            f"<body>{''.join(body)}"
            f"<script>var HOVER_BASE={HOVER_BASE};{JS}</script></body></html>")


# -------------------------------------------------------------------- text ---

def shade(delta, colour):
    i = min(len(RAMP) - 1, max(0, delta // STEP))
    ch = RAMP[i]
    if colour and i:
        return f"\033[38;5;{COLOURS[i]}m{ch}\033[0m"
    return ch


def fold(values, width):
    """Fold bins down to `width` columns, keeping the strongest of each group."""
    n = len(values)
    if width >= n:
        return values
    return [max(values[i * n // width:(i + 1) * n // width]) for i in range(width)]


def fold_axis(freqs, width):
    """Fold the axis the same way, labelling each column with its LEFT edge."""
    n = len(freqs)
    if width >= n:
        return freqs
    return [freqs[i * n // width] for i in range(width)]


def render_text(freqs, frames, session, args):
    floor = session["floor"]
    legend = "  ".join(f"{RAMP[i]!r}={i * STEP}+" for i in range(1, len(RAMP)))
    print(f"shading, dB over the {floor} dBm noise floor: {legend}")
    if session["clipping"]:
        print(f"! {session['clipping']}")

    width = min(args.width, len(freqs))
    shown = fold_axis(freqs, width)
    ticks = [" "] * width
    labels = [" "] * width
    for c in range(0, width, 16):
        ticks[c] = "|"
        for k, ch in enumerate(f"{shown[c]:.3f}"):
            if c + k < width:
                labels[c + k] = ch
    print(" " * 9 + "".join(ticks))
    print(" " * 9 + "".join(labels))

    # One row per bucket across the whole session; a cell keeps the strongest
    # sample in it, so a single burst still shows after folding.
    buckets = max(1, min(args.rows or len(frames), len(frames)))
    for b in range(buckets):
        lo = b * len(frames) // buckets
        hi = max(lo + 1, (b + 1) * len(frames) // buckets)
        cells = [max(col) for col in zip(*(fold(v, width) for _, v in frames[lo:hi]))]
        line = "".join(shade(v - floor, args.color) for v in cells)
        print(f"{hhmmss(frames[lo][0]):>8} {line}")

    if not session["flares"]:
        print(f"\nnothing rose {args.flare} dB above the floor")
        return
    print(f"\nflares, at least {args.flare} dB over the floor:")
    print(f"  {'frequency':>13}  {'peak':>8}  {'over':>5}  {'up':>5}  "
          f"{'of ses':>6}  {'first':>8}  {'last':>8}")
    for f in session["flares"]:
        print(f"  {f['freq']:9.4f} MHz  {f['peak']:5d} dBm  {f['over']:+5d}  "
              f"{f['hits']:5d}  {100 * f['hits'] / f['frames']:5.1f}%  "
              f"{hhmmss(f['first'])}  {hhmmss(f['last'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="a CSV written by k5logdump.py")
    ap.add_argument("-o", "--out", help="HTML file to write (default: alongside the CSV)")
    ap.add_argument("--flare", type=int, default=10,
                    help="dB over the session's noise floor that counts as a flare")
    ap.add_argument("--text", action="store_true", help="print to the terminal instead")
    ap.add_argument("--yscale", type=float, default=0.5,
                    help="map height as a fraction of its natural aspect "
                         "(0.5 = half as tall as it is wide-per-pixel; 1.0 = square pixels)")
    ap.add_argument("--rows", type=int, default=40,
                    help="text: time rows for the whole session (0 = one per frame)")
    ap.add_argument("--width", type=int, default=128, help="text: max columns")
    ap.add_argument("--color", action="store_true", help="text: ANSI colour")
    args = ap.parse_args()

    freqs, frames = load(args.csv)
    session = analyse(frames, freqs, args.flare)
    span = frames[-1][0] - frames[0][0]
    print(f"{args.csv}: {len(frames)} frames, {len(freqs)} bins "
          f"{freqs[0]:.4f}-{freqs[-1]:.4f} MHz, "
          f"{hhmmss(frames[0][0])} to {hhmmss(frames[-1][0])} "
          f"({span // 3600}h {span % 3600 // 60:02d}m)")

    if args.text:
        render_text(freqs, frames, session, args)
        return 0

    out = args.out or (args.csv.rsplit(".", 1)[0] + ".html")
    doc = render_html(args.csv, freqs, frames, session, args)
    with open(out, "w") as f:
        f.write(doc)
    print(f"  wrote {out}  ({len(doc) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

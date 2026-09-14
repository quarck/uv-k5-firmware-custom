#!/usr/bin/env python3
"""
k5logview.py -- turn a k5logdump CSV into a self-contained HTML report.

One heat map per hour: time down, frequency across, coloured by how far each
bin stood above that hour's own noise floor rather than by absolute level -
the floor moves with the band, the antenna and the AGC, and what matters is
what rose out of it. Under each map is the list of bins that flared, at least
FLARE dB over that floor.

The maps are inline PNGs, one pixel per bin per frame, so a 15-hour session is
a handful of images rather than two hundred thousand table cells. Nothing is
fetched: the report is one file that works offline.

    python k5logview.py session.csv                 # -> session.html
    python k5logview.py session.csv -o report.html
    python k5logview.py session.csv --flare 15
    python k5logview.py session.csv --text          # the old terminal view
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
    """Group into hours and work out floor, flares and cells for each."""
    hours = {}
    for t, values in frames:
        hours.setdefault(t // 3600, []).append((t, values))

    out = []
    for hour in sorted(hours):
        block = hours[hour]
        flat = [v for _, values in block for v in values]
        floor, clipping = noise_floor(flat)

        flares = []
        for i, f in enumerate(freqs):
            column = [values[i] for _, values in block]
            peak = max(column)
            if peak - floor >= flare_db:
                hits = sum(1 for v in column if v - floor >= flare_db)
                flares.append({"freq": f, "peak": peak, "over": peak - floor,
                               "hits": hits, "frames": len(block)})
        flares.sort(key=lambda d: (-d["peak"], d["freq"]))

        out.append({"hour": hour, "frames": block, "floor": floor,
                    "clipping": clipping, "flares": flares})
    return out


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


def heat_png(block, floor, bins):
    lut = {}
    rows = []
    for _, values in block:
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
.img{position:relative}
.img img{display:block;width:100%;image-rendering:pixelated;
         image-rendering:crisp-edges;border-radius:3px}
.ruler{display:grid;grid-template-columns:58px 1fr;margin-top:2px}
.ruler div{position:relative;height:18px}
.ruler span{position:absolute;transform:translateX(-50%);font-size:11px;
            color:var(--dim);font-variant-numeric:tabular-nums;white-space:nowrap}
.readout{position:absolute;top:4px;right:6px;background:rgba(0,0,0,.72);
         color:#fff;font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
         padding:3px 6px;border-radius:4px;opacity:0;pointer-events:none;
         transition:opacity .1s;white-space:nowrap}
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


def hour_section(h, freqs, flare_db):
    block, floor = h["frames"], h["floor"]
    bins = len(freqs)
    rows = len(block)
    span = f"{hhmmss(h['hour'] * 3600)} – {hhmmss((h['hour'] + 1) * 3600)}"

    img = b64(heat_png(block, floor, bins))
    levels = bytes(max(0, min(255, v - HOVER_BASE))
                   for _, values in block for v in values)
    times = ",".join(hhmmss(t) for t, _ in block)

    # A few time labels down the side, and frequency labels under the map.
    tlabels = []
    for k in range(min(6, rows)):
        row = k * (rows - 1) // max(1, min(6, rows) - 1) if rows > 1 else 0
        pct = (row + 0.5) / rows * 100
        tlabels.append(f'<span style="top:{pct:.3f}%">{hhmmss(block[row][0])}</span>')

    flabels = []
    for k in range(5):
        i = k * (bins - 1) // 4
        pct = (i + 0.5) / bins * 100
        flabels.append(f'<span style="left:{pct:.3f}%">{freqs[i]:.3f}</span>')

    parts = [f'<section><h2>{span} <span class="meta">· {rows} frames '
             f'· noise floor {floor} dBm</span></h2>']
    if h["clipping"]:
        parts.append(f'<p class="warn">{esc(h["clipping"])}</p>')

    parts.append(
        f'<div class="map"><div class="tcol">{"".join(tlabels)}</div>'
        f'<div class="img" data-bins="{bins}" data-rows="{rows}" '
        f'data-f0="{freqs[0]:.6f}" data-df="{(freqs[1] - freqs[0]) if bins > 1 else 0:.6f}" '
        f'data-times="{esc(times)}" data-levels="{b64(levels)}">'
        f'<img alt="heat map, {span}" src="data:image/png;base64,{img}">'
        f'<div class="readout"></div></div></div>'
        f'<div class="ruler"><div></div><div>{"".join(flabels)}</div></div>')

    if not h["flares"]:
        parts.append(f'<p class="none">Nothing rose {flare_db} dB above the floor.</p>')
    else:
        parts.append(
            '<table><thead><tr><th>frequency</th><th>peak</th><th>over floor</th>'
            '<th>frames</th><th>of hour</th><th></th></tr></thead><tbody>')
        for f in h["flares"]:
            pct = 100 * f["hits"] / f["frames"]
            parts.append(
                f'<tr><td>{f["freq"]:.4f} MHz</td><td>{f["peak"]} dBm</td>'
                f'<td>+{f["over"]}</td><td>{f["hits"]} / {f["frames"]}</td>'
                f'<td>{pct:.0f}%</td>'
                f'<td><span class="bar" style="width:{max(2, pct * 0.6):.0f}px"></span></td></tr>')
        parts.append('</tbody></table>')

    parts.append('</section>')
    return "".join(parts)


def render_html(path, freqs, frames, hours, args):
    grad = ",".join(f"rgb{ramp(d)} {min(100, d / STOPS[-1][0] * 100):.0f}%"
                    for d, _ in STOPS)

    seen = {}
    for h in hours:
        for f in h["flares"]:
            was = seen.get(f["freq"], [0, 0, -999])
            seen[f["freq"]] = [was[0] + 1, was[1] + f["hits"], max(was[2], f["peak"])]

    body = [f'<div class="wrap"><h1>{esc(path)}</h1>',
            f'<p class="sub">{len(frames)} frames · {len(freqs)} bins · '
            f'{freqs[0]:.4f}–{freqs[-1]:.4f} MHz · '
            f'{hhmmss(frames[0][0])} to {hhmmss(frames[-1][0])} · '
            f'{len(hours)} hour(s) · flare threshold {args.flare} dB · '
            f'rendered {datetime.now():%Y-%m-%d %H:%M}</p>',
            f'<section><h2>Colour <span class="meta">· dB above that hour\'s '
            f'noise floor</span></h2><div class="legend"><span>floor</span>'
            f'<div class="grad" style="background:linear-gradient(90deg,{grad})"></div>'
            f'<span>+{STOPS[-1][0]} dB</span></div>']

    if seen:
        body.append('<table><thead><tr><th>frequency</th><th>hours seen</th>'
                    '<th>frames</th><th>peak</th></tr></thead><tbody>')
        for f, (nh, hits, peak) in sorted(seen.items(), key=lambda kv: -kv[1][1]):
            body.append(f'<tr><td>{f:.4f} MHz</td><td>{nh}</td><td>{hits}</td>'
                        f'<td>{peak} dBm</td></tr>')
        body.append('</tbody></table>')
    else:
        body.append(f'<p class="none">Nothing reached {args.flare} dB over the '
                    f'floor in any hour.</p>')
    body.append('</section>')

    for h in hours:
        body.append(hour_section(h, freqs, args.flare))
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


def render_text(freqs, hours, args):
    legend = "  ".join(f"{RAMP[i]!r}={i * STEP}+" for i in range(1, len(RAMP)))
    print(f"shading, dB over that hour's floor: {legend}")

    for h in hours:
        block, floor = h["frames"], h["floor"]
        span = f"{hhmmss(h['hour'] * 3600)}-{hhmmss((h['hour'] + 1) * 3600)}"
        print(f"\n=== {span}   {len(block)} frames, noise floor {floor} dBm ===")
        if h["clipping"]:
            print(f"{'':9}! {h['clipping']}")

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

        buckets = max(1, min(args.rows or len(block), len(block)))
        for b in range(buckets):
            lo = b * len(block) // buckets
            hi = max(lo + 1, (b + 1) * len(block) // buckets)
            cells = [max(col) for col in zip(*(fold(v, width) for _, v in block[lo:hi]))]
            line = "".join(shade(v - floor, args.color) for v in cells)
            print(f"{hhmmss(block[lo][0]):>8} {line}")

        if not h["flares"]:
            print(f"{'':9}nothing above the floor by {args.flare} dB")
            continue
        print(f"{'':9}flares, at least {args.flare} dB over floor:")
        for f in h["flares"]:
            print(f"{'':11}{f['freq']:9.4f} MHz  peak {f['peak']:5d} dBm "
                  f"(+{f['over']:2d})  {f['hits']:4d}/{f['frames']:<4d} frames  "
                  f"{100 * f['hits'] / f['frames']:3.0f}%")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="a CSV written by k5logdump.py")
    ap.add_argument("-o", "--out", help="HTML file to write (default: alongside the CSV)")
    ap.add_argument("--flare", type=int, default=10,
                    help="dB over the hour's noise floor that counts as a flare")
    ap.add_argument("--text", action="store_true", help="print to the terminal instead")
    ap.add_argument("--rows", type=int, default=12, help="text: time rows per hour")
    ap.add_argument("--width", type=int, default=128, help="text: max columns")
    ap.add_argument("--color", action="store_true", help="text: ANSI colour")
    args = ap.parse_args()

    freqs, frames = load(args.csv)
    hours = analyse(frames, freqs, args.flare)
    print(f"{args.csv}: {len(frames)} frames, {len(freqs)} bins "
          f"{freqs[0]:.4f}-{freqs[-1]:.4f} MHz, "
          f"{hhmmss(frames[0][0])} to {hhmmss(frames[-1][0])}, {len(hours)} hour(s)")

    if args.text:
        render_text(freqs, hours, args)
        return 0

    out = args.out or (args.csv.rsplit(".", 1)[0] + ".html")
    doc = render_html(args.csv, freqs, frames, hours, args)
    with open(out, "w") as f:
        f.write(doc)
    print(f"  wrote {out}  ({len(doc) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
k5logview.py -- turn a k5logdump CSV into a self-contained HTML report.

The band is cut into regions of at most REGION bins and each gets its own heat
map covering the whole session: frequency across, time down. One map of
everything does not work for a wide recording - 8192 bins against 30 hourly
frames is a strip a few pixels tall - and splitting by hour instead gives maps
with one row each.

Because a day of hourly frames is only ~24 rows, the maps are interpolated
rather than drawn as blocks: bilinear in time, so a channel that came and went
reads as a gradient instead of a staircase.

Below the maps is the text summary: the session's noise floor and every bin that
rose at least FLARE dB above it, with when it was first and last seen.

    python k5logview.py session.csv                 # -> session.html
    python k5logview.py session.csv -o report.html
    python k5logview.py session.csv --region 128    # narrower slices
    python k5logview.py session.csv --text          # terminal view
"""

import argparse
import base64
import csv
import html
import math
import struct
import sys
import zlib
from datetime import datetime
from statistics import median

REGION = 256          # bins per map, at most
MIN_ROWS = 120        # interpolate time up to at least this many pixel rows
MAX_ROWS = 720        # and never draw more than this

# Heat ramp, keyed by dB over the session floor. Dark and desaturated at the
# floor so noise recedes, warm where something stood up.
STOPS = ((0, (16, 20, 30)), (4, (26, 48, 92)), (8, (24, 106, 138)),
         (14, (32, 160, 112)), (20, (148, 194, 62)), (28, (246, 204, 60)),
         (38, (250, 124, 44)), (50, (255, 74, 74)))

# Terminal view only.
STEP = 5
RAMP = " .:+*#@"


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
    """The session's floor, and a note if the log clipped it.

    When the band is quieter than the lowest level the logger can store, most
    bins read that level and the median becomes the rail itself rather than a
    measurement - everything then looks 10 dB "over the floor". Where that
    happens, take the floor from the samples that did measure something."""
    rail = min(flat)
    clipped = flat.count(rail) / len(flat)
    if clipped < 0.25:
        return int(median(flat)), None

    above = [v for v in flat if v > rail]
    floor = int(median(above)) if above else rail
    return floor, (f"{clipped:.0%} of samples sit at {rail} dBm, the bottom of "
                   f"the log's range - the true floor is below it, so this "
                   f"floor is taken from the rest and flare sizes are lower "
                   f"bounds")


def analyse(frames, freqs, flare_db):
    """The floor, and every bin that rose flare_db above it."""
    flat = [v for _, values in frames for v in values]
    floor, clipping = noise_floor(flat)

    flares = []
    for i, f in enumerate(freqs):
        column = [values[i] for _, values in frames]
        peak = max(column)
        if peak - floor < flare_db:
            continue
        hits = [n for n, v in enumerate(column) if v - floor >= flare_db]
        flares.append({"bin": i, "freq": f, "peak": peak, "over": peak - floor,
                       "hits": len(hits), "frames": len(frames),
                       "first": frames[hits[0]][0], "last": frames[hits[-1]][0]})
    flares.sort(key=lambda d: d["bin"])      # up the band, not by strength
    return {"floor": floor, "clipping": clipping, "flares": flares}


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
    mostly smooth, which is what zlib is good at."""
    raw = b"".join(b"\x00" + row for row in rows_rgb)      # filter 0 per line

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def region_png(frames, lo, hi, floor, out_rows):
    """One region as a PNG: columns are bins lo..hi, rows are interpolated time.

    Bilinear in time only. Frequency is left at one pixel per bin - the bins are
    real measurements 25 kHz apart and smoothing across them would invent
    structure between channels, where smoothing in time only fills in between
    two readings of the same channel."""
    rows_in = len(frames)
    cols = hi - lo
    out = []

    for oy in range(out_rows):
        # sample position in input rows, pixel centres
        fy = (oy + 0.5) * rows_in / out_rows - 0.5
        y0 = int(math.floor(fy))
        w = fy - y0
        if y0 < 0:
            y0, w = 0, 0.0
        y1 = y0 + 1
        if y1 > rows_in - 1:
            y1, w = rows_in - 1, 0.0 if y0 > rows_in - 1 else w
        y0 = min(y0, rows_in - 1)

        a = frames[y0][1]
        b = frames[y1][1]
        row = bytearray()
        if w == 0.0:
            for i in range(lo, hi):
                row += bytes(ramp(a[i] - floor))
        else:
            for i in range(lo, hi):
                v = a[i] + (b[i] - a[i]) * w
                row += bytes(ramp(v - floor))
        out.append(bytes(row))

    return png(cols, out_rows, out)


def b64(data):
    return base64.b64encode(data).decode("ascii")


# -------------------------------------------------------------------- html ---

CSS = """
:root{--bg:#f5f6f7;--card:#fff;--fg:#14181d;--dim:#5e6670;--faint:#8b939c;
      --rule:#dcdfe3;--soft:#eceef1;--accent:#2f5d8c;
      --warn-bg:#fdf3dd;--warn-fg:#7a5600}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
      color-scheme:dark;
      --bg:#0f1317;--card:#161b21;--fg:#e6eaee;--dim:#98a2ac;--faint:#6d767f;
      --rule:#242b33;--soft:#1b2129;--accent:#79aada;
      --warn-bg:#33290f;--warn-fg:#f0cd7a}}
:root[data-theme="dark"]{color-scheme:dark;
      --bg:#0f1317;--card:#161b21;--fg:#e6eaee;--dim:#98a2ac;--faint:#6d767f;
      --rule:#242b33;--soft:#1b2129;--accent:#79aada;
      --warn-bg:#33290f;--warn-fg:#f0cd7a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 -apple-system,
     BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding-block:32px 64px;padding-left:16px;
      padding-right:16px}
h1{font-size:21px;font-weight:600;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--dim);margin:0 0 4px;font-variant-numeric:tabular-nums}
h2{font-size:12px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;
   color:var(--dim);margin:34px 0 0;padding-bottom:7px;
   border-bottom:1px solid var(--rule)}
.warn{background:var(--warn-bg);color:var(--warn-fg);border-radius:5px;
      padding:9px 11px;margin:14px 0 0;font-size:13px}
.legend{display:flex;align-items:center;gap:9px;margin:14px 0 0;font-size:12px;
        color:var(--dim);flex-wrap:wrap;font-variant-numeric:tabular-nums}
.legend .grad{height:9px;flex:1;min-width:160px;border-radius:2px}

.regions{display:grid;gap:18px;margin-top:16px}
.region{background:var(--card);border:1px solid var(--rule);border-radius:7px;
        padding:11px 13px 13px}
.rhead{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
       flex-wrap:wrap;margin-bottom:9px}
.rband{font-weight:600;font-variant-numeric:tabular-nums}
.rpeak{font-size:12px;color:var(--dim);font-variant-numeric:tabular-nums}
.rpeak b{color:var(--accent)}
.map{display:grid;grid-template-columns:56px 1fr}
.tcol{position:relative}
.tcol span{position:absolute;right:7px;transform:translateY(-50%);font-size:11px;
           color:var(--faint);font-variant-numeric:tabular-nums;white-space:nowrap}
.img{position:relative}
.img img{display:block;width:100%;max-width:100%;border-radius:3px;
         image-rendering:auto}
.ruler{display:grid;grid-template-columns:56px 1fr;margin-top:3px}
.ruler div{position:relative;height:17px}
.ruler span{position:absolute;transform:translateX(-50%);font-size:11px;
            color:var(--faint);font-variant-numeric:tabular-nums;white-space:nowrap}
.quiet{color:var(--faint);font-size:12px;margin:6px 0 0}
.readout{position:absolute;top:5px;right:6px;background:rgba(8,10,14,.84);
         color:#fff;font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;
         padding:3px 7px;border-radius:4px;opacity:0;pointer-events:none;
         transition:opacity .08s;white-space:nowrap;z-index:2;
         font-variant-numeric:tabular-nums}
.img:hover{cursor:crosshair}

.tscroll{overflow-x:auto;margin-top:14px;border:1px solid var(--rule);
         border-radius:6px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:580px;
      font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:5px 10px;border-bottom:1px solid var(--soft)}
th:first-child,td:first-child{text-align:left}
th{color:var(--faint);font-size:11px;letter-spacing:.07em;text-transform:uppercase;
   font-weight:600;background:var(--card);position:sticky;top:0;
   border-bottom:1px solid var(--rule)}
tr:last-child td{border-bottom:none}
.bar{display:inline-block;height:7px;background:var(--accent);border-radius:2px;
     vertical-align:middle}
.none{color:var(--dim);margin-top:14px}
@media (max-width:560px){.map,.ruler{grid-template-columns:42px 1fr}}
"""


HOVER_BASE = -185      # the byte the logger stores is dBm minus this

JS = """
document.querySelectorAll('.img').forEach(function(el){
  var out=el.querySelector('.readout'), img=el.querySelector('img');
  var lo=+el.dataset.lo, cols=+el.dataset.cols;
  function show(e){
    var r=img.getBoundingClientRect();
    if(!r.width||!r.height) return;
    var c=Math.floor((e.clientX-r.left)/r.width*cols);
    var y=Math.floor((e.clientY-r.top)/r.height*ROWS);
    c=c<0?0:(c>cols-1?cols-1:c);
    y=y<0?0:(y>ROWS-1?ROWS-1:y);
    var b=lo+c;
    out.textContent=(F0+b*DF).toFixed(4)+' MHz  '+T[y]+'  '
                    +(L.charCodeAt(y*BINS+b)+HB)+' dBm';
    out.style.opacity=1;
  }
  el.addEventListener('mousemove',show);
  el.addEventListener('touchmove',function(e){
    if(e.touches.length===1){show(e.touches[0]); e.preventDefault();}
  },{passive:false});
  el.addEventListener('mouseleave',function(){out.style.opacity=0;});
});
"""


def esc(t):
    return html.escape(str(t), quote=True)


def time_labels(frames, count=6):
    """Row positions, as percentages, for the time gutter."""
    n = len(frames)
    if n == 1:
        return [(50.0, hhmmss(frames[0][0]))]
    picks = sorted({k * (n - 1) // (count - 1) for k in range(count)})
    return [((i + 0.5) / n * 100, hhmmss(frames[i][0])) for i in picks]


def flare_table(flares, floor, args, where):
    """The bins that rose above the floor, up the band. Not capped: a long table
    is the honest answer when a lot of the band was busy."""
    if not flares:
        return (f'<p class="quiet">Nothing rose {args.flare} dB above the '
                f'{floor} dBm floor {where}.</p>')
    rows = []
    for f in flares:
        pct = 100 * f["hits"] / f["frames"]
        rows.append(
            f'<tr><td>{f["freq"]:.4f} MHz</td><td>{f["peak"]} dBm</td>'
            f'<td>+{f["over"]}</td><td>{f["hits"]}</td>'
            f'<td>{pct:.1f}%</td><td>{hhmmss(f["first"])}</td>'
            f'<td>{hhmmss(f["last"])}</td>'
            f'<td><span class="bar" style="width:{max(2, pct * 0.6):.0f}px">'
            f'</span></td></tr>')
    return ('<div class="tscroll"><table><thead><tr><th>frequency</th><th>peak</th>'
            '<th>over floor</th><th>up</th><th>of session</th><th>first</th>'
            '<th>last</th><th></th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table></div>')


def region_html(frames, freqs, lo, hi, floor, flares_by_bin, args):
    cols = hi - lo
    rows_in = len(frames)
    out_rows = max(MIN_ROWS, min(MAX_ROWS, rows_in if rows_in >= MIN_ROWS
                                 else rows_in * ((MIN_ROWS + rows_in - 1) // rows_in)))
    img = b64(region_png(frames, lo, hi, floor, out_rows))

    peak = max(max(v[lo:hi]) for _, v in frames)
    at = None
    for _, v in frames:
        for i in range(lo, hi):
            if v[i] == peak:
                at = freqs[i]
                break
        if at is not None:
            break
    hits = [f for f in flares_by_bin if lo <= f["bin"] < hi]

    tl = "".join(f'<span style="top:{pct:.3f}%">{lab}</span>'
                 for pct, lab in time_labels(frames))
    fl = "".join(
        f'<span style="left:{(i - lo + 0.5) / cols * 100:.3f}%">{freqs[i]:.3f}</span>'
        for i in (lo + k * (cols - 1) // 4 for k in range(5)))

    return (
        f'<div class="region"><div class="rhead">'
        f'<span class="rband">{freqs[lo]:.3f} &ndash; {freqs[hi - 1]:.3f} MHz</span>'
        f'<span class="rpeak">peak <b>{peak} dBm</b> at {at:.4f} &middot; '
        f'{len(hits)} bin{"" if len(hits) == 1 else "s"} over '
        f'+{args.flare}</span></div>'
        f'<div class="map"><div class="tcol">{tl}</div>'
        f'<div class="img" data-lo="{lo}" data-cols="{cols}">'
        f'<img alt="{freqs[lo]:.3f} to {freqs[hi - 1]:.3f} MHz" '
        f'src="data:image/png;base64,{img}">'
        f'<div class="readout"></div></div></div>'
        f'<div class="ruler"><div></div><div>{fl}</div></div>'
        + flare_table(hits, floor, args, "in this region")
        + '</div>')


def render_html(path, freqs, frames, session, args):
    floor = session["floor"]
    span = frames[-1][0] - frames[0][0]
    grad = ",".join(f"rgb{ramp(d)} {min(100, d / STOPS[-1][0] * 100):.0f}%"
                    for d, _ in STOPS)
    edges = [(lo, min(lo + args.region, len(freqs)))
             for lo in range(0, len(freqs), args.region)]

    body = [f'<div class="wrap"><h1>{esc(path)}</h1>',
            f'<p class="sub">{len(frames)} frames &middot; '
            f'{hhmmss(frames[0][0])} to {hhmmss(frames[-1][0])} '
            f'({span // 3600} h {span % 3600 // 60:02d} min) &middot; '
            f'{len(freqs)} bins &middot; {freqs[0]:.4f}&ndash;{freqs[-1]:.4f} MHz '
            f'&middot; noise floor {floor} dBm</p>',
            f'<p class="sub">{len(edges)} region'
            f'{"" if len(edges) == 1 else "s"} of up to {args.region} bins, each '
            f'covering the whole session &middot; rendered '
            f'{datetime.now():%Y-%m-%d %H:%M}</p>']

    if session["clipping"]:
        body.append(f'<p class="warn">{esc(session["clipping"])}</p>')

    body.append(f'<div class="legend"><span>floor</span>'
                f'<div class="grad" style="background:linear-gradient(90deg,{grad})">'
                f'</div><span>+{STOPS[-1][0]} dB over it</span></div>')

    flares = session["flares"]
    body.append(
        f'<h2>Band by band</h2>'
        f'<p class="sub">{len(flares)} of {len(freqs)} bins rose at least '
        f'{args.flare} dB above the {floor} dBm floor; each region lists its own '
        f'below its map, up the band.</p><div class="regions">')
    for lo, hi in edges:
        body.append(region_html(frames, freqs, lo, hi, floor,
                                session["flares"], args))
    body.append('</div>')

    body.append('</div>')

    # One blob for the whole grid rather than one per region: the regions do
    # not overlap, so it is the same bytes either way, and it keeps the lookup
    # a single index. Same byte the logger stores, dBm - HOVER_BASE.
    levels = bytes(max(0, min(255, v - HOVER_BASE))
                   for _, values in frames for v in values)
    df = (freqs[1] - freqs[0]) if len(freqs) > 1 else 0.0
    script = ('<script>var HB=' + str(HOVER_BASE)
              + ',BINS=' + str(len(freqs)) + ',ROWS=' + str(len(frames))
              + ',F0=' + f'{freqs[0]:.6f}' + ',DF=' + f'{df:.6f}'
              + ',T="' + ",".join(hhmmss(t) for t, _ in frames) + '".split(",")'
              + ',L=atob("' + b64(levels) + '");' + JS + '</script>')

    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(path)} – spectrum log</title><style>{CSS}</style>'
            f'</head><body>{"".join(body)}{script}</body></html>')


# -------------------------------------------------------------------- text ---

def render_text(freqs, frames, session, args):
    floor = session["floor"]
    print(f"shading, dB over the {floor} dBm floor: "
          + "  ".join(f"{RAMP[i]!r}={i * STEP}+" for i in range(1, len(RAMP))))
    if session["clipping"]:
        print(f"! {session['clipping']}")

    for lo in range(0, len(freqs), args.region):
        hi = min(lo + args.region, len(freqs))
        width = min(args.width, hi - lo)
        fold = (hi - lo + width - 1) // width
        print(f"\n=== {freqs[lo]:.3f} - {freqs[hi - 1]:.3f} MHz ===")
        buckets = max(1, min(args.rows or len(frames), len(frames)))
        for b in range(buckets):
            a = b * len(frames) // buckets
            z = max(a + 1, (b + 1) * len(frames) // buckets)
            cells = []
            for c in range(width):
                v = max(max(fr[1][lo + c * fold:min(hi, lo + (c + 1) * fold)])
                        for fr in frames[a:z])
                cells.append(v)
            line = "".join(RAMP[min(len(RAMP) - 1, max(0, (v - floor) // STEP))]
                           for v in cells)
            print(f"{hhmmss(frames[a][0]):>8} {line}")

        hits = [f for f in session["flares"] if lo <= f["bin"] < hi]
        if not hits:
            print(f"  nothing rose {args.flare} dB above the floor here")
            continue
        print(f"  {'frequency':>13}  {'peak':>8}  {'over':>5}  {'up':>5}  "
              f"{'first':>8}  {'last':>8}")
        for f in hits:
            print(f"  {f['freq']:9.4f} MHz  {f['peak']:5d} dBm  {f['over']:+5d}  "
                  f"{f['hits']:5d}  {hhmmss(f['first'])}  {hhmmss(f['last'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="a CSV written by k5logdump.py")
    ap.add_argument("-o", "--out", help="HTML file to write (default: beside the CSV)")
    ap.add_argument("--region", type=int, default=REGION,
                    help=f"bins per map (default {REGION})")
    ap.add_argument("--flare", type=int, default=10,
                    help="dB over the session's noise floor that counts as a flare "
                         "(default 10)")
    ap.add_argument("--text", action="store_true", help="print to the terminal instead")
    ap.add_argument("--rows", type=int, default=24, help="text: time rows per region")
    ap.add_argument("--width", type=int, default=128, help="text: max columns")
    args = ap.parse_args()
    if args.region < 1:
        sys.exit("--region must be at least 1")

    freqs, frames = load(args.csv)
    regions = (len(freqs) + args.region - 1) // args.region
    if regions > 64 and not args.text:
        print(f"  note: {len(freqs)} bins / {args.region} = {regions} maps. That "
              f"is a lot of images; --region {max(128, len(freqs) // 32)} would "
              f"give about 32.", file=sys.stderr)
    session = analyse(frames, freqs, args.flare)
    span = frames[-1][0] - frames[0][0]
    print(f"{args.csv}: {len(frames)} frames, {len(freqs)} bins "
          f"{freqs[0]:.4f}-{freqs[-1]:.4f} MHz, "
          f"{hhmmss(frames[0][0])} to {hhmmss(frames[-1][0])} "
          f"({span // 3600}h {span % 3600 // 60:02d}m), floor {session['floor']} dBm")

    if args.text:
        render_text(freqs, frames, session, args)
        return 0

    out = args.out or (args.csv.rsplit(".", 1)[0] + ".html")
    doc = render_html(args.csv, freqs, frames, session, args)
    with open(out, "w") as f:
        f.write(doc)
    print(f"  {(len(freqs) + args.region - 1) // args.region} region maps, "
          f"{len(session['flares'])} flares -> {out} ({len(doc) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""HTML and SVG helpers for the self-contained report pages (the verification report, the run reports).

Pages are one file each: inline CSS and SVG, light and dark themes (prefers-color-scheme, or data-theme on <html>),
no external files. CSS is the shared base sheet; h() escapes, fmt() / pct() / short() format numbers, ticks() picks
axis ticks, line_svg() draws the verification report's charts and series_svg() the run report's per-player charts,
with labels at the line ends that never overlap.
"""
from __future__ import annotations
from html import escape
import math

STATUS_TEXT = {'pass': 'pass', 'warn': 'warn', 'fail': 'fail', 'n/a': 'n/a', 'skipped': 'skipped', 'info': 'info',
               'incomplete': 'incomplete'}

CSS = '''
:root{--bg:#fbfbfa;--fg:#1d1f21;--muted:#62666b;--line:#d9dbde;--panel:#ffffff;--band:#9cc3e6;--median:#5b6670;
--ref:#d1495b;--ok:#2e7d32;--warn:#b26a00;--bad:#c62828;--na:#7a7f85;--info:#3a6ea5;--bar:#4f8fc9;--bar2:#8fb07a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#16181b;--fg:#e6e7e8;--muted:#9ba1a7;--line:#33373c;
--panel:#1d2024;--band:#2f5878;--median:#a2adb7;--ref:#ff7a8a;--ok:#66bb6a;--warn:#ffb74d;--bad:#ef5350;--na:#8d939a;
--info:#7fb0e0;--bar:#5b9bd5;--bar2:#9cc28a}}
:root[data-theme="dark"]{--bg:#16181b;--fg:#e6e7e8;--muted:#9ba1a7;--line:#33373c;--panel:#1d2024;--band:#2f5878;
--median:#a2adb7;--ref:#ff7a8a;--ok:#66bb6a;--warn:#ffb74d;--bad:#ef5350;--na:#8d939a;--info:#7fb0e0;--bar:#5b9bd5;--bar2:#9cc28a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 10px;padding-bottom:4px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:18px 0 8px}
.muted{color:var(--muted)}.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.verdict{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:14px 0;padding:14px 16px;background:var(--panel);
border:1px solid var(--line);border-radius:8px}
.big{font-size:16px}
.badge{display:inline-block;min-width:58px;text-align:center;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;
color:#fff;background:var(--na);text-transform:uppercase;letter-spacing:.03em}
.badge.pass{background:var(--ok)}.badge.warn{background:var(--warn)}.badge.fail,.badge.incomplete{background:var(--bad)}
.badge.info{background:var(--info)}
.verdict .badge{font-size:15px;padding:4px 14px}
table{border-collapse:collapse;width:100%;background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:hidden}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
details{margin-top:4px}summary{cursor:pointer;color:var(--muted);font-size:12px}
pre{white-space:pre-wrap;word-break:break-word;margin:6px 0;font-size:12px;max-height:340px;overflow:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
.chart .t{font-size:12px;display:flex;justify-content:space-between;gap:6px}
.chart svg{display:block;width:100%;height:auto}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:2px 14px;font-size:13px}
.legend span{display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:12px;color:var(--muted)}
.sw{display:inline-block;width:14px;height:8px;border-radius:2px}
.scroll{overflow-x:auto}
'''


def h(x):
    return escape('' if x is None else str(x))


def badge(status):
    s = status or 'n/a'
    return f'<span class="badge {h(s.replace("/", ""))}">{h(STATUS_TEXT.get(s, s))}</span>'


def fmt(v, digits=2):
    if v is None:
        return '-'
    if isinstance(v, float):
        return f'{v:,.{digits}f}'
    if isinstance(v, int):
        return f'{v:,}'
    return str(v)


def pct(v):
    return '-' if v is None else f'{v:.1%}'


def size(n):
    """Bytes as B, KB, MB or GB."""
    if n is None:
        return '-'
    for unit in ('B', 'KB', 'MB'):
        if n < 1024:
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.2f} GB'


# ---- SVG ----

def scale(lo, hi, a, b):
    span = (hi - lo) or 1.0
    return lambda v: a + (v - lo) * (b - a) / span


def path_d(points):
    return 'M' + 'L'.join(f'{x:.1f},{y:.1f}' for x, y in points) if points else ''


def short(v):
    a = abs(v)
    if a < 1e-9:
        return '0'
    if a >= 1e6:
        return f'{v / 1e6:.1f}M'
    if a >= 1e4:
        return f'{v / 1e3:.0f}k'
    if a >= 100:
        return f'{v:.0f}'
    if a >= 10:
        return f'{v:.1f}'
    return f'{v:.2f}'


def ticks(lo, hi, n=4, integer=False):
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    if integer:
        step = max(1, round(step))
    start = (lo // step + 1) * step if lo % step else lo
    out, v = [], start
    while v <= hi + 1e-9 and len(out) < 12:
        out.append(int(v) if integer else v)
        v += step
    return out


def line_svg(series_list, width=560, height=170, xlabel='', ylabel=''):
    """series_list: [(label, color, [(x, y)], dashed)]"""
    pts = [p for _, _, s, _ in series_list for p in s if p[1] is not None]
    if not pts:
        return ''
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = 0, max(p[1] for p in pts) * 1.08 or 1
    left, right, top, bottom = 44, width - 8, 8, height - 22
    X = scale(x0, x1 if x1 > x0 else x0 + 1, left, right)
    Y = scale(y0, y1, bottom, top)
    tk = ''.join(f'<text x="{left - 4}" y="{Y(v) + 3:.1f}" text-anchor="end" font-size="10" fill="var(--muted)">{short(v)}</text>'
                 f'<line x1="{left}" x2="{right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)" stroke-width="0.5"/>'
                 for v in ticks(y0, y1))
    xt = ''.join(f'<text x="{X(t):.1f}" y="{height - 6}" text-anchor="middle" font-size="10" fill="var(--muted)">{short(t)}</text>'
                 for t in ticks(x0, x1, 5))
    body = ''
    for label, color, s, dashed in series_list:
        pp = [(X(x), Y(y)) for x, y in s if y is not None]
        if len(pp) == 1:
            body += f'<circle cx="{pp[0][0]:.1f}" cy="{pp[0][1]:.1f}" r="3" fill="{color}"/>'
        body += (f'<path d="{path_d(pp)}" fill="none" stroke="{color}" stroke-width="1.6"'
                 + (' stroke-dasharray="4 3"' if dashed else '') + '/>')
        if len(pp) <= 40:
            body += ''.join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="{color}"/>' for x, y in pp)
    labels = (f'<text x="{right}" y="{height - 6}" text-anchor="end" font-size="10" fill="var(--muted)">{h(xlabel)}</text>' if xlabel else '')
    return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{h(ylabel)}">{tk}{xt}{body}{labels}</svg>'


def spread(wanted, gap, lo, hi):
    """Label positions near wanted (sorted or not), at least gap apart, inside [lo, hi] when they fit; returns them in
    the order given."""
    order = sorted(range(len(wanted)), key=lambda i: wanted[i])
    n = len(order)
    if not n:
        return []
    gap = min(gap, (hi - lo) / max(n - 1, 1)) if n > 1 else gap
    pos = [min(max(wanted[i], lo), hi) for i in order]
    for k in range(1, n):
        pos[k] = max(pos[k], pos[k - 1] + gap)
    if pos[-1] > hi:
        pos[-1] = hi
        for k in range(n - 2, -1, -1):
            pos[k] = min(pos[k], pos[k + 1] - gap)
    out = [0.0] * n
    for k, i in enumerate(order):
        out[i] = pos[k]
    return out


def series_svg(series, width=560, height=210, label_width=96, zero=True, title=''):
    """A line chart over turns of several series with each label at its line's end, in the line's colour, spread apart
    so labels never overlap (the chart reads without colours too). series: [(label, colour, [(x, y)], dashed)];
    colours may be CSS values such as var(--p3). zero: the y axis starts at 0 unless values go below it."""
    series = [(l, c, [(x, y) for x, y in s if y is not None], d) for l, c, s, d in series]
    series = [s for s in series if s[2]]
    pts = [p for _, _, s, _ in series for p in s]
    if not pts:
        return ''
    whole = all(float(p[1]).is_integer() for p in pts)  # counts: integer ticks and labels
    value = (lambda v: f'{v:,.0f}' if abs(v) < 1e4 else short(v)) if whole else short
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    if zero:
        y0 = min(y0, 0)
    if y1 <= y0:
        y1 = y0 + 1
    pad = (y1 - y0) * 0.06
    y1 += pad
    if y0 < 0 or not zero:
        y0 -= pad
    left, top, bottom = 44, 8, height - 22
    right = width - (label_width if label_width else 8)
    X = scale(x0, x1 if x1 > x0 else x0 + 1, left, right)
    Y = scale(y0, y1, bottom, top)
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{h(title)}">']
    for v in ticks(y0, y1, integer=whole):
        out.append(f'<line x1="{left}" x2="{right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)" stroke-width="0.5"/>'
                   f'<text x="{left - 4}" y="{Y(v) + 3:.1f}" text-anchor="end" font-size="10" fill="var(--muted)">{value(v)}</text>')
    for t in ticks(x0, x1, 5, integer=True) if x1 > x0 else [x0]:
        out.append(f'<text x="{X(t):.1f}" y="{height - 7}" text-anchor="middle" font-size="10" fill="var(--muted)">{h(t)}</text>')
    ends = []
    for label, colour, s, dashed in series:
        pp = [(X(x), Y(y)) for x, y in s]
        if len(pp) == 1:
            out.append(f'<circle cx="{pp[0][0]:.1f}" cy="{pp[0][1]:.1f}" r="2.5" fill="{colour}"/>')
        else:
            out.append(f'<path d="{path_d(pp)}" fill="none" stroke="{colour}" stroke-width="1.5" stroke-linejoin="round"'
                       + (' stroke-dasharray="4 3"' if dashed else '') + f'><title>{h(label)}</title></path>')
        ends.append((pp[-1], label, colour, s[-1][1]))
    if label_width and ends:
        ys = spread([e[0][1] for e in ends], 11, top + 4, bottom)
        for (pt, label, colour, last), y in zip(ends, ys):
            out.append(f'<path d="M{pt[0]:.1f},{pt[1]:.1f}L{right + 3:.1f},{y:.1f}" stroke="{colour}" stroke-width="0.6" fill="none" opacity="0.6"/>'
                       f'<text x="{right + 5:.1f}" y="{y + 3.5:.1f}" font-size="10" fill="{colour}">{h(label)} '
                       f'<tspan fill="var(--muted)">{value(last)}</tspan></text>')
    out.append('</svg>')
    return ''.join(out)

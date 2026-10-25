"""The suite's report as one self-contained HTML page: inline CSS and SVG, no scripts, no external files.

html(doc) renders verify.json's dict: the verdict and its headline, the checks by section, the trajectory
comparisons, the envelope charts per metric, the performance tables, the load timeline and the history trend.
"""
from __future__ import annotations
from html import escape
import json
import math

STATUS_TEXT = {'pass': 'pass', 'warn': 'warn', 'fail': 'fail', 'n/a': 'n/a', 'skipped': 'skipped', 'info': 'info',
               'incomplete': 'incomplete'}
SECTION_TITLES = {'setup': 'Exact setup', 'health': 'Health', 'trajectory': 'Trajectory', 'statistics': 'Statistical fidelity',
                  'performance': 'Performance'}

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


# ---- SVG ----

def _scale(lo, hi, a, b):
    span = (hi - lo) or 1.0
    return lambda v: a + (v - lo) * (b - a) / span


def _path(points):
    return 'M' + 'L'.join(f'{x:.1f},{y:.1f}' for x, y in points) if points else ''


def envelope_svg(c, width=300, height=150):
    turns = c['turns']
    if not turns:
        return ''
    vals = [v for k in ('lo', 'hi', 'reference', 'median') for v in c[k] if v is not None]
    y0, y1 = min(vals), max(vals)
    if y0 == y1:
        y0, y1 = y0 - 1, y1 + 1
    pad = (y1 - y0) * 0.06
    y0, y1 = y0 - pad, y1 + pad
    left, right, top, bottom = 38, width - 6, 6, height - 18
    X = _scale(turns[0], turns[-1], left, right)
    Y = _scale(y0, y1, bottom, top)
    band = [(X(t), Y(v)) for t, v in zip(turns, c['hi'])] + [(X(t), Y(v)) for t, v in reversed(list(zip(turns, c['lo'])))]
    med = [(X(t), Y(v)) for t, v in zip(turns, c['median'])]
    ref = [(X(t), Y(v)) for t, v in zip(turns, c['reference']) if v is not None]
    twin = [(X(t), Y(v)) for t, v in zip(turns, c.get('twin') or []) if v is not None]
    out_pts = [(X(t), Y(v)) for t, v, a, b in zip(turns, c['reference'], c['lo'], c['hi'])
               if v is not None and not (a - 1e-9 <= v <= b + 1e-9)]
    ticks = ''.join(f'<text x="{left - 4}" y="{Y(v) + 3:.1f}" text-anchor="end" font-size="9" fill="var(--muted)">{_short(v)}</text>'
                    f'<line x1="{left}" x2="{right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)" stroke-width="0.5"/>'
                    for v in _ticks(y0, y1))
    xt = ''.join(f'<text x="{X(t):.1f}" y="{height - 5}" text-anchor="middle" font-size="9" fill="var(--muted)">{t}</text>'
                 for t in _ticks(turns[0], turns[-1], 4, integer=True))
    dots = ''.join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.6" fill="var(--ref)"/>' for x, y in out_pts[:200])
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{h(c["label"])}">{ticks}{xt}'
            f'<path d="{_path(band)}Z" fill="var(--band)" opacity="0.55"/>'
            f'<path d="{_path(med)}" fill="none" stroke="var(--median)" stroke-width="1" stroke-dasharray="3 2"/>'
            + (f'<path d="{_path(twin)}" fill="none" stroke="var(--info)" stroke-width="1.2" stroke-dasharray="1 2"/>' if twin else '')
            + f'<path d="{_path(ref)}" fill="none" stroke="var(--ref)" stroke-width="1.4"/>{dots}</svg>')


def _short(v):
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


def _ticks(lo, hi, n=4, integer=False):
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
    X = _scale(x0, x1 if x1 > x0 else x0 + 1, left, right)
    Y = _scale(y0, y1, bottom, top)
    ticks = ''.join(f'<text x="{left - 4}" y="{Y(v) + 3:.1f}" text-anchor="end" font-size="10" fill="var(--muted)">{_short(v)}</text>'
                    f'<line x1="{left}" x2="{right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)" stroke-width="0.5"/>'
                    for v in _ticks(y0, y1))
    xt = ''.join(f'<text x="{X(t):.1f}" y="{height - 6}" text-anchor="middle" font-size="10" fill="var(--muted)">{_short(t)}</text>'
                 for t in _ticks(x0, x1, 5))
    body = ''
    for label, color, s, dashed in series_list:
        pp = [(X(x), Y(y)) for x, y in s if y is not None]
        if len(pp) == 1:
            body += f'<circle cx="{pp[0][0]:.1f}" cy="{pp[0][1]:.1f}" r="3" fill="{color}"/>'
        body += (f'<path d="{_path(pp)}" fill="none" stroke="{color}" stroke-width="1.6"'
                 + (' stroke-dasharray="4 3"' if dashed else '') + '/>')
        if len(pp) <= 40:
            body += ''.join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="{color}"/>' for x, y in pp)
    labels = (f'<text x="{right}" y="{height - 6}" text-anchor="end" font-size="10" fill="var(--muted)">{h(xlabel)}</text>' if xlabel else '')
    return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{h(ylabel)}">{ticks}{xt}{body}{labels}</svg>'


def trajectory_svg(rows, width=760):
    """One strip per comparison: matched turns, transients, the lasting difference."""
    if not rows:
        return ''
    horizon = max((r['compared'] or 0) + (r.get('firstTurn') or 0) for _, r in rows) or 1
    rh, left = 22, 150
    height = rh * len(rows) + 22
    X = _scale(0, horizon, left, width - 8)
    out = []
    for k, (name, r) in enumerate(rows):
        y = 6 + k * rh
        out.append(f'<text x="{left - 6}" y="{y + 12}" text-anchor="end" font-size="11" fill="var(--fg)">{h(name)}</text>')
        first = r.get('firstTurn') or 0
        end = first + (r['compared'] or 0)
        div = (r.get('divergence') or {}).get('turn')
        ok_end = div if div is not None else end
        out.append(f'<rect x="{X(first):.1f}" y="{y}" width="{max(X(ok_end) - X(first), 0):.1f}" height="14" fill="var(--ok)" opacity="0.75"/>')
        if div is not None:
            out.append(f'<rect x="{X(div):.1f}" y="{y}" width="{max(X(end) - X(div), 1):.1f}" height="14" fill="var(--bad)" opacity="0.75"/>')
        for t in r.get('transients') or []:
            out.append(f'<rect x="{X(t["turn"]):.1f}" y="{y - 2}" width="{max(X(t["until"]) - X(t["turn"]), 2):.1f}" height="18" fill="var(--warn)"/>')
    for t in _ticks(0, horizon, 6, integer=True):
        out.append(f'<text x="{X(t):.1f}" y="{height - 4}" text-anchor="middle" font-size="10" fill="var(--muted)">{t}</text>')
    return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="trajectory comparisons">{"".join(out)}</svg>'


# ---- page ----

def _details(d):
    items = {k: v for k, v in (d or {}).items() if v not in (None, [], {}, '')}
    if not items:
        return ''
    return f'<details><summary>details</summary><pre class="mono">{h(json.dumps(items, indent=1, default=str)[:20000])}</pre></details>'


def html(doc):
    v = doc.get('verdict')
    inputs = doc.get('inputs') or {}
    machine = doc.get('machine') or {}
    parts = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<title>c5h verify report</title><style>{CSS}</style></head><body><main>']
    parts.append(f'<h1>c5h verify: {h(doc.get("mode"))}</h1><div class="muted">{h(doc.get("utc"))} &middot; {h(doc.get("run"))}</div>')
    secs = doc.get('seconds')
    parts.append(f'<div class="verdict">{badge(v)}<div><div class="big">{h(doc.get("headline"))}</div>'
                 f'<div class="muted">exit code {h(doc.get("exitCode"))} &middot; {fmt((secs or 0) / 60, 1)} of {fmt(doc.get("budgetSeconds", 0) / 60, 0)} minutes'
                 + (f' &middot; missing: {h(", ".join(doc["essentialMissing"]))}' if doc.get('essentialMissing') else '') + '</div></div></div>')
    dll, exe = inputs.get('dll') or {}, inputs.get('exe') or {}
    mods = ', '.join(m.get('name') or m.get('id') for m in inputs.get('mods') or []) or 'none'
    parts.append('<div class="kv">'
                 f'<div class="muted">DLL</div><div class="mono">{h(dll.get("path"))} ({h((dll.get("sha256") or "")[:8])})</div>'
                 f'<div class="muted">Mods</div><div>{h(mods)}</div>'
                 f'<div class="muted">Game</div><div>{h(inputs.get("setup"))}</div>'
                 f'<div class="muted">Host</div><div class="mono">{h(exe.get("path"))} ({h((exe.get("sha256") or "")[:8])})</div>'
                 f'<div class="muted">Machine</div><div>{h(machine.get("cpu"))}, {h(machine.get("logicalCPUs"))} logical CPUs</div></div>')
    for note in doc.get('notes') or []:
        parts.append(f'<p class="muted">Note: {h(note)}</p>')
    # Checks
    parts.append('<h2>Checks</h2>')
    by = {}
    for c in doc.get('checks') or []:
        by.setdefault(c['section'], []).append(c)
    for section in ('setup', 'health', 'trajectory', 'statistics', 'performance'):
        cs = by.get(section)
        if not cs:
            continue
        parts.append(f'<h3>{h(SECTION_TITLES[section])}</h3><table><tbody>')
        for c in cs:
            parts.append(f'<tr><td style="width:96px">{badge(c["status"])}</td><td style="width:32%"><b>{h(c["title"])}</b>'
                         f'<div class="muted mono">{h(c["id"])}</div></td><td>{h(c["summary"])}{_details(c.get("details"))}</td></tr>')
        parts.append('</tbody></table>')
    # Trajectory
    comps = doc.get('comparisons') or {}
    names = {'real': 'real / host', 'real-aa': 'real A/A', 'aa': 'host A/A', 'skew': 'frame skew', 'perturb': 'heap perturbation',
             'noprobe': 'probe off', 'standard': 'real / host Standard'}
    rows = [(names[k], comps[k]) for k in names if comps.get(k)]
    if rows:
        parts.append('<h2>Trajectory</h2><div class="legend"><span><i class="sw" style="background:var(--ok)"></i>identical</span>'
                     '<span><i class="sw" style="background:var(--warn)"></i>transient (heals within '
                     f'{h(rows[0][1].get("healTurns"))} turns)</span><span><i class="sw" style="background:var(--bad)"></i>lasting difference</span></div>')
        parts.append(f'<div class="scroll">{trajectory_svg(rows)}</div><table><thead><tr><th>comparison</th><th>method</th>'
                     '<th class="num">matched</th><th class="num">compared</th><th>lasting difference</th><th>transients</th><th>UI-only</th></tr></thead><tbody>')
        for name, r in rows:
            d = r.get('divergence')
            lasting = 'turn %s: %s' % (d['turn'], ', '.join(d['sections'][:8])) if d else 'none'
            transients = ', '.join('T%s-%s' % (t['turn'], t['until']) for t in r.get('transients') or []) or 'none'
            ui = ', '.join('T%s' % u['turn'] for u in (r.get('uiOnly') or [])[:10]) or 'none'
            parts.append(f'<tr><td>{h(name)}</td><td>{h(r.get("method"))}</td><td class="num">{fmt(r.get("matchedTurns"))}</td>'
                         f'<td class="num">{fmt(r.get("compared"))}</td><td>{h(lasting)}</td><td>{h(transients)}</td><td>{h(ui)}</td></tr>')
        parts.append('</tbody></table>')
    # Statistics
    st = doc.get('statistics') or {}
    charts = st.get('charts') or []
    if charts:
        env, b = st.get('envelope') or {}, st.get('bias') or {}
        parts.append('<h2>Statistical fidelity</h2>')
        vary = (st.get('vary') or {}).get('vary')
        what = 'other map seeds (other maps of the same script and size)' if vary == 'map' else 'the same map seed and other sync seeds'
        parts.append(f'<p>Reference: {h(st.get("reference"))}; ensemble: {h(st.get("members"))} host games with {h(what)}. '
                     f'Envelope: {pct(env.get("coverage"))} of {fmt(env.get("points"))} points inside the '
                     f'{pct((env.get("band") or [None])[0])}-{pct((env.get("band") or [None, None])[1])} band; threshold {pct(env.get("threshold"))} '
                     f'(ensemble games get {pct(env.get("expected"))} on average). Bias: {len(b.get("flagged") or [])} series flagged '
                     f'(max-T threshold {fmt(b.get("threshold"))}).</p>')
        parts.append('<div class="legend"><span><i class="sw" style="background:var(--band)"></i>ensemble band</span>'
                     '<span><i class="sw" style="background:var(--median)"></i>ensemble median</span>'
                     '<span><i class="sw" style="background:var(--ref)"></i>reference (dots: outside the band)</span>'
                     + ('<span><i class="sw" style="background:var(--info)"></i>host game with the same seeds</span>'
                        if st.get('twinCoverage') is not None else '') + '</div>')
        flagged = set(b.get('flagged') or [])
        ordered = sorted(charts, key=lambda c: (c['series'] not in flagged, c['coverage'] if c['coverage'] is not None else 2, c['series']))
        parts.append('<div class="grid">')
        for c in ordered:
            bias = c.get('bias') or {}
            flag = ' <span class="badge warn">bias</span>' if c['series'] in flagged else ''
            side = f" &middot; {bias.get('side')} median {bias.get('signFraction', 0):.0%}" if bias else ''
            parts.append(f'<div class="chart"><div class="t"><b>{h(c["label"])}</b><span class="muted">{pct(c["coverage"])}{side}{flag}</span></div>'
                         f'{envelope_svg(c)}</div>')
        parts.append('</div>')
    stt = doc.get('selfTest')
    if stt and stt.get('summary'):
        sm = stt['summary']
        parts.append('<h3>Statistics self-test</h3>'
                     f'<p>{sm["holdouts"]} held-out ensemble games: envelope pass {sm["envelopePass"]}, warn {sm["envelopeWarn"]}, '
                     f'fail {sm["envelopeFail"]}; bias quiet {sm["biasQuiet"]}. Shifting one metric by {stt["shift"]:.0%}: the bias check '
                     f'flags {sm["shiftDetected"]} of {sm["metrics"]} metrics. Foreign games caught: {sm["foreignCaught"]} of {sm["foreign"]}.</p>')
        parts.append('<table><thead><tr><th>metric</th><th class="num">bias flags</th><th class="num">envelope objects</th>'
                     '<th class="num">detectable shift</th></tr></thead><tbody>')
        for m, r in sorted(stt['shifts'].items(), key=lambda x: (x[1]['medianDetectableShift'] or 9)):
            parts.append(f'<tr><td>{h(r["label"])}</td><td class="num">{r["biasFlagged"]}/{r["tries"]}</td>'
                         f'<td class="num">{r["envelopeObjects"]}/{r["tries"]}</td><td class="num">{pct(r["medianDetectableShift"])}</td></tr>')
        parts.append('</tbody></table>')
    # Performance
    perf = doc.get('performance') or {}
    speed = next((c for c in doc.get('checks') or [] if c['id'] == 'performance.speed'), None)
    parts.append('<h2>Performance</h2>')
    if speed and speed['details'].get('rows'):
        parts.append('<table><thead><tr><th></th><th class="num">real game</th><th class="num">host</th><th class="num">real / host</th></tr></thead><tbody>')
        for r in speed['details']['rows']:
            parts.append(f'<tr><td>{h(r["what"])}</td><td class="num">{fmt(r["real"])}</td><td class="num">{fmt(r["host"])}</td>'
                         f'<td class="num">{fmt(r["ratio"])}</td></tr>')
        parts.append('</tbody></table>')
        real = perf.get('real') or {}
        if real.get('load'):
            parts.append('<p class="muted">Machine load during the real game (mean busy cores of '
                         f'{h(machine.get("logicalCPUs"))}; the real game\'s own; host games running): '
                         + '; '.join(f"{k}: {fmt((l or {}).get('busyCores'), 1)}, {fmt((l or {}).get('gameBusyCores'), 1)}, {fmt((l or {}).get('hosts'), 1)}"
                                     for k, l in real['load'].items()) + '</p>')
        host = perf.get('host') or {}
        curves = []
        if host.get('curve'):
            curves.append(('host', 'var(--bar)', [(t, s) for t, s in host['curve']], False))
        if real.get('curve'):
            curves.append(('real game', 'var(--ref)', [(t, s) for t, s in real['curve']], False))
        if curves:
            parts.append('<h3>Autoplay seconds by turn (cumulative)</h3><div class="legend">' +
                         ''.join(f'<span><i class="sw" style="background:{c}"></i>{h(n)}</span>' for n, c, _, _ in curves) +
                         f'</div><div class="chart">{line_svg(curves, xlabel="turn")}</div>')
    tp = perf.get('throughput') or []
    if tp:
        parts.append('<h3>Host throughput</h3><table><thead><tr><th>phase</th><th class="num">workers</th><th class="num">games</th>'
                     '<th class="num">turns/game</th><th class="num">seconds</th><th class="num">games/hour</th><th class="num">turns/hour</th>'
                     '<th class="num">busy cores</th><th class="num">real game cores</th></tr></thead><tbody>')
        for r in tp:
            load = r.get('load') or {}
            parts.append(f'<tr><td>{h(r["phase"])}</td><td class="num">{r["workers"]}</td><td class="num">{r["games"]}</td>'
                         f'<td class="num">{r["turnsPerGame"]}</td><td class="num">{fmt(r["seconds"], 0)}</td><td class="num">{fmt(r["gamesPerHour"], 1)}</td>'
                         f'<td class="num">{fmt(r["turnsPerHour"])}</td><td class="num">{fmt(load.get("busyCores"), 1)}</td>'
                         f'<td class="num">{fmt(load.get("gameBusyCores"), 1)}</td></tr>')
        parts.append('</tbody></table>')
    samples = perf.get('loadSamples') or []
    if samples:
        parts.append('<h3>Machine load over the run</h3><div class="legend"><span><i class="sw" style="background:var(--bar)"></i>busy cores</span>'
                     '<span><i class="sw" style="background:var(--ref)"></i>real game cores</span><span><i class="sw" style="background:var(--bar2)"></i>host games running</span></div>')
        parts.append('<div class="chart">' + line_svg([
            ('busy', 'var(--bar)', [(s['t'], s['busyCores']) for s in samples], False),
            ('game', 'var(--ref)', [(s['t'], s['gameBusyCores']) for s in samples], False),
            ('hosts', 'var(--bar2)', [(s['t'], s['hosts']) for s in samples], True)], xlabel='seconds') + '</div>')
    hist = doc.get('history') or []
    if len(hist) > 1:
        hs = [(k, ((e.get('host') or {}).get('perTurn') or {}).get('all')) for k, e in enumerate(hist)]
        rs = [(k, ((e.get('real') or {}).get('perTurn') or {}).get('all')) for k, e in enumerate(hist)]
        curves = [('host', 'var(--bar)', [p for p in hs if p[1] is not None], False)]
        if any(p[1] is not None for p in rs):
            curves.append(('real', 'var(--ref)', [p for p in rs if p[1] is not None], False))
        parts.append('<h3>History on this machine (same game setup): seconds per turn by run</h3><div class="legend">'
                     '<span><i class="sw" style="background:var(--bar)"></i>host</span><span><i class="sw" style="background:var(--ref)"></i>real game</span></div>'
                     f'<div class="chart">{line_svg(curves, xlabel="run")}</div>')
        parts.append('<table><thead><tr><th>run</th><th>date</th><th>mode</th><th>DLL</th><th>mods</th><th>host</th>'
                     '<th class="num">host s/turn</th><th class="num">real s/turn</th><th>verdict</th></tr></thead><tbody>')
        prev = None
        for k, e in enumerate(hist):
            changed = lambda key: ' style="font-weight:600"' if prev and prev.get(key) != e.get(key) else ''
            parts.append(f'<tr><td class="num">{k}</td><td>{h((e.get("utc") or "")[:16])}</td><td>{h(e.get("mode"))}</td>'
                         f'<td class="mono"{changed("dllSHA256")}>{h((e.get("dllSHA256") or "")[:8])}</td>'
                         f'<td class="mono"{changed("modsKey")}>{h((e.get("modsKey") or "")[:8])}</td>'
                         f'<td class="mono"{changed("exeSHA256")}>{h((e.get("exeSHA256") or "")[:8])}</td>'
                         f'<td class="num">{fmt(hs[k][1], 3)}</td><td class="num">{fmt(rs[k][1], 3)}</td><td>{badge(e.get("verdict")) if e.get("verdict") else "this run"}</td></tr>')
            prev = e
        parts.append('</tbody></table>')
    # Runs
    parts.append('<h2>Runs</h2><table><thead><tr><th>phase</th><th class="num">workers</th><th class="num">games</th>'
                 '<th class="num">seconds</th></tr></thead><tbody>')
    for p in doc.get('phases') or []:
        parts.append(f'<tr><td>{h(p["name"])}</td><td class="num">{p["workers"]}</td><td class="num">{p.get("completed")}/{len(p.get("jobs") or [])}</td>'
                     f'<td class="num">{fmt(p.get("seconds"), 0)}</td></tr>')
    parts.append('</tbody></table><details><summary>every host game</summary><table><thead><tr><th>game</th><th>kind</th><th>state</th>'
                 '<th class="num">turns</th><th class="num">seconds</th><th class="num">estimate</th><th>error</th></tr></thead><tbody>')
    for j in doc.get('jobs') or []:
        secs = (j['finished'] - j['started']) if j.get('finished') is not None and j.get('started') is not None else None
        parts.append(f'<tr><td class="mono">{h(j["name"])}</td><td>{h(j.get("kind"))}</td><td>{h(j.get("state"))}</td>'
                     f'<td class="num">{fmt(j.get("endTurn"))}</td><td class="num">{fmt(secs, 0)}</td><td class="num">{fmt(j.get("estimate"), 0)}</td>'
                     f'<td>{h(j.get("error"))}</td></tr>')
    parts.append('</tbody></table></details>')
    real = doc.get('real')
    if real:
        parts.append('<h3>Real game session</h3><table><thead><tr><th>game</th><th>state</th><th class="num">turns</th>'
                     '<th class="num">start s</th><th class="num">autoplay s</th><th>error</th></tr></thead><tbody>')
        for g in real.get('games') or []:
            parts.append(f'<tr><td>{h(g.get("name"))}</td><td>{h(g.get("state"))}</td><td class="num">{fmt(g.get("endTurn"))}</td>'
                         f'<td class="num">{fmt((g.get("start") or {}).get("seconds"), 1)}</td><td class="num">{fmt(g.get("autoplaySeconds"), 1)}</td>'
                         f'<td>{h(g.get("error"))}</td></tr>')
        parts.append('</tbody></table>')
        for e in real.get('errors') or []:
            parts.append(f'<p class="muted">Real game: {h(e)}</p>')
    caps = doc.get('capabilities') or {}
    parts.append('<h2>Capabilities</h2><div class="kv">'
                 f'<div class="muted">host --lua-probe</div><div>{h("yes" if caps.get("luaProbe") else "no")}</div>'
                 f'<div class="muted">Lua fingerprint</div><div>{h("yes" if caps.get("fingerprint") else "no")}</div>'
                 f'<div class="muted">real-game session</div><div>{h("yes" if caps.get("realGameSession") else "no")}</div>'
                 f'<div class="muted">UI hazard scan</div><div>{h("yes" if caps.get("hazards") else "no")}</div></div>')
    for k, why in (caps.get('notes') or {}).items():
        parts.append(f'<div class="muted">{h(k)}: {h(why)}</div>')
    parts.append('<p class="muted">docs/verification.md explains each check and what it can and cannot tell.</p></main></body></html>')
    return ''.join(parts)

"""Self-test of the statistical tier on a host ensemble: c5h verify --analyse DIR --self-test [--foreign RUN]...

- Held-out games (null): each of the first N ensemble games in turn is the reference, the others the ensemble. The
  envelope test should pass and the bias check stay quiet about as often as their alpha says.
- Shifted metrics (negative control): a held-out game with one metric (all its aggregates) multiplied by 1 + shift
  and 1 - shift. Reports, per metric, how often the bias check flags it and the envelope test fails or warns.
- Foreign games (negative control): games from another setup (another map, size or DLL), scored against the whole
  ensemble; both checks should object.
"""
from __future__ import annotations

from . import series, stats


def _metric(name):
    parts = name.split(':')
    return ':'.join(parts[:2]) if len(parts) == 3 else name


def run(ensemble, settings, holdouts=12, shift_holdouts=4, shift=0.05, foreign=(), log=print):
    """ensemble: [series dicts]; foreign: [(name, series dict)]. Returns a dict for verify.json and prints a summary."""
    s = settings
    lo, hi = s.envelope_band
    n = len(ensemble)
    out = dict(members=n, shift=shift, holdouts=[], shifts={}, foreign=[])
    if n < max(s.min_members, 4) + 1:
        out['error'] = f'{n} ensemble games; the self-test needs at least {max(s.min_members, 4) + 1}'
        log(f"self-test: {out['error']}")
        return out
    metrics = sorted({_metric(name) for g in ensemble for name in g})
    for i in range(min(holdouts, n)):
        ref, rest = ensemble[i], ensemble[:i] + ensemble[i + 1:]
        em = stats.envelope_model(rest, lo, hi, s.min_members, s.stats_from_turn, s.turns)
        bm = stats.bias_model(rest, s.bias_alpha, s.bias_z_cap, s.min_members, s.stats_from_turn, s.turns)
        e = stats.envelope_score(em, ref, s.envelope_target, s.envelope_alpha, s.envelope_margin)
        b = stats.bias_score(bm, ref, s.bias_one_sided)
        out['holdouts'].append(dict(member=i, envelope=e['status'], coverage=e.get('coverage'), threshold=e.get('threshold'),
                                    bias=b['status'], flagged=b.get('flagged', [])))
        if i < shift_holdouts:
            for m in metrics:
                names = [x for x in ref if _metric(x) == m]
                row = out['shifts'].setdefault(m, dict(label=series.label(names[0]).rsplit(' (', 1)[0] if names else m,
                                                       tries=0, biasFlagged=0, envelopeObjects=0, detectableShift=[]))
                for factor in (1 + shift, 1 - shift):
                    sh = stats.shifted(ref, factor, set(names))
                    e2 = stats.envelope_score(em, sh, s.envelope_target, s.envelope_alpha, s.envelope_margin)
                    b2 = stats.bias_score(bm, sh, s.bias_one_sided)
                    row['tries'] += 1
                    row['biasFlagged'] += any(f in names for f in b2.get('flagged', []))
                    row['envelopeObjects'] += e2['status'] in ('warn', 'fail')
                row['detectableShift'] += [b['series'][x]['detectableShift'] for x in names
                                           if x in b.get('series', {}) and b['series'][x]['detectableShift'] is not None]
    for row in out['shifts'].values():
        d = sorted(row.pop('detectableShift'))
        row['medianDetectableShift'] = d[len(d) // 2] if d else None
    if foreign:
        em = stats.envelope_model(ensemble, lo, hi, s.min_members, s.stats_from_turn, s.turns)
        bm = stats.bias_model(ensemble, s.bias_alpha, s.bias_z_cap, s.min_members, s.stats_from_turn, s.turns)
        for name, g in foreign:
            e = stats.envelope_score(em, g, s.envelope_target, s.envelope_alpha, s.envelope_margin)
            b = stats.bias_score(bm, g, s.bias_one_sided)
            out['foreign'].append(dict(name=name, envelope=e['status'], coverage=e.get('coverage'), bias=b['status'],
                                       flagged=b.get('flagged', [])[:10]))
    h = out['holdouts']
    out['summary'] = dict(
        holdouts=len(h), envelopePass=sum(x['envelope'] == 'pass' for x in h), envelopeWarn=sum(x['envelope'] == 'warn' for x in h),
        envelopeFail=sum(x['envelope'] == 'fail' for x in h), biasQuiet=sum(x['bias'] == 'pass' for x in h),
        meanCoverage=stats.mean(x['coverage'] for x in h if x['coverage'] is not None),
        shiftDetected=sum(1 for r in out['shifts'].values() if r['biasFlagged']), metrics=len(out['shifts']),
        foreignCaught=sum(1 for f in out['foreign'] if f['envelope'] in ('warn', 'fail') or f['bias'] == 'warn'),
        foreign=len(out['foreign']))
    sm = out['summary']
    log(f"self-test, {n} ensemble games: held out {sm['holdouts']}: envelope pass {sm['envelopePass']}, warn {sm['envelopeWarn']}, "
        f"fail {sm['envelopeFail']} (mean coverage {sm['meanCoverage']:.1%}); bias quiet {sm['biasQuiet']}")
    log(f"  shift {shift:+.0%}/{-shift:+.0%} of one metric: bias flags it for {sm['shiftDetected']} of {sm['metrics']} metrics")
    for m, r in sorted(out['shifts'].items(), key=lambda x: (x[1]['medianDetectableShift'] or 9)):
        d = r['medianDetectableShift']
        log(f"    {r['label']:<32} flagged {r['biasFlagged']}/{r['tries']}, envelope objects {r['envelopeObjects']}/{r['tries']}, "
            f"detectable shift {d:.0%}" if d is not None else f"    {r['label']:<32} flagged {r['biasFlagged']}/{r['tries']}")
    for f in out['foreign']:
        log(f"  foreign {f['name']}: envelope {f['envelope']} ({(f['coverage'] or 0):.1%}), bias {f['bias']} {f['flagged'][:4]}")
    return out

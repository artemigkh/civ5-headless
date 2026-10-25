"""Statistics of the fidelity tier (plan 5.3): the envelope test and the bias check, calibrated on the ensemble itself.

A game's metrics are series: {series name: {turn: value}}. The ensemble is a list of such games played with the same
setup and different sync seeds; the reference is the game under test (the real game, or a held-out host game).

Envelope test. Per (series, turn) the ensemble gives a band, the lo-hi quantiles (default 2.5-97.5%); coverage is
the fraction of the reference's points inside its band. A finite ensemble's band holds fewer than 95% of a new
game's points (with 32 games, about 90%), and ties and persistence change that again, so the expected coverage is
measured, not assumed: each member in turn is left out and scored against the band of the others (leave-one-out).
The reference passes when its coverage reaches the target (about 95%) or the low alpha quantile of the members'
leave-one-out coverages, whichever is lower.

Bias check. Per series, the reference's deviation from the ensemble median in robust units (the others' spread at
that turn), averaged over the turns: B. A game sits on one side of the median for long stretches by chance, so a
plain sign test over turns flags almost every metric; instead each B is compared with the members' leave-one-out
B for the same series (T = |B - mean| / sd), and the flag threshold is the 1 - alpha quantile of the members'
largest T over all series (a max-T threshold, which holds the chance of any false flag near alpha whatever the
correlation between series). A flagged series must also sit on one side of the median for most turns (the sign
fraction, default 90%), which is the plan's sign test in descriptive form.

Each test is a model built once from the ensemble (bands and the members' leave-one-out scores) and a score of a
reference against it, so the self-tests can score many references against one ensemble cheaply.
"""
from __future__ import annotations
import bisect
import math


def quantile(sorted_values, p):
    """Linear interpolation between order statistics (R type 7, numpy's default)."""
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return sorted_values[0]
    h = (n - 1) * p
    lo = int(math.floor(h))
    hi = min(lo + 1, n - 1)
    return sorted_values[lo] + (h - lo) * (sorted_values[hi] - sorted_values[lo])


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def sd(values):
    values = list(values)
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def _without(sorted_values, value):
    """sorted_values with one occurrence of value removed (a new list)."""
    i = bisect.bisect_left(sorted_values, value)
    return sorted_values[:i] + sorted_values[i + 1:]


def columns(ensemble, min_members, from_turn=0, to_turn=None):
    """{series: {turn: sorted member values}} for the points at least min_members members have."""
    raw = {}
    for g in ensemble:
        for name, s in g.items():
            col = raw.setdefault(name, {})
            for t, v in s.items():
                if v is not None and t >= from_turn and (to_turn is None or t <= to_turn):
                    col.setdefault(t, []).append(v)
    out = {}
    for name, col in raw.items():
        kept = {t: sorted(vs) for t, vs in col.items() if len(vs) >= min_members}
        if kept:
            out[name] = dict(sorted(kept.items()))
    return out


# ---- envelope ----

def _inside(v, col, lo, hi):
    a, b = quantile(col, lo), quantile(col, hi)
    return a - 1e-9 <= v <= b + 1e-9


def envelope_model(ensemble, lo=0.025, hi=0.975, min_members=8, from_turn=0, to_turn=None):
    """Bands and the members' leave-one-out coverages."""
    cols = columns(ensemble, min_members, from_turn, to_turn)
    loo = []
    for g in ensemble:
        inside = total = 0
        for name, col in cols.items():
            s = g.get(name) or {}
            for t, values in col.items():
                v = s.get(t)
                if v is None:
                    continue
                rest = _without(values, v)
                if len(rest) < 2:
                    continue
                total += 1
                inside += _inside(v, rest, lo, hi)
        if total:
            loo.append(inside / total)
    return dict(columns=cols, loo=loo, lo=lo, hi=hi, members=len(ensemble), min_members=min_members)


def envelope_score(model, reference, target=0.95, alpha=0.05, margin=0.02):
    """The envelope test of reference against a model. Returns a dict:
      status          pass, warn or fail (n/a with a reason when there is too little data)
      coverage        the reference's fraction of points inside the band
      points          the number of (series, turn) points scored
      expected        mean leave-one-out coverage of the members (what a game like them gets)
      looCoverages    every member's leave-one-out coverage
      threshold       min(target, the alpha quantile of looCoverages)
      pValue          rank of the reference's coverage among the members' (small: worse than most members)
      series          {name: {coverage, inside, points, outsideTurns, bands: {turn: [lo, median, hi]}}}
    """
    lo, hi, cols = model['lo'], model['hi'], model['columns']
    need = max(model['min_members'], 3)
    if model['members'] < need or not cols:
        return dict(status='n/a', reason=f"{model['members']} ensemble games with data; at least {need} are needed",
                    coverage=None, points=0, series={})
    inside = total = 0
    series = {}
    for name, col in cols.items():
        ref = reference.get(name) or {}
        i = n = 0
        outside, bands = [], {}
        for t, values in col.items():
            v = ref.get(t)
            if v is None:
                continue
            bands[t] = [quantile(values, lo), quantile(values, 0.5), quantile(values, hi)]
            n += 1
            if bands[t][0] - 1e-9 <= v <= bands[t][2] + 1e-9:
                i += 1
            else:
                outside.append(t)
        if n:
            series[name] = dict(coverage=i / n, inside=i, points=n, outsideTurns=outside, bands=bands)
            inside += i
            total += n
    if not total:
        return dict(status='n/a', reason='the reference has no points in common with the ensemble', coverage=None, points=0, series={})
    loo = model['loo']
    coverage = inside / total
    threshold = min(target, quantile(sorted(loo), alpha)) if loo else target
    p = (1 + sum(1 for c in loo if c <= coverage)) / (len(loo) + 1) if loo else None
    status = 'pass' if coverage >= threshold else 'warn' if coverage >= threshold - margin else 'fail'
    return dict(status=status, coverage=coverage, points=total, inside=inside, expected=mean(loo), looCoverages=loo,
                threshold=threshold, target=target, alpha=alpha, margin=margin, pValue=p, members=model['members'],
                band=[lo, hi], series=series)


def envelope(reference, ensemble, lo=0.025, hi=0.975, target=0.95, alpha=0.05, margin=0.02, min_members=8,
             from_turn=0, to_turn=None):
    return envelope_score(envelope_model(ensemble, lo, hi, min_members, from_turn, to_turn), reference, target, alpha, margin)


# ---- bias ----

def _robust_scale(sorted_values, median):
    """The spread used to standardise a deviation: IQR / 1.349, floored at 1% of |median|; None when the ensemble
    has no spread there (an IQR of 0: early turns where most games are alike say nothing about a distribution)."""
    iqr = quantile(sorted_values, 0.75) - quantile(sorted_values, 0.25)
    if iqr <= 1e-12:
        return None
    return max(iqr / 1.349, 0.01 * abs(median))


def _deviation(s, col, z_cap, leave_out):
    """(B, above, below, ties, mean |median| / scale) of one series {turn: value} against the column medians."""
    zs, above, below, ties, rel = [], 0, 0, 0, []
    for t, values in col.items():
        v = s.get(t)
        if v is None:
            continue
        if leave_out:
            values = _without(values, v)
        if len(values) < 2:
            continue
        med = quantile(values, 0.5)
        scale = _robust_scale(values, med)
        if scale is None:
            continue
        zs.append(max(-z_cap, min(z_cap, (v - med) / scale)))
        rel.append(min(abs(med) / scale, 1e6))
        if v > med + 1e-9:
            above += 1
        elif v < med - 1e-9:
            below += 1
        else:
            ties += 1
    if not zs:
        return None
    return mean(zs), above, below, ties, mean(rel)


def bias_model(ensemble, alpha=0.05, z_cap=10.0, min_members=8, from_turn=0, to_turn=None):
    """Per series the members' leave-one-out B (mean, sd) and the max-T threshold."""
    cols = columns(ensemble, min_members, from_turn, to_turn)
    per = {name: [] for name in cols}       # [(member index, B)]
    for k, g in enumerate(ensemble):
        for name, col in cols.items():
            d = _deviation(g.get(name) or {}, col, z_cap, leave_out=True)
            if d is not None:
                per[name].append((k, d[0]))
    moments = {name: (mean(b for _, b in v), max(sd(b for _, b in v), 1e-6)) for name, v in per.items() if len(v) >= 4}
    # Each member's T against the others' B (mean and sd without its own B), as the reference's T is against the
    # members': with its own B in the sd, a member's T could never exceed (n - 1) / sqrt(n).
    member_max = [0.0] * len(ensemble)
    for name in moments:
        for k, b in per[name]:
            others = [x for j, x in per[name] if j != k]
            mu, s = mean(others), max(sd(others), 1e-6)
            member_max[k] = max(member_max[k], abs(b - mu) / s)
    tau = quantile(sorted(member_max), 1 - alpha) if member_max else None
    return dict(columns=cols, moments=moments, memberMax=member_max, threshold=tau, alpha=alpha, z_cap=z_cap,
                members=len(ensemble), min_members=min_members)


def bias_score(model, reference, one_sided=0.9):
    """The bias check of reference against a model. Returns a dict:
      status          pass, or warn when a series is flagged (n/a with a reason when there is too little data)
      flagged         series names flagged, most extreme first
      threshold       the max-T threshold (1 - alpha quantile of the members' largest T)
      pValue          rank of the reference's largest T among the members' (global test)
      series          {name: {B, T, above, below, ties, signFraction, side, flagged, detectableShift}}
    detectableShift is the relative shift of the whole series (0.05 = 5%) that would reach the threshold: what the
    check can see in that metric with this ensemble.
    """
    need = max(model['min_members'], 4)
    if model['members'] < need or not model['moments']:
        return dict(status='n/a', reason=f"{model['members']} ensemble games with data; at least {need} are needed",
                    flagged=[], series={})
    tau = model['threshold']
    series, ref_max = {}, 0.0
    for name, (mu, s) in model['moments'].items():
        d = _deviation(reference.get(name) or {}, model['columns'][name], model['z_cap'], leave_out=False)
        if d is None:
            continue
        b, above, below, ties, rel = d
        T = abs(b - mu) / s
        ref_max = max(ref_max, T)
        decided = above + below
        frac = max(above, below) / decided if decided else 0.0
        series[name] = dict(B=b, T=T, above=above, below=below, ties=ties, signFraction=frac,
                            side='above' if above >= below else 'below',
                            flagged=tau is not None and T > tau and frac >= one_sided,
                            detectableShift=(tau * s / rel) if tau is not None and rel > 0 else None,
                            memberMean=mu, memberSd=s)
    if not series:
        return dict(status='n/a', reason='the reference has no series in common with the ensemble', flagged=[], series={})
    flagged = sorted((n for n, v in series.items() if v['flagged']), key=lambda n: -series[n]['T'])
    mm = model['memberMax']
    p = (1 + sum(1 for m in mm if m >= ref_max)) / (len(mm) + 1) if mm else None
    return dict(status='warn' if flagged else 'pass', flagged=flagged, threshold=tau, pValue=p, alpha=model['alpha'],
                oneSided=one_sided, members=model['members'], referenceMaxT=ref_max, memberMaxT=mm, series=series)


def bias(reference, ensemble, alpha=0.05, one_sided=0.9, z_cap=10.0, min_members=8, from_turn=0, to_turn=None):
    return bias_score(bias_model(ensemble, alpha, z_cap, min_members, from_turn, to_turn), reference, one_sided)


def shifted(game, factor, names=None):
    """A copy of game with the named series (all when None) multiplied by factor (negative controls)."""
    return {name: ({t: (v * factor if v is not None else None) for t, v in s.items()} if names is None or name in names else dict(s))
            for name, s in game.items()}

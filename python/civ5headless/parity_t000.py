#!/usr/bin/env python3
"""Compare two digest dumps (Game.DumpHeadlessState folders) section by section.

  parity_t000.py REF HOST [--fields DIR] [--mask-normalised] [--runs N]

REF and HOST are dump folders (<section>.bin + digest.txt) or run folders containing dump-t000\\. For every
section the report says identical, or gives the sizes, the number of differing byte runs and the first differing
offset. With a field map (<section>.fields.txt, written by a DLL built with tools/headless/fieldmap_transform.py;
--fields DIR, or found next to HOST's or REF's .bin files) each differing run is attributed to the Serialize call
that wrote it, and the distinct fields are listed.

--mask-normalised: differences inside the fields the current DLL normalises in the digest (docs/
headless-dll-additions.md, "Unstable bytes") are counted as masked, for references recorded with a DLL that
predates the normalisation. Needs a field map. A section whose differences are all masked is reported as
"identical (masked)".

savedb is not part of the digest total; it is compared and reported but does not affect the exit code.
Exit code 0 when every section in the total is identical (or masked), 1 otherwise.
"""
import argparse
import bisect
import os
import sys

# Members the DLL normalises in the digest (substrings of the field-map argument text).
NORMALISED = [
    'game.m_iTurnSlice', 'game.m_bTunerEverConnected', 'game.m_bSavedOnce', 'game.m_strGameId', 'map.m_guid',
    'player.m_uiStartTime', 'unit.m_uiLastPathTurnSlice',
    'gameTrade.m_aaiTechDifference', 'gameTrade.m_aaiPolicyDifference', 's_aaiUnbuilt',
    'notification.m_iExtraGameData', 'notification.m_ePlayerID',
    'playerTraits.m_bHasYieldFromTileCultureBomb', 'playerTraits.m_bHasYieldFromTileEarn',
    'playerTraits.m_bHasYieldFromTilePurchase',
    'playerCulture.m_eOpinion', 'playerCulture.m_ePreferredIdeology', 'playerCulture.m_eOpinionBiggestInfluence',
    'team.m_aiTechShareCount', 'team.m_aiNumTurnsLockedIntoWar', 'team.m_paiTurnMadePeaceTreatyWithTeam',
    'team.m_aiIgnoreWarningCount', 'team.m_abHasFoundPlayersTerritory', 'team.m_abHasMet', 'team.m_abAtWar',
    'team.m_abAggressorPacifier', 'team.m_abPermanentWarPeace', 'team.m_abEmbassy', 'team.m_abOpenBorders',
    'team.m_abDefensivePact', 'team.m_abResearchAgreement', 'team.m_abForcePeace', 'team.m_abWonLatestWar',
    'team.m_aiTurnTeamMet', 'team.m_aiTurnWarStarted', 'team.m_aiNumTurnsSinceVassalEnded',
]
NOT_IN_TOTAL = {'savedb'}


def dump_dir(path):
    if os.path.isdir(os.path.join(path, 'dump-t000')) and not any(f.endswith('.bin') for f in os.listdir(path)):
        return os.path.join(path, 'dump-t000')
    return path


def diff_runs(a, b, gap=4):
    """(start, end) runs of differing bytes over the common length; runs closer than gap bytes merge."""
    n = min(len(a), len(b))
    out = []
    i = 0
    while i < n:
        if a[i] != b[i]:
            last = i
            j = i + 1
            while j < n and j - last <= gap:
                if a[j] != b[j]:
                    last = j
                j += 1
            out.append((i, last + 1))
            i = last + 1
        else:
            i += 1
    if len(a) != len(b):
        out.append((n, max(len(a), len(b))))
    return out


def load_fields(dirs, section):
    for d in dirs:
        if not d:
            continue
        p = os.path.join(d, section + '.fields.txt')
        if os.path.exists(p):
            offs, what = [], []
            with open(p, encoding='latin-1') as f:
                for line in f:
                    o, _, w = line.rstrip('\n').partition(' ')
                    offs.append(int(o))
                    what.append(w)
            return offs, what
    return None


def field_at(fields, offset):
    if not fields:
        return None
    k = bisect.bisect_right(fields[0], offset) - 1
    return fields[1][k] if k >= 0 else '(section header)'


def is_normalised(field):
    return field is not None and any(n in field for n in NORMALISED)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ref')
    ap.add_argument('host')
    ap.add_argument('--fields', help='folder with <section>.fields.txt (default: HOST, then REF)')
    ap.add_argument('--mask-normalised', action='store_true')
    ap.add_argument('--runs', type=int, default=3, help='differing fields listed per section (default 3)')
    args = ap.parse_args(argv)
    ref, host = dump_dir(args.ref), dump_dir(args.host)
    field_dirs = [args.fields, host, ref]
    sections = sorted({f[:-4] for d in (ref, host) for f in os.listdir(d) if f.endswith('.bin')})
    ok = True
    summary = {'identical': 0, 'masked': 0, 'different': 0}
    for sec in sections:
        pa, pb = os.path.join(ref, sec + '.bin'), os.path.join(host, sec + '.bin')
        tag = '' if sec not in NOT_IN_TOTAL else ' (not in total)'
        if not os.path.exists(pa) or not os.path.exists(pb):
            print('%-12s missing in %s%s' % (sec, 'REF' if not os.path.exists(pa) else 'HOST', tag))
            ok = ok and sec in NOT_IN_TOTAL
            summary['different'] += 1
            continue
        a, b = open(pa, 'rb').read(), open(pb, 'rb').read()
        if a == b:
            print('%-12s identical (%d bytes)%s' % (sec, len(a), tag))
            summary['identical'] += 1
            continue
        runs = diff_runs(a, b)
        fields = load_fields(field_dirs, sec)
        attributed = [(s, e, field_at(fields, s)) for s, e in runs]
        real = [r for r in attributed if not (args.mask_normalised and is_normalised(r[2]))]
        if args.mask_normalised and fields and not real and len(a) == len(b):
            print('%-12s identical (masked: %d runs in normalised fields)%s' % (sec, len(runs), tag))
            summary['masked'] += 1
            continue
        summary['different'] += 1
        if sec not in NOT_IN_TOTAL:
            ok = False
        s0 = real[0][0] if real else runs[0][0]
        print('%-12s DIFFERENT sizes %d/%d, %d runs (%d not masked), first at %d%s' % (
            sec, len(a), len(b), len(runs), len(real), s0, tag))
        shown = {}
        for s, e, f in (real if real else attributed):
            key = f or '(no field map)'
            shown.setdefault(key, []).append((s, e))
        for key, lst in list(shown.items())[:args.runs]:
            s, e = lst[0]
            print('    %s x%d, first %d-%d REF %s HOST %s' % (key, len(lst), s, e, a[s:min(e, s + 12)].hex(),
                                                            b[s:min(e, s + 12)].hex()))
        if len(shown) > args.runs:
            print('    ... %d more fields' % (len(shown) - args.runs))
    print('summary: %(identical)d identical, %(masked)d identical after masking, %(different)d different' % summary)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

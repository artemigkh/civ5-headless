"""Compare two Civilization V game databases: schema, indexes, triggers and every row.

  python work/headless/dbdiff.py REFERENCE.db CANDIDATE.db [--rows 5] [--json OUT.json] [--data-only]

The oracle for the headless database builder (plan section 4.5): REFERENCE is the game's own
Civ5DebugDatabase.db, CANDIDATE the tool-built one. Rows are compared as multisets (row order and
rowids are not significant to the game). Exit code 0 when identical, 1 when they differ.
--data-only skips schema, index and trigger SQL (for exports made with CREATE TABLE AS SELECT).
"""
from pathlib import Path
import argparse, collections, json, sqlite3, sys


def norm_sql(sql):
    return ' '.join((sql or '').split())


def objects(conn, kind):
    return {name: norm_sql(sql) for name, sql in conn.execute(
        "select name, sql from sqlite_master where type = ? and name not like 'sqlite_%'", (kind,))}


def rows(conn, table):
    cols = [r[1] for r in conn.execute(f'pragma table_info("{table}")')]
    return cols, collections.Counter(conn.execute(f'select * from "{table}"').fetchall())


def diff(ref_path, cand_path, show=5, data_only=False):
    ref = sqlite3.connect(Path(ref_path).resolve().as_uri() + '?mode=ro', uri=True)
    cand = sqlite3.connect(Path(cand_path).resolve().as_uri() + '?mode=ro', uri=True)
    out = {'reference': str(ref_path), 'candidate': str(cand_path)}
    rt, ct = objects(ref, 'table'), objects(cand, 'table')
    out['tables_only_reference'] = sorted(set(rt) - set(ct))
    out['tables_only_candidate'] = sorted(set(ct) - set(rt))
    if not data_only:
        out['schema_differs'] = sorted(t for t in set(rt) & set(ct) if rt[t] != ct[t])
        for kind in ('index', 'trigger', 'view'):
            r, c = objects(ref, kind), objects(cand, kind)
            out[kind + '_differs'] = {'only_reference': sorted(set(r) - set(c)), 'only_candidate': sorted(set(c) - set(r)),
                                       'sql_differs': sorted(n for n in set(r) & set(c) if r[n] != c[n])}
    tables = []
    for t in sorted(set(rt) & set(ct)):
        rc, rr = rows(ref, t)
        cc, cr = rows(cand, t)
        if rc != cc:
            tables.append({'table': t, 'columns_reference': rc, 'columns_candidate': cc})
            continue
        if rr != cr:
            missing, extra = rr - cr, cr - rr
            tables.append({'table': t, 'rows_reference': sum(rr.values()), 'rows_candidate': sum(cr.values()),
                           'missing': [list(x) for x in list(missing.elements())[:show]],
                           'extra': [list(x) for x in list(extra.elements())[:show]],
                           'missing_count': sum(missing.values()), 'extra_count': sum(extra.values())})
    out['tables_differ'] = tables
    out['identical'] = not (out['tables_only_reference'] or out['tables_only_candidate'] or tables or
                            (not data_only and (out['schema_differs'] or any(v['only_reference'] or v['only_candidate'] or v['sql_differs']
                                                                             for k, v in out.items() if k.endswith('_differs') and isinstance(v, dict)))))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('reference', type=Path)
    ap.add_argument('candidate', type=Path)
    ap.add_argument('--rows', type=int, default=5, help='example rows to show per differing table')
    ap.add_argument('--json', type=Path)
    ap.add_argument('--data-only', action='store_true')
    a = ap.parse_args()
    out = diff(a.reference, a.candidate, a.rows, a.data_only)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1, default=str) + '\n', encoding='utf-8')
    print('identical' if out['identical'] else 'DIFFERENT')
    for key in ('tables_only_reference', 'tables_only_candidate', 'schema_differs'):
        if out.get(key):
            print(f'{key}: {len(out[key])}: {out[key][:10]}')
    for kind in ('index', 'trigger', 'view'):
        v = out.get(kind + '_differs')
        if v and (v['only_reference'] or v['only_candidate'] or v['sql_differs']):
            print(f'{kind}: only_reference {len(v["only_reference"])}, only_candidate {len(v["only_candidate"])}, sql_differs {len(v["sql_differs"])}')
    for t in out['tables_differ'][:40]:
        if 'missing_count' in t:
            print(f"{t['table']}: reference {t['rows_reference']} rows, candidate {t['rows_candidate']}; missing {t['missing_count']}, extra {t['extra_count']}")
            for r in t['missing'][:2]: print('   missing', r)
            for r in t['extra'][:2]: print('   extra  ', r)
        else:
            print(f"{t['table']}: columns differ")
    if len(out['tables_differ']) > 40:
        print(f"... {len(out['tables_differ']) - 40} more tables differ")
    return 0 if out['identical'] else 1


if __name__ == '__main__':
    sys.exit(main())

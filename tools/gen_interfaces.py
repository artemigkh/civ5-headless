"""Generate C++ classes for the engine interfaces the game DLL calls.

  python tools/headless/gen_interfaces.py [--check]

Reads the Firaxis interface headers in CvGameCoreDLLUtil/include and writes:

  CvGameCoreDLL_Expansion2/Headless/HHTraceProxies.gen.h
      Forwarding proxies (DLL side, trace builds only). Every method records a call
      through the HHTrace* functions, forwards to the engine's object and records the
      return value and simple out parameters. Script argument objects are unwrapped
      before they go back to the engine. The recorder (Headless/HHTrace.h) defines
      HHTraceMethod, HHTraceCall, HHTraceArg, HHTraceOutRef, HHTraceRet and
      HHTraceUnwrapArgs.
  Civ5Headless/gen/HHStubs.gen.h
      Stub bases for the headless host. Every method reports itself through
      HH_STUB_CALL(name) and returns a value-initialised result; the host overrides
      the methods it implements.
  Civ5Headless/gen/HHInterfaces.gen.json
      The method table (interface, index, name, signature) used by the trace tools.

The generated classes derive from the real interface classes, so the compiler checks
every signature, calling convention and the vtable layout. --check only parses and
prints the method counts.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ROOT / 'CvGameCoreDLLUtil/include'
OUT_PROXIES = ROOT / 'CvGameCoreDLL_Expansion2/Headless/HHTraceProxies.gen.h'
OUT_STUBS = ROOT / 'Civ5Headless/gen/HHStubs.gen.h'
OUT_JSON = ROOT / 'Civ5Headless/gen/HHInterfaces.gen.json'

# (generated class suffix, most-derived interface, header, GUID constants answered by QueryInterface)
TARGETS = [
    ('EngineUtility', 'ICvEngineUtility4', 'ICvDLLUtility.h',
     ['guidICvEngineUtility1', 'guidICvEngineUtility2', 'guidICvEngineUtility3', 'guidICvEngineUtility4']),
    ('UserInterface', 'ICvUserInterface2', 'ICvDLLUserInterface.h',
     ['guidICvUserInterface1', 'guidICvUserInterface2']),
    ('ScriptSystem', 'ICvEngineScriptSystem1', 'ICvDLLScriptSystem.h', []),
    ('ScriptArgs', 'ICvEngineScriptSystemArgs1', 'ICvDLLScriptSystem.h', []),
]
HEADERS = ['CvDllInterfaces.h', 'ICvDLLUtility.h', 'ICvDLLUserInterface.h', 'ICvDLLScriptSystem.h']
DROP_PREFIX = re.compile(r'\b(DECLSPEC_DEPRECATED|_Ret_maybenull_|_Ret_notnull_|_Ret_)\b\s*')
CALLCONV = re.compile(r'\b(DLLCALL|__stdcall|__cdecl|__thiscall)\b')
ANNOTATION = re.compile(r'\b(__checkReturn|_Check_return_)\b')


def strip_comments(text):
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def split_top(text, sep=','):
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in '(<[':
            depth += 1
        elif ch in ')>]':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append(''.join(cur))
    return [p.strip() for p in parts if p.strip()]


def parse_classes(text):
    """Return {class name: (base or None, [method dict])} for every class body in text."""
    classes = {}
    for m in re.finditer(r'\bclass\s+(\w+)\s*(?::\s*public\s+(\w+))?\s*\{', text):
        name, base = m.group(1), m.group(2)
        depth, i = 1, m.end()
        while depth:
            depth += {'{': 1, '}': -1}.get(text[i], 0)
            i += 1
        body = text[m.end():i - 1]
        # Drop inline function bodies so their statements are not mistaken for declarations.
        flat = re.sub(r'\{[^{}]*\}', ';', re.sub(r'\{[^{}]*\{[^{}]*\}[^{}]*\}', ';', body))
        methods = []
        for stmt in flat.split(';'):
            stmt = ' '.join(stmt.split())
            if 'virtual' not in stmt or not re.search(r'=\s*0$', stmt):
                continue
            methods.append(parse_method(stmt, name))
        classes[name] = (base, methods)
    return classes


def parse_method(stmt, owner):
    stmt = re.sub(r'=\s*0$', '', stmt).strip()
    stmt = DROP_PREFIX.sub('', stmt)
    stmt = stmt[stmt.index('virtual') + len('virtual'):].strip()
    const = False
    if stmt.endswith('const'):
        const, stmt = True, stmt[:-5].strip()
    if not stmt.endswith(')'):
        raise ValueError(f'{owner}: cannot parse {stmt!r}')
    depth, i = 0, len(stmt) - 1
    while True:
        depth += {')': 1, '(': -1}.get(stmt[i], 0)
        if depth == 0:
            break
        i -= 1
    params_text, head = stmt[i + 1:-1], stmt[:i].strip()
    nm = re.search(r'(\w+)$', head)
    name, prefix = nm.group(1), head[:nm.start()].strip()
    ret = ' '.join(ANNOTATION.sub('', CALLCONV.sub('', prefix)).split())
    params = []
    if params_text.strip() not in ('', 'void'):
        for k, raw in enumerate(split_top(params_text)):
            decl = split_top(raw, '=')[0] if '=' in raw else raw
            decl = re.sub(r'\s*=\s*.*$', '', decl) if re.search(r'=(?![=])', decl) else decl
            arr = ''
            am = re.search(r'(\s*\[\s*\w*\s*\])+$', decl)
            if am:
                arr, decl = am.group(0).strip(), decl[:am.start()].strip()
            tokens = re.findall(r'\w+|[^\w\s]', re.sub(r'\b_\w+_(\([^)]*\))?', '', decl))
            words = [t for t in tokens if re.match(r'\w+$', t) and t not in ('const', 'unsigned', 'signed', 'struct', 'class')]
            named = len(words) >= 2 and re.search(r'\w+$', decl) and not re.search(r'[*&>]\s*$', decl)
            if named:
                pname = re.search(r'(\w+)$', decl).group(1)
                ptype = decl[:-len(pname)].strip()
            else:
                pname, ptype = f'a{k}', decl.strip()
            params.append({'type': ptype + (' *' if arr else ''), 'decl_type': ptype, 'name': pname, 'array': arr})
    return {'owner': owner, 'name': name, 'prefix': prefix, 'ret': ret, 'const': const, 'params': params}


def chain(classes, name):
    out = []
    while name:
        base, methods = classes[name]
        out.insert(0, (name, methods))
        name = base
    return out


def signature(m):
    params = ', '.join(f"{p['decl_type']} {p['name']}{p['array']}" for p in m['params'])
    return f"{m['prefix']} {m['name']}({params}){' const' if m['const'] else ''}"


def call_args(m):
    return ', '.join(p['name'] for p in m['params'])


# Non-const reference parameters whose value after the call is recorded (out parameters).
OUT_REF = re.compile(r'^(bool|int|uint|unsigned int|float|double|char\s*\*|CvString)\s*&$')
# Script argument objects handed back to the engine must be the engine's own objects.
ARGS_PTR = re.compile(r'^ICvEngineScriptSystemArgs1\s*\*$')


def bare_type(decl_type):
    return ' '.join(re.sub(r'\b_\w+_\b', '', decl_type).split())


def gen_proxy(suffix, iface, methods, guids):
    lines = [f'class HHTrace{suffix} : public {iface}', '{', 'public:',
             f'\texplicit HHTrace{suffix}({iface}* pInner) : m_pInner(pInner) {{}}',
             f'\t{iface}* Inner() const {{ return m_pInner; }}', '']
    for m in methods:
        qual = f"{m['owner']}::{m['name']}"
        body = []
        if m['owner'] == 'ICvUnknown' and m['name'] == 'QueryInterface':
            for g in guids:
                body.append(f'\t\tif (guidInterface == {g}) return static_cast<{iface}*>(this);')
            body.append('\t\treturn m_pInner->QueryInterface(guidInterface);')
        elif m['owner'] == 'ICvUnknown' and m['name'] == 'Destroy':
            body.append('\t\tm_pInner->Destroy();')
        else:
            body.append('\t\tstatic HHTraceMethod* hhSite = NULL;')
            body.append(f'\t\tHHTraceCall hhCall(HHTRACE_OUT, "{qual}", hhSite);')
            for p in m['params']:
                body.append(f"\t\tHHTraceArg(hhCall, {p['name']});")
            for p in m['params']:
                if OUT_REF.match(bare_type(p['decl_type'])):
                    body.append(f"\t\tHHTraceOutRef(hhCall, \"{p['name']}\", {p['name']});")
            forward = ', '.join(f"HHTraceUnwrapArgs({p['name']})" if ARGS_PTR.match(bare_type(p['decl_type']))
                                else p['name'] for p in m['params'])
            if m['ret'] == 'void':
                body.append(f'\t\tm_pInner->{m["name"]}({forward});')
            else:
                body.append(f'\t\t{m["ret"]} hhResult = m_pInner->{m["name"]}({forward});')
                body.append('\t\tHHTraceRet(hhCall, hhResult);')
                body.append('\t\treturn hhResult;')
        lines += [f'\t{signature(m)}', '\t{', *body, '\t}']
    lines += ['private:', f'\t{iface}* m_pInner;', '};', '']
    return lines


def gen_stub(suffix, iface, methods, has_dtor):
    lines = [f'class HHStub{suffix} : public {iface}', '{', 'public:']
    if has_dtor:
        lines.append(f'\tvirtual ~HHStub{suffix}() {{}}')
    for m in methods:
        qual = f"{m['owner']}::{m['name']}"
        if m['ret'] == 'void':
            body = f'HH_STUB_CALL("{qual}");'
        else:
            body = f'HH_STUB_CALL("{qual}"); return HHStubDefault< {m["ret"]} >();'
        lines.append(f'\t{signature(m)} {{ {body} }}')
    lines += ['};', '']
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    classes = {}
    for h in HEADERS:
        classes.update(parse_classes(strip_comments((INCLUDE / h).read_text(encoding='latin-1'))))
    table, proxies, stubs = [], [], []
    for suffix, iface, header, guids in TARGETS:
        methods = [m for _, ms in chain(classes, iface) for m in ms]
        print(f'{iface}: {len(methods)} methods ({", ".join(f"{n} {len(ms)}" for n, ms in chain(classes, iface))})')
        for i, m in enumerate(methods):
            table.append({'interface': iface, 'index': i, 'owner': m['owner'], 'name': m['name'],
                          'signature': signature(m), 'returns': m['ret'],
                          'params': [p['decl_type'] + ' ' + p['name'] + p['array'] for p in m['params']]})
        proxies += gen_proxy(suffix, iface, methods, guids)
        stubs += gen_stub(suffix, iface, methods, iface == 'ICvEngineScriptSystemArgs1')
    if args.check:
        return 0
    banner = ['// Generated by tools/headless/gen_interfaces.py from CvGameCoreDLLUtil/include.',
              '// Do not edit; rerun the generator.', '#pragma once', '']
    # getInterfaceIFace is declared deprecated but still has to be overridden.
    wrap = (['#pragma warning(push)', '#pragma warning(disable:4996)', ''], ['#pragma warning(pop)', ''])
    OUT_PROXIES.parent.mkdir(parents=True, exist_ok=True)
    OUT_STUBS.parent.mkdir(parents=True, exist_ok=True)
    OUT_PROXIES.write_text('\n'.join(banner + ['// Requires Headless/HHTrace.h.', ''] + wrap[0] + proxies + wrap[1]), encoding='utf-8', newline='\r\n')
    OUT_STUBS.write_text('\n'.join(banner + ['// Requires HH_STUB_CALL(name) and template<class T> T HHStubDefault().', ''] + wrap[0] + stubs + wrap[1]), encoding='utf-8', newline='\r\n')
    OUT_JSON.write_text(json.dumps(table, indent=1) + '\n', encoding='utf-8')
    print(f'wrote {OUT_PROXIES.relative_to(ROOT)}, {OUT_STUBS.relative_to(ROOT)}, {OUT_JSON.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

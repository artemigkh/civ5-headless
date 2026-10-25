"""UI hazard scan: calls in UI Lua (InGameUIAddins, UI overrides) to DLL Lua methods that change game state.

  python -m civ5headless.hazards scan [--report RUN/host-report.json] [PATH ...] [--dll-source DIR] [--profiles DIR]
                                      [--json OUT] [--all]
  python -m civ5headless.hazards methods --dll-source DIR [--json OUT]

The host does not run the game's UI. UI code that calls a state-changing method (a setter, a do/change function, a
getter with a lazy cache, the synchronised random number generator) changes the game in the real game but not in
the host, unless a UI emulation profile (profiles/, docs/profiles.md) does the same call. The scan lists those call
sites so a mod set's UI can be checked before a run.

Files: --report takes the add-ins and UI files a host run loaded (host-report.json: addins.contexts, uiFiles); PATH
arguments add files or folders (every .lua below). Only UI files count: add-ins, UI overrides, DLC UI.

Methods: with --dll-source (a CvGameCoreDLL_Expansion2 folder), from the DLL's Lua bindings (Lua/CvLua*.cpp):
  writes  the binding calls a set/change/do/init/kill/... method of a game object
  cache   the binding reaches, within three calls, a function that writes a cache from a const function
          (const_cast<...>(this) or a mutable member): the result can depend on when the UI calls it
Without it, python/civ5headless/data/lua-state-methods.json (the same derivation from the VP and stock sources).
Both are merged with the curated python/civ5headless/data/lua-hazards.json: getters known to write state, and engine
calls (Network.Send*) that the real game turns into DLL calls.

Output (JSON, --json): {format, methods: {source, writes, cache, curated}, files: [...], hits: [{file, path, line,
method, classes, kind, why, call, function, triggers, covered, profile}], summary}. covered names the profile that
emulates the call (its manifest's covers: file and methods); with --report, only profiles selected in that run.
Standard library only.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent / 'data'
FORMAT = 'civ5headless-hazards/1'

# ---------------------------------------------------------------------------------------------------------------
# DLL sources: the Lua bindings and what they call
# ---------------------------------------------------------------------------------------------------------------
_COMMENT = re.compile(r'//[^\n]*|/\*.*?\*/', re.S)
_STRING = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
_DEF = re.compile(r'(?:^|\n)[ \t]*(?:[\w:<>\*&,]+[ \t\*&]+)+?(\w+)::(~?\w+)[ \t]*\(([^;{}()]*(?:\([^;{}()]*\)[^;{}()]*)*)\)'
                  r'[ \t\n]*(const)?[ \t\n]*(?::[^{;]*)?\{')
_CALL = re.compile(r'(->|\.|::|&)?\s*\b([A-Za-z_]\w*)\s*\(')
_MEMBER_PTR = re.compile(r'&\s*(Cv\w+)::(\w+)')
_REGISTER = re.compile(r'\bMethod\(\s*(\w+)\s*\)')
_MUTATING = re.compile(r'^(?:[Ss]et|[Cc]hange|[Dd]o|[Ii]nit|[Kk]ill|[Cc]reate|[Ff]ound|[Aa]cquire|[Dd]isband|[Aa]dd|[Rr]emove|'
                       r'[Cc]lear|[Rr]eset|[Pp]rocess|[Uu]pdate|[Ii]ncrement|[Dd]ecrement|[Cc]onvert|[Rr]aze|[Gg]ift|'
                       r'[Rr]eceive|[Aa]pply|[Ss]pawn|[Gg]ive|[Mm]ake|[Dd]eclare|[Mm]eet|[Ll]iberate|[Tt]ransfer|'
                       r'[Pp]illage|[Cc]ancel|[Aa]ctivate|[Dd]eactivate|[Tt]rigger|[Aa]ward|[Gg]rant|[Ss]wap|[Pp]op|'
                       r'[Jj]oin|[Ee]xpend|[Ss]pend|[Cc]hoose|[Pp]ick|[Pp]urchase|[Bb]uy|[Ss]ell|[Ee]nd|[Ss]tart|'
                       r'[Ff]orce|[Ee]rase|[Ii]nsert|[Pp]ush|[Aa]dopt|[Ee]nact|[Rr]epeal|[Ee]nable|[Dd]isable|[Ee]quip|'
                       r'[Uu]nlock|[Ll]earn|[Rr]esearch|[Ee]xecute|[Ee]stablish|[Pp]lace|[Mm]ove|[Ee]mbark|'
                       r'[Pp]romote|[Hh]eal|[Rr]evoke|[Dd]estroy|[Dd]elete|[Dd]ismiss|[Ss]ign)(?=[A-Z_0-9])')
_NOT_STATE = {'push_back', 'push_front', 'pop_back', 'pop_front'}
# Container and helper names shared with game classes: not followed when looking for caches.
_GENERIC = {'erase', 'insert', 'find', 'size', 'begin', 'end', 'clear', 'push_back', 'get', 'set', 'at', 'count',
            'empty', 'resize', 'reserve', 'swap', 'front', 'back', 'add', 'remove', 'reset', 'init', 'update',
            'contains', 'Get', 'Set', 'Add', 'Remove', 'Reset', 'Init', 'Update', 'Clear', 'Find', 'Count'}
_CONST_CAST_THIS = re.compile(r'const_cast\s*<\s*\w+\s*\*\s*>\s*\(\s*this\s*\)\s*->\s*(\w+)')
_MUTABLE = re.compile(r'^\s*mutable\s+[^;()]*?\b(\w+)\s*(?:\[[^\]]*\])?\s*(?::\s*\d+)?\s*;', re.M)
_GETTER = re.compile(r'^(?:[Gg]et|[Ii]s|[Hh]as|[Cc]an|[Cc]alculate|[Cc]ount|[Ff]ind)(?=[A-Z_0-9])')
_MEMBER_WRITE = r'(?<![.>\w]){0}\s*(?:\[[^\]\n]*\]\s*)*(?:=(?!=)|\+=|-=|\*=|/=|\|=|&=|\+\+|--|\.push_back|\.clear\s*\(|\.erase|' \
                r'\.insert|\.resize|\.assign|\.swap|\.pop_back)|(?:\+\+|--)\s*{0}\b'
_ANY_MEMBER_WRITE = re.compile(_MEMBER_WRITE.format(r'm_\w+'))
_LOCAL_DECL = re.compile(r'(?:\b([A-Za-z_][\w:]*)\s*(?:<[^;{}()]*>)?\s*[&\*]*\s+|[>&\*]\s*)(m_\w+)\s*(?:=(?!=)|;|\[)')
_KEYWORDS = {'return', 'else', 'case', 'delete', 'new', 'throw', 'goto', 'do', 'sizeof'}


def _member_write(body, pattern):
    """The first write to a member (m_ name, not a local of that name, not another object's member), or None."""
    local = {m.group(2) for m in _LOCAL_DECL.finditer(body) if m.group(1) not in _KEYWORDS}
    for w in pattern.finditer(body):
        name = re.match(r'(?:\+\+|--)?\s*(\w+)', w.group(0)).group(1)
        if name not in local:
            return name
    return None


def _strip_cpp(text):
    text = _COMMENT.sub(lambda m: '\n' * m.group(0).count('\n'), text)
    return _STRING.sub('""', text)


def _functions(root):
    """{name: [(class, body, const)]} of every function defined in the .cpp files below root."""
    funcs = defaultdict(list)
    for path in sorted(Path(root).rglob('*.cpp')):
        text = _strip_cpp(path.read_text(encoding='latin-1'))
        for m in _DEF.finditer(text):
            i, depth = m.end(), 1
            while depth and i < len(text):
                c = text[i]
                depth += 1 if c == '{' else -1 if c == '}' else 0
                i += 1
            funcs[m.group(2)].append((m.group(1), text[m.end():i - 1], bool(m.group(4))))
    return funcs


def _refs(body):
    """Names declared in a body as references or pointers (game objects), not values."""
    return set(re.findall(r'[&\*]\s*(\w+)\s*(?:=|;|,|\))', body))


def _state_calls(body):
    """Mutating-named calls of a binding body on game objects: member pointers, -> calls, calls on a call's result
    or on a reference or pointer; not Lua helpers, not calls on local values."""
    out = []
    refs = _refs(body)
    for m in _MEMBER_PTR.finditer(body):
        if _MUTATING.match(m.group(2)):
            out.append(m.group(2))
    for m in _CALL.finditer(body):
        op, name = m.group(1), m.group(2)
        if name in _NOT_STATE or name.lower().startswith('lua') or not _MUTATING.match(name) or op in (None, '::', '&'):
            continue
        if name.startswith('Push'):  # Lua push helpers (CvLuaX::Push, PushX)
            continue
        if op == '.':
            before = body[:m.start()].rstrip()
            ident = re.search(r'(\w+)\s*$', before)
            if not before.endswith(')') and not (ident and ident.group(1) in refs):
                continue
        out.append(name)
    return sorted(set(out))


def _callees(body):
    names = {m.group(2) for m in _MEMBER_PTR.finditer(body)}
    names |= {m.group(2) for m in _CALL.finditer(body) if m.group(1) in ('->', '.', None)}
    return names


def derive_methods(root, depth=5, harmless=()):
    """{lua class: {method: {kind, calls?, chain?}}} for every Lua binding below root (a CvGameCoreDLL folder)."""
    root = Path(root)
    funcs = _functions(root)
    mutable = set()
    for h in root.rglob('*.h'):
        mutable |= set(_MUTABLE.findall(_strip_cpp(h.read_text(encoding='latin-1'))))
    mutable_write = re.compile('|'.join(_MEMBER_WRITE.format(re.escape(n)) for n in sorted(mutable))) if mutable else None
    lazy = {}
    for name, defs in funcs.items():
        for cls, body, const in defs:
            if cls.startswith('CvLua') or f'{cls}::{name}' in harmless:
                continue
            m = _CONST_CAST_THIS.search(body)
            if m:
                lazy[name] = f'{cls}::{name} const_cast(this)->{m.group(1)}'
                break
            if const and mutable_write is not None:
                w = _member_write(body, mutable_write)
                if w:
                    lazy[name] = f'{cls}::{name} writes mutable {w}'
                    break
            if _GETTER.match(name) and cls.startswith('Cv'):
                w = _member_write(body, _ANY_MEMBER_WRITE)
                if w:
                    lazy[name] = f'{cls}::{name} writes {w}'
                    break

    memo = {}

    def reaches(name, d, stack):
        if name in lazy:
            return [lazy[name]]
        key = (name, d)
        if key in memo:
            return memo[key]
        if d == 0 or name in stack:
            return None
        defs = [x for x in funcs.get(name, []) if not x[0].startswith('CvLua')]
        if not defs or len(defs) > 4:  # unknown, or a name too common to follow
            memo[key] = None
            return None
        stack.add(name)
        found = None
        for cls, body, const in defs:
            for callee in sorted(_callees(body)):
                if callee != name and callee in funcs and callee not in _GENERIC:
                    r = reaches(callee, d - 1, stack)
                    if r:
                        found = [f'{cls}::{name}'] + r
                        break
            if found:
                break
        stack.discard(name)
        memo[key] = found
        return found

    out = defaultdict(dict)
    for path in sorted((root / 'Lua').glob('CvLua*.cpp')):
        text = _strip_cpp(path.read_text(encoding='latin-1'))
        cls = path.stem
        lua_class = cls[len('CvLua'):]
        registered = _REGISTER.findall(text)
        bodies = {}
        for name, defs in funcs.items():
            if name.startswith('l'):
                for c, body, const in defs:
                    if c == cls:
                        bodies[name[1:]] = body
        for method in registered:
            body = bodies.get(method)
            if body is None:
                continue
            calls = _state_calls(body)
            if calls:
                out[lua_class][method] = {'kind': 'writes', 'calls': calls}
                continue
            for callee in sorted(_callees(body)):
                if callee in funcs and not callee.lower().startswith('lua'):
                    chain = reaches(callee, depth - 1, set())
                    if chain:
                        out[lua_class][method] = {'kind': 'cache', 'chain': chain}
                        break
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def load_curated():
    return json.loads((DATA / 'lua-hazards.json').read_text(encoding='utf-8'))


def harmless_caches(curated):
    return {e['function'] for e in curated.get('harmlessCaches', [])}


def load_methods(dll_source=None):
    """(method name -> [entries], source text, curated data). Entries: {class, kind, why}; derived plus curated."""
    curated = load_curated()
    if dll_source:
        derived = derive_methods(dll_source, harmless=harmless_caches(curated))
        source = str(dll_source)
    else:
        doc = json.loads((DATA / 'lua-state-methods.json').read_text(encoding='utf-8'))
        derived = doc['classes']
        source = 'data/lua-state-methods.json (' + doc.get('source', '') + ')'
    by_name = defaultdict(list)
    for cls, methods in derived.items():
        for name, info in methods.items():
            why = ('calls ' + ', '.join(info['calls'])) if info['kind'] == 'writes' else ' > '.join(info.get('chain', []))
            by_name[name].append({'class': cls, 'kind': info['kind'], 'why': why})
    for entry in curated.get('notHazards', []):
        by_name[entry['name']] = [e for e in by_name[entry['name']] if e['class'] != entry['class']]
    for entry in curated['methods']:
        by_name[entry['name']] = [e for e in by_name[entry['name']] if e['class'] != entry['class']]
        by_name[entry['name']].append({'class': entry['class'], 'kind': 'curated', 'why': entry['why']})
    return {k: v for k, v in by_name.items() if v}, source, curated


# ---------------------------------------------------------------------------------------------------------------
# Lua scanning
# ---------------------------------------------------------------------------------------------------------------
_LUA_STRIP = re.compile(r'--\[(=*)\[.*?\]\1\]|--[^\n]*|\[(=*)\[.*?\]\2\]|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)
_LUA_BLOCK = re.compile(r'\b(function|if|do|repeat|end|until)\b')
_LUA_MEMBER = re.compile(r'([:.])[ \t]*([A-Za-z_]\w*)')
_STATIC = ('Game', 'Map')
_REGISTRATIONS = ((r'\b(Events|GameEvents|LuaEvents)\.(\w+)\.Add\s*\(\s*', '{0}.{1}'),
                  (r'RegisterCallback\s*\(\s*([\w.]+)\s*,\s*', 'callback {0}'),
                  (r'ContextPtr\s*:\s*(Set\w+)\s*\(\s*', 'ContextPtr:{0}'))


def _strip_lua(text):
    """Comments and string contents blanked, line structure kept."""
    out, i = [], 0
    for m in _LUA_STRIP.finditer(text):
        out.append(text[i:m.start()])
        s = m.group(0)
        if s.startswith('--'):
            out.append(re.sub(r'[^\n]', ' ', s))
        else:  # keep the delimiters so a call on a string literal still parses
            out.append(s[0] + re.sub(r'[^\n]', ' ', s[1:-1]) + s[-1])
        i = m.end()
    out.append(text[i:])
    return ''.join(out)


def _functions_at(code):
    """[(start, end, name, text before)] of every function in stripped Lua code; name '' for an anonymous function,
    whose text before shows registrations such as Events.X.Add(function ...)."""
    stack, spans = [], []
    for m in _LUA_BLOCK.finditer(code):
        kw = m.group(1)
        if kw in ('do', 'if', 'repeat'):  # for ... do, while ... do and do ... end open a block at do
            stack.append((kw, m.start(), None))
        elif kw == 'function':
            before = code[max(0, m.start() - 160):m.start()]
            name = ''
            n = re.match(r'\s*([\w.:]+)\s*\(', code[m.end():m.end() + 120])
            if n:
                name = n.group(1)
            else:
                a = re.search(r'([\w.]+)\s*=\s*$', before)
                if a:
                    name = a.group(1)
            stack.append(('function', m.start(), (name, before)))
        elif stack:  # end, until
            k, start, info = stack.pop()
            if k == 'function':
                spans.append((start, m.end(), info[0], info[1]))
    return spans


def _registrations(code, name, before):
    """How a function runs: Events / GameEvents / LuaEvents registrations, control callbacks, ContextPtr handlers."""
    out = []
    if name:
        names = {name, name.split('.')[-1].split(':')[-1]}
        alt = '|'.join(re.escape(n) for n in sorted(names))
        for pat, label in _REGISTRATIONS:
            for m in re.finditer(pat + r'(?:%s)\s*[,)]' % alt, code):
                out.append(label.format(*m.groups()))
    else:
        for pat, label in _REGISTRATIONS:
            m = re.search(pat + '$', before)
            if m:
                out.append(label.format(*m.groups()))
    return sorted(set(out))


class _LuaFile:
    def __init__(self, text):
        self.code = _strip_lua(text)
        self.spans = _functions_at(self.code)
        self.line_starts = [0] + [m.end() for m in re.finditer(r'\n', self.code)]

    def line_of(self, pos):
        lo, hi = 0, len(self.line_starts)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid
        return lo + 1

    def context(self, pos, depth=2):
        """(enclosing function names, triggers). Triggers: 'load' at top level; else, from the innermost function out,
        the first that has registrations (Events.X.Add, callbacks, ContextPtr handlers) or other uses: called by
        another function ('via' its triggers, depth levels), or passed as a value ('passed to' the callee)."""
        inner = sorted((s for s in self.spans if s[0] <= pos < s[1]), key=lambda s: s[0])
        if not inner:
            return '', ['load']
        names = [s[2] or '<anonymous>' for s in reversed(inner)]
        for start, end, name, before in reversed(inner):
            found = _registrations(self.code, name, before)
            if not found and name:
                found = self._uses(name, start, depth)
            if not found and not name:
                m = re.search(r'([\w.:\[\]]+)\s*\(\s*(?:[^()]*,\s*)?$', before)
                if m:
                    found = ['passed to ' + m.group(1)]
            if found:
                return ' < '.join(names), found
        return ' < '.join(names), []

    def _uses(self, name, def_start, depth):
        short = name.split('.')[-1].split(':')[-1]
        found = set()
        for m in re.finditer(r'(?<![\w.:])%s\b' % re.escape(short), self.code):
            if def_start <= m.start() < def_start + 12 + len(name):
                continue  # the definition
            head = self.code[self.code.rfind('\n', 0, m.start()) + 1:m.start()]
            if re.search(r'function\s*[\w.:]*$', head) or re.search(r'local\s+$', head):
                continue
            tail = self.code[m.end():m.end() + 40].lstrip()[:1]
            if tail == '(':
                if depth > 0:
                    _, t = self.context(m.start(), depth - 1)
                    found.update(x if x.startswith(('via ', 'passed to ')) else 'via ' + x for x in t)
            elif tail != '=':
                callee = re.search(r'([\w.:\[\]]+)\s*\([^()]*$', self.code[max(0, m.start() - 200):m.start()])
                if callee:
                    found.add('passed to ' + callee.group(1))
                else:
                    a = re.search(r'([\w.\[\]]+)\s*=\s*$', head)
                    if a:
                        found.add('assigned to ' + a.group(1))
        return sorted(found)


def _receiver(code, pos):
    """The expression before a ':' or '.' at pos (crude: names, dots, brackets and calls)."""
    j, depth = pos, 0
    while j > 0:
        c = code[j - 1]
        if c in ')]':
            depth += 1
        elif c in '([':
            if depth == 0:
                break
            depth -= 1
        elif not (c.isalnum() or c in '_.:') and depth == 0:
            break
        j -= 1
    return code[j:pos].strip()


def scan_text(text, methods, engine_patterns):
    """[{line, method, classes, kind, why, call, function, triggers}] of the hazardous calls in one Lua file."""
    f = _LuaFile(text)
    code = f.code
    hits = []
    for m in _LUA_MEMBER.finditer(code):
        sep, name = m.group(1), m.group(2)
        if name not in methods or (sep == '.' and m.start() > 0 and code[m.start() - 1] == '.'):
            continue
        recv = _receiver(code, m.start())
        nxt = code[m.end():m.end() + 40].lstrip()[:1]
        is_call = nxt in ('(', '"', "'", '{')
        if sep == '.':
            entries = [e for e in methods[name] if e['class'] == recv.split('.')[-1]]
        else:
            if not is_call or recv.startswith('Controls') or '.Controls' in recv:
                continue
            entries = [e for e in methods[name] if e['class'] not in _STATIC and e['class'] != 'engine']
        if not entries:
            continue
        func, triggers = f.context(m.start())
        hits.append(dict(line=f.line_of(m.start(2)), method=name, classes=sorted({e['class'] for e in entries}),
                         kind=_worst(entries), why='; '.join(sorted({e['class'] + ': ' + e['why'] for e in entries})),
                         call=recv + sep + name + ('(' if is_call else ' (reference)'), function=func,
                         triggers=triggers))
    for pat, why in engine_patterns:
        for m in pat.finditer(code):
            func, triggers = f.context(m.start())
            hits.append(dict(line=f.line_of(m.start()), method=m.group(1), classes=['engine'], kind='engine', why=why,
                             call=m.group(0).rstrip('( '), function=func, triggers=triggers))
    hits.sort(key=lambda h: (h['line'], h['method']))
    return hits


_RANK = {'curated': 0, 'writes': 1, 'engine': 2, 'cache': 3}


def _worst(entries):
    return min((e['kind'] for e in entries), key=lambda k: _RANK.get(k, 9))


# ---------------------------------------------------------------------------------------------------------------
# Files and profiles
# ---------------------------------------------------------------------------------------------------------------
def files_from_report(report):
    """[(name, path, kind, source)] of the UI Lua a host run loaded (host-report.json)."""
    doc = json.loads(Path(report).read_text(encoding='utf-8'))
    seen, out = set(), []
    for c in doc.get('addins', {}).get('contexts', []):
        p = c.get('path')
        if p and p.lower().endswith('.lua') and p not in seen:
            seen.add(p)
            out.append((Path(p).name, p, 'addin', c.get('mod', '')))
    ui = doc.get('uiFiles', {})
    for f in ui.get('unknown', []) + ui.get('knownFiles', []):
        p = f.get('path')
        if p and p.lower().endswith('.lua') and p not in seen:
            seen.add(p)
            out.append((f.get('name') or Path(p).name, p, f.get('kind', ''), f.get('source', '')))
    selected = None
    if 'profiles' in doc:
        selected = [s['name'] for s in doc['profiles'].get('selected', [])]
    return out, selected


def files_from_paths(paths):
    out = []
    for p in paths:
        p = Path(p)
        items = sorted(p.rglob('*.lua')) if p.is_dir() else [p]
        for f in items:
            out.append((f.name, str(f), 'path', ''))
    return out


def load_covers(profiles_dir, selected=None):
    """{file name (lower case): [(profile, methods or None)]} from the profiles' manifests."""
    covers = defaultdict(list)
    root = Path(profiles_dir)
    if not root.is_dir():
        return covers
    for manifest in sorted(root.glob('*/profile.json')):
        doc = json.loads(manifest.read_text(encoding='utf-8'))
        name = doc.get('name', manifest.parent.name)
        if selected is not None and name not in selected:
            continue
        for c in doc.get('covers', []):
            covers[c['file'].lower()].append((name, c.get('methods')))
    return covers


def default_profiles_dir():
    for base in (Path(__file__).resolve().parents[2], Path.cwd()):
        if (base / 'profiles').is_dir():
            return base / 'profiles'
    return None


def scan(files, methods, curated, covers):
    engine = [(re.compile(e['pattern']), e['why']) for e in curated.get('engine', [])]
    hits, scanned = [], []
    for name, path, kind, source in files:
        try:
            text = Path(path).read_text(encoding='utf-8', errors='replace')
        except OSError as e:
            scanned.append(dict(file=name, path=path, kind=kind, source=source, error=str(e)))
            continue
        found = scan_text(text, methods, engine)
        scanned.append(dict(file=name, path=path, kind=kind, source=source, hits=len(found)))
        for h in found:
            profile = None
            for prof, ms in covers.get(name.lower(), []):
                if ms is None or h['method'] in ms:
                    profile = prof
                    break
            hits.append(dict(file=name, path=path, **h, covered=profile is not None, profile=profile))
    return scanned, hits


def summarize(hits):
    by_kind = defaultdict(int)
    uncovered = defaultdict(int)
    for h in hits:
        by_kind[h['kind']] += 1
        if not h['covered']:
            uncovered[h['method']] += 1
    return dict(hits=len(hits), byKind=dict(sorted(by_kind.items())), covered=sum(h['covered'] for h in hits),
                uncoveredByMethod=dict(sorted(uncovered.items(), key=lambda kv: (-kv[1], kv[0]))))


def cmd_scan(a):
    files, selected = [], None
    if a.report:
        files, selected = files_from_report(a.report)
    files += files_from_paths(a.paths)
    if not files:
        print('nothing to scan: give --report or paths')
        return 2
    methods, source, curated = load_methods(a.dll_source)
    if not a.all:
        methods = {k: [e for e in v if e['kind'] != 'cache'] or v for k, v in methods.items()}
        methods = {k: v for k, v in methods.items() if any(e['kind'] != 'cache' for e in v)}
    profiles = Path(a.profiles) if a.profiles else default_profiles_dir()
    covers = load_covers(profiles, selected) if profiles else {}
    scanned, hits = scan(files, methods, curated, covers)
    doc = dict(format=FORMAT, methods=dict(source=source, cacheIncluded=bool(a.all)),
               profiles=dict(dir=str(profiles) if profiles else None, selectedOnly=selected is not None),
               files=scanned, hits=hits, summary=summarize(hits))
    if a.json:
        Path(a.json).write_text(json.dumps(doc, indent=1) + '\n', encoding='utf-8')
    for h in hits:
        if h['covered'] and not a.verbose:
            continue
        print(f"{h['file']}:{h['line']}: {h['call']} [{h['kind']}] {h['function'] or 'top level'}"
              + (f" ({', '.join(h['triggers'])})" if h['triggers'] else '')
              + (f" covered by {h['profile']}" if h['covered'] else ''))
    s = doc['summary']
    print(f"{len(scanned)} files, {s['hits']} hazardous calls ({s['covered']} covered by profiles); "
          + ', '.join(f'{k} {v}' for k, v in s['byKind'].items()))
    return 0


def merge_methods(derived):
    """Union of several derive_methods results ({label: result}): writes wins over cache; 'in' lists the labels."""
    out = defaultdict(dict)
    for label, result in derived.items():
        for cls, methods in result.items():
            for name, info in methods.items():
                cur = out[cls].get(name)
                if cur is None or (cur['kind'] == 'cache' and info['kind'] == 'writes'):
                    out[cls][name] = dict(info, **{'in': (cur or {}).get('in', []) + [label]})
                else:
                    cur['in'].append(label)
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def cmd_methods(a):
    labels = a.label or []
    labels += [Path(d).name for d in a.dll_source[len(labels):]]
    harmless = harmless_caches(load_curated())
    derived = merge_methods({label: derive_methods(d, harmless=harmless) for label, d in zip(labels, a.dll_source)})
    counts = {k: sum(1 for v in derived.values() for i in v.values() if i['kind'] == k) for k in ('writes', 'cache')}
    doc = dict(about='Lua methods of the DLL that change game state (python -m civ5headless.hazards methods); '
               'writes: the binding calls a mutating method; cache: it reaches a lazy cache.',
               source=' + '.join(labels), counts=counts, classes=derived)
    text = json.dumps(doc, indent=1) + '\n'
    if a.json:
        Path(a.json).write_text(text, encoding='utf-8')
    else:
        sys.stdout.write(text)
    print(f'{counts}', file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m civ5headless.hazards', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scan', help='scan UI Lua for state-changing DLL calls')
    s.add_argument('paths', nargs='*', help='Lua files or folders')
    s.add_argument('--report', help='host-report.json of a run: scan the add-ins and UI files it loaded')
    s.add_argument('--dll-source', help='CvGameCoreDLL_Expansion2 folder: derive the methods from its Lua bindings')
    s.add_argument('--profiles', help='profiles folder (default: the repository\'s profiles/)')
    s.add_argument('--all', action='store_true', help='also report calls that only reach a lazy cache (kind cache)')
    s.add_argument('--verbose', '-v', action='store_true', help='also print calls covered by a profile')
    s.add_argument('--json', help='write the full result here')
    m = sub.add_parser('methods', help='derive the state-changing methods from DLL sources')
    m.add_argument('--dll-source', required=True, action='append', help='repeatable: the union is written')
    m.add_argument('--label', action='append', help='a label per --dll-source, written into the output')
    m.add_argument('--json', help='output file (default: standard output)')
    a = ap.parse_args(argv)
    return cmd_scan(a) if a.cmd == 'scan' else cmd_methods(a)


if __name__ == '__main__':
    sys.exit(main())

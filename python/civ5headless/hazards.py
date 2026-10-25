"""UI hazard scan: calls in UI Lua (InGameUIAddins, UI overrides) to DLL Lua methods that change game state.

  python -m civ5headless.hazards scan [--report RUN/host-report.json] [PATH ...] [--dll-source DIR] [--profiles DIR]
                                      [--json OUT] [--all]
  python -m civ5headless.hazards methods --dll-source DIR [--label TEXT] [--json OUT]
  python -m civ5headless.hazards known --report RUN/host-report.json --note TEXT [--write]

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
import hashlib
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
        if entry.get('notWithDll'):
            by_name[entry['name']][-1].update(notWithDll=entry['notWithDll'], notWithDllWhy=entry.get('notWithDllWhy', ''))
    for entry in curated.get('writesWithArgs', []):
        for e in by_name.get(entry['name'], []):
            if e['class'] == entry['class']:
                e.update(minArgs=entry['minArgs'], argsWhy=entry['why'])
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


_LUA_KEYWORDS = {'and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for', 'function', 'if', 'in', 'local', 'nil',
                 'not', 'or', 'repeat', 'return', 'then', 'true', 'until', 'while'}
_STOP_WORDS = _LUA_KEYWORDS - {'and', 'or', 'not', 'nil', 'true', 'false', 'function'}
# Callees that call a function passed to them before they return: that function runs when its enclosing one runs.
_IMMEDIATE = {'pcall', 'xpcall', 'sort', 'gsub'}
# Functions that only look at a value: passing a function to them does not run it.
_INSPECT = {'type', 'tostring', 'print', 'assert', 'rawequal'}


def _enclosing_call(code, pos, limit=2000):
    """The callee of the call whose argument list holds pos ('Foo' for 'Foo(a, <pos>'), or None: a table
    constructor, an index, an assignment or a statement keyword comes first."""
    depth, j, stop = 0, pos, max(0, pos - limit)
    while j > stop:
        j -= 1
        c = code[j]
        if c in ')]}':
            depth += 1
        elif c in '([{':
            if depth:
                depth -= 1
            elif c != '(':
                return None
            else:
                m = re.search(r'([\w.:\[\]]+)\s*$', code[max(0, j - 200):j])
                return m.group(1) if m and m.group(1) not in _LUA_KEYWORDS else None
        elif depth == 0:
            if c == '=' and code[j - 1] not in '=~<>' and code[j + 1] != '=':
                return None
            if c.isalnum() or c == '_':
                k = j
                while k > 0 and (code[k - 1].isalnum() or code[k - 1] == '_'):
                    k -= 1
                if code[k:j + 1] in _STOP_WORDS and (k == 0 or code[k - 1] not in '.:'):
                    return None
                j = k
    return None


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
        self.memo = {}

    def line_of(self, pos):
        lo, hi = 0, len(self.line_starts)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid
        return lo + 1

    def context(self, pos, depth=3):
        """(enclosing function names, triggers). Triggers: 'load' at top level; else how the innermost function runs:
        registrations (Events.X.Add, control callbacks, ContextPtr handlers); calls from another function ('via' its
        triggers, depth levels); passed as a value ('passed to' the callee, or 'via' the callee's triggers when the
        callee is a function of the file); stored ('assigned to' a handler table entry, a table key such as
        [Mouse.eLClick], a named field). A function passed to pcall, xpcall, sort or gsub runs with its enclosing
        one. No trigger found: []."""
        inner = sorted((s for s in self.spans if s[0] <= pos < s[1]), key=lambda s: s[0])
        if not inner:
            return '', ['load']
        names = [s[2] or '<anonymous>' for s in reversed(inner)]
        for start, end, name, before in reversed(inner):
            found, outward = self._triggers(start, name, before, depth)
            if found or not outward:
                return ' < '.join(names), found
        return ' < '.join(names), []

    def _triggers(self, start, name, before, depth):
        """(triggers of one function, whether it runs as part of its enclosing function)."""
        key = (start, depth)
        if key not in self.memo:
            self.memo[key] = ([], False)  # a use inside its own chain adds nothing
            self.memo[key] = self._find_triggers(start, name, before, depth)
        return self.memo[key]

    def _find_triggers(self, start, name, before, depth):
        found = _registrations(self.code, name, before)
        if found:
            return found, False
        if name:
            field = bool(re.search(r'[{,]\s*\w+\s*=\s*$', before))
            found = self._uses(name, start, depth, field or '.' in name or ':' in name)
            if not found and ('.' in name or ':' in name):
                found = ['assigned to ' + name]
            return found, False
        a = re.search(r'((?:[\w.]*)(?:\[[^\[\]\n]*\])+)\s*=\s*$', before)
        if a:
            target = a.group(1)
            base = re.match(r'[\w.]*', target).group(0)
            if not _INPUT_ASSIGNED.search(target) and base:
                found = self._table_calls(base, depth)
            return found or ['assigned to ' + target], False
        callee = _enclosing_call(self.code, start)
        if callee:
            if re.split(r'[.:]', callee)[-1] in _IMMEDIATE:
                return [], True
            return self._passed(callee, depth), False
        return [], False

    def _via(self, pos, depth):
        if depth <= 0:
            return []
        _, t = self.context(pos, depth - 1)
        return [x if x.startswith(('via ', 'passed to ', 'assigned to ')) else 'via ' + x for x in t]

    def _passed(self, callee, depth):
        """A function passed to callee: 'via' the callee's triggers when the file defines it (and its name is not that
        of a callback registration such as AddButton), else 'passed to'."""
        if _INPUT_PASSED.search(callee):
            return ['passed to ' + callee]
        for start, end, name, before in self.spans:
            if name and name == callee:
                t, _ = self._triggers(start, name, before, depth - 1) if depth > 0 else ([], False)
                return [x if x.startswith(('via ', 'passed to ', 'assigned to ')) else 'via ' + x for x in t]
        return ['passed to ' + callee]

    def _table_calls(self, base, depth):
        """Triggers of the calls of a function stored in a table entry: base[...](...)."""
        found = set()
        for m in re.finditer(r'(?<![\w.:])%s\s*\[[^\[\]\n]*\]\s*\(' % re.escape(base), self.code):
            found.update(self._via(m.start(), depth))
        return sorted(found)

    def _uses(self, name, def_start, depth, qualified=False):
        """Triggers from the uses of a named function: calls, values passed or stored. qualified (a table field or a
        dotted name): uses as t.name / t:name count too."""
        short = name.split('.')[-1].split(':')[-1]
        found = set()
        pattern = r'(?<![\w])%s\b' if qualified else r'(?<![\w.:])%s\b'
        for m in re.finditer(pattern % re.escape(short), self.code):
            if def_start <= m.start() < def_start + 12 + len(name):
                continue  # the definition
            head = self.code[self.code.rfind('\n', 0, m.start()) + 1:m.start()]
            if re.search(r'function\s*[\w.:]*$', head) or re.search(r'local\s+$', head):
                continue
            tail = self.code[m.end():m.end() + 40].lstrip()[:1]
            if tail == '(':
                found.update(self._via(m.start(), depth))
            elif tail != '=':
                callee = _enclosing_call(self.code, m.start())
                if callee in _INSPECT:
                    continue
                if callee:
                    if re.split(r'[.:]', callee)[-1] in _IMMEDIATE:
                        found.update(self._via(m.start(), depth))
                    else:
                        found.update(self._passed(callee, depth))
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


def _call_args(code, pos):
    """The number of arguments of the call whose name ends at pos, or None when it cannot tell."""
    j = pos
    while j < len(code) and code[j] in ' \t\r\n':
        j += 1
    if j >= len(code) or code[j] != '(':
        return 1 if j < len(code) and code[j] in '"\'{' else None
    depth, count, empty = 0, 0, True
    for k in range(j + 1, min(len(code), j + 2000)):
        c = code[k]
        if c in '([{':
            depth += 1
        elif c in ')]}':
            if depth == 0:
                return 0 if empty else count + 1
            depth -= 1
        elif c == ',' and depth == 0:
            count += 1
        if not c.isspace():
            empty = False
    return None


def scan_text(text, methods, engine_patterns, lua_events=None):
    """[{line, method, classes, kind, why, call, function, triggers, reach}] of the hazardous calls in one Lua file
    (text, or a parsed _LuaFile). lua_events: see reach."""
    f = text if isinstance(text, _LuaFile) else _LuaFile(text)
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
        if is_call and all(e.get('minArgs') for e in entries):
            n = _call_args(code, m.end())
            if n is not None and n < min(e['minArgs'] for e in entries):
                continue  # writes only with more arguments (writesWithArgs)
        func, triggers = f.context(m.start())
        hits.append(dict(line=f.line_of(m.start(2)), method=name, classes=sorted({e['class'] for e in entries}),
                         kind=_worst(entries), why='; '.join(sorted({e['class'] + ': ' + e['why'] for e in entries})),
                         call=recv + sep + name + ('(' if is_call else ' (reference)'), function=func,
                         triggers=triggers, reach=reach(triggers, lua_events)))
    for pat, why in engine_patterns:
        for m in pat.finditer(code):
            func, triggers = f.context(m.start())
            hits.append(dict(line=f.line_of(m.start()), method=m.group(1), classes=['engine'], kind='engine', why=why,
                             call=m.group(0).rstrip('( '), function=func, triggers=triggers,
                             reach=reach(triggers, lua_events)))
    hits.sort(key=lambda h: (h['line'], h['method']))
    return hits


# Reach: whether a call can run in an autoplayed game. 'load' (the file's top level, or a function it calls),
# 'game' (game or UI events, per-frame updates, show/hide, anything not known to be input) or 'input' (only player
# input: control callbacks, input handlers, tooltips, popup buttons, mouse and key handlers).
_INPUT_PASSED = re.compile(r'Register\w*Callback|RegisterCheckHandler|SetToolTipCallback|ToolTip|AddButton|CommitConfirm|'
                           r'SetInputHandler|SetVoid\d', re.I)
_INPUT_ASSIGNED = re.compile(r'MouseEvents\.|KeyEvents\.|\bMouse\.|InterfaceModeMessageHandler|ToolTip|Callback', re.I)
# Engine events that only follow player input: hovering, the Civilopedia, keys, opening and closing the city screen.
_INPUT_EVENTS = {'SerialEventMouseOverHex', 'SearchForPediaEntry', 'GoToPediaHomePage', 'KeyUpEvent', 'KeyDownEvent',
                 'SerialEventEnterCityScreen', 'SerialEventExitCityScreen'}
_LUA_EVENT_USE = re.compile(r'\bLuaEvents\s*\.\s*(\w+)\s*([(.]?)')


def trigger_reach(trigger, lua_events=None):
    """The reach of one trigger (see reach). lua_events: {LuaEvents name: reach of the places that fire it}."""
    t = trigger or ''
    while t.startswith('via '):
        t = t[4:]
    if t == 'load':
        return 'load'
    if t.startswith('callback ') or t == 'ContextPtr:SetInputHandler':
        return 'input'
    if t.startswith('passed to '):
        return 'input' if _INPUT_PASSED.search(t) else 'game'
    if t.startswith('assigned to '):
        return 'input' if _INPUT_ASSIGNED.search(t) else 'game'
    if t.startswith(('Events.', 'LuaEvents.')) and t.split('.', 1)[1] in _INPUT_EVENTS:
        return 'input'
    if t.startswith('LuaEvents.') and lua_events and lua_events.get(t.split('.', 1)[1]) == 'input':
        return 'input'
    return 'game'


def reach(triggers, lua_events=None):
    """'load' when any trigger is the file's load, else 'game' when any can come from the game (or none was found),
    else 'input' (every trigger is player input). A LuaEvents listener is input when every place that fires the
    event (lua_events, from the scanned files) is input."""
    found = {trigger_reach(t, lua_events) for t in triggers or [] if t}
    if not found:
        return 'game'
    for r in ('load', 'game'):
        if r in found:
            return r
    return 'input'


def lua_event_reach(texts, passes=2):
    """{LuaEvents name: 'input' or 'game'} over Lua files (texts): 'input' when every place that fires the event
    (LuaEvents.X(...)) is reached only through player input. Events fired nowhere in texts are left out (unknown)."""
    files = [_LuaFile(t) if isinstance(t, str) else t for t in texts]
    sites = []
    for f in files:
        for m in _LUA_EVENT_USE.finditer(f.code):
            if m.group(2) == '(':  # fired here
                sites.append((m.group(1), f.context(m.start())[1]))
                continue
            if m.group(2) == '.':  # .Add, .Remove
                continue
            # the event as a value: a handler (InterfaceModeMessageHandler[...][...] = LuaEvents.X) or an argument
            head = f.code[f.code.rfind('\n', 0, m.start()) + 1:m.start()]
            a = re.search(r'([\w.\[\]]+)\s*=\s*$', head)
            callee = None if a else _enclosing_call(f.code, m.start())
            sites.append((m.group(1), ['assigned to ' + a.group(1)] if a else ['passed to ' + callee] if callee else []))
    out = {}
    for _ in range(passes):
        cur = defaultdict(set)
        for name, triggers in sites:
            cur[name].add(reach(triggers, out))
        out = {name: 'input' if r == {'input'} else 'game' for name, r in cur.items()}
    return out


_RANK = {'curated': 0, 'writes': 1, 'engine': 2, 'cache': 3}


def _worst(entries):
    return min((e['kind'] for e in entries), key=lambda k: _RANK.get(k, 9))


# ---------------------------------------------------------------------------------------------------------------
# Files and profiles
# ---------------------------------------------------------------------------------------------------------------
def files_from_report(report, unknown_only=False):
    """[(name, path, kind, source)] of the UI Lua a host run loaded (host-report.json): every add-in context and UI
    file, or with unknown_only the UI files the run reported as unknown (not in the known list nor covered)."""
    doc = json.loads(Path(report).read_text(encoding='utf-8'))
    seen, out = set(), []
    ui = doc.get('uiFiles', {})
    unknown = {f.get('path') for f in ui.get('unknown', [])}
    for c in doc.get('addins', {}).get('contexts', []):
        p = c.get('path')
        if p and p.lower().endswith('.lua') and p not in seen and (not unknown_only or p in unknown):
            seen.add(p)
            out.append((Path(p).name, p, 'addin', c.get('mod', '')))
    for f in ui.get('unknown', []) + ([] if unknown_only else ui.get('knownFiles', [])):
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


def _review(reviews, name, sha, h):
    """The first curated review (lua-hazards.json reviews) that matches a hit, or None."""
    for r in reviews:
        if r['file'].lower() != name.lower():
            continue
        if r.get('sha256') and sha not in {s.upper() for s in r['sha256']}:
            continue
        if r.get('methods') and h['method'] not in r['methods']:
            continue
        if r.get('function') and not re.search(r['function'], h['function'] or ''):
            continue
        if r.get('lines') and h['line'] not in r['lines']:
            continue
        return r
    return None


# UI events the host fires itself (docs/engine-contract.md 10.6); GameEvents come from the DLL.
_HOST_EVENTS = {'Events.SequenceGameInitComplete', 'Events.LoadScreenClose'}
HOST_RUN_WHY = ('add-in the host runs: its load, GameEvents listeners and SequenceGameInitComplete/LoadScreenClose '
                'listeners run in the host as in the game')


def _host_runs(trigger):
    t = trigger
    while t.startswith('via '):
        t = t[4:]
    return t == 'load' or t.startswith('GameEvents.') or t in _HOST_EVENTS


def _dll_fixed(methods, h, dll):
    """The reason a hit's method does not change state with the run's DLL (curated notWithDll), or None."""
    entries = [e for e in methods.get(h['method'], []) if e['class'] in h['classes']]
    if not dll or not entries:
        return None
    for e in entries:
        cond = e.get('notWithDll')
        if not cond or any(dll.get(k) != v for k, v in cond.items()):
            return None
    return '; '.join(sorted({e['notWithDllWhy'] for e in entries}))


def scan(files, methods, curated, covers, report=None):
    """(scanned files, hits). Each hit adds to scan_text's fields: file, path, sha256; covered, coveredBy and reason
    (profile: a selected profile emulates the call, named in profile; review: a curated review; dll: the run's DLL
    does not change state in this method; host: an add-in the host runs, reached only from its load, GameEvents or
    the UI events the host fires); review (a curated review's verdict and why: verdict input sets reach to input,
    covered covers the hit). report (a host-report.json document) enables the dll and host rules."""
    engine = [(re.compile(e['pattern']), e['why']) for e in curated.get('engine', [])]
    reviews = curated.get('reviews', [])
    dll = (report or {}).get('dll') or {}
    host_run = {c.get('path') for c in (report or {}).get('addins', {}).get('contexts', []) if c.get('status') == 'run'}
    hits, scanned, parsed = [], [], []
    for name, path, kind, source in files:
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            scanned.append(dict(file=name, path=path, kind=kind, source=source, error=str(e)))
            continue
        parsed.append((name, path, kind, source, hashlib.sha256(data).hexdigest().upper(),
                       _LuaFile(data.decode('utf-8', errors='replace'))))
    lua_events = lua_event_reach([p[5] for p in parsed])
    for name, path, kind, source, sha, f in parsed:
        found = scan_text(f, methods, engine, lua_events)
        scanned.append(dict(file=name, path=path, kind=kind, source=source, sha256=sha, hits=len(found)))
        for h in found:
            hit = dict(file=name, path=path, sha256=sha, **h, covered=False, profile=None, coveredBy=None, reason=None)
            for prof, ms in covers.get(name.lower(), []):
                if ms is None or h['method'] in ms:
                    hit.update(covered=True, profile=prof, coveredBy='profile', reason=f'profile {prof} emulates it')
                    break
            r = _review(reviews, name, sha, h)
            if r:
                hit['review'] = dict(verdict=r['verdict'], why=r['why'])
                if r['verdict'] == 'input':
                    hit['reach'] = 'input'
                elif r['verdict'] == 'covered' and not hit['covered']:
                    hit.update(covered=True, coveredBy='review', reason=r['why'])
            if not hit['covered']:
                why = _dll_fixed(methods, h, dll)
                if why:
                    hit.update(covered=True, coveredBy='dll', reason=why)
            if not hit['covered'] and path in host_run and any(_host_runs(t) for t in h['triggers']) \
                    and all(_host_runs(t) or trigger_reach(t, lua_events) == 'input' for t in h['triggers']):
                hit.update(covered=True, coveredBy='host', reason=HOST_RUN_WHY)
            hits.append(hit)
    return scanned, hits


def _methods_for(dll_source=None, include_cache=False):
    methods, source, curated = load_methods(dll_source)
    if not include_cache:
        methods = {k: [e for e in v if e['kind'] != 'cache'] for k, v in methods.items()}
        methods = {k: v for k, v in methods.items() if v}
    return methods, source, curated


def scan_report(report_path, unknown_only=False, profiles_dir=None, include_cache=False, dll_source=None):
    """The hits over the UI Lua a host run loaded (host-report.json), as `scan --report` finds them: state-writing
    calls (lazy caches only with include_cache), each with reach, covered, coveredBy and reason from the profiles
    that run selected (from profiles_dir, else the folder the run used, else the repository's profiles/), the curated
    reviews, the run's DLL and the add-ins the host ran. One entry point for other tools (c5h verify)."""
    doc = json.loads(Path(report_path).read_text(encoding='utf-8'))
    files, selected = files_from_report(report_path, unknown_only)
    methods, _, curated = _methods_for(dll_source, include_cache)
    used = (doc.get('profiles') or {}).get('dir')
    profiles = Path(profiles_dir) if profiles_dir else Path(used) if used and Path(used).is_dir() else default_profiles_dir()
    covers = load_covers(profiles, selected) if profiles else {}
    return scan(files, methods, curated, covers, report=doc)[1]


def summarize(hits):
    by_kind, uncovered, covered_by, reach_open = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    for h in hits:
        by_kind[h['kind']] += 1
        if h['covered']:
            covered_by[h.get('coveredBy') or 'profile'] += 1
        else:
            uncovered[h['method']] += 1
            reach_open[h.get('reach', 'game')] += 1
    return dict(hits=len(hits), byKind=dict(sorted(by_kind.items())), covered=sum(h['covered'] for h in hits),
                coveredBy=dict(sorted(covered_by.items())), uncoveredByReach=dict(sorted(reach_open.items())),
                uncoveredByMethod=dict(sorted(uncovered.items(), key=lambda kv: (-kv[1], kv[0]))))


def cmd_scan(a):
    files, selected, report = [], None, None
    if a.report:
        files, selected = files_from_report(a.report, a.unknown_only)
        report = json.loads(Path(a.report).read_text(encoding='utf-8'))
    files += files_from_paths(a.paths)
    if not files:
        print('nothing to scan: give --report or paths')
        return 2
    methods, source, curated = _methods_for(a.dll_source, a.all)
    profiles = Path(a.profiles) if a.profiles else default_profiles_dir()
    covers = load_covers(profiles, selected) if profiles else {}
    scanned, hits = scan(files, methods, curated, covers, report=report)
    doc = dict(format=FORMAT, methods=dict(source=source, cacheIncluded=bool(a.all)),
               profiles=dict(dir=str(profiles) if profiles else None, selectedOnly=selected is not None),
               files=scanned, hits=hits, summary=summarize(hits))
    if a.json:
        Path(a.json).write_text(json.dumps(doc, indent=1) + '\n', encoding='utf-8')
    for h in hits:
        if (h['covered'] or h['reach'] == 'input') and not a.verbose:
            continue
        print(f"{h['file']}:{h['line']}: {h['call']} [{h['kind']}, {h['reach']}] {h['function'] or 'top level'}"
              + (f" ({', '.join(h['triggers'])})" if h['triggers'] else '')
              + (f" covered ({h['coveredBy']}): {h['reason']}" if h['covered'] else '')
              + (f" review: {h['review']['why']}" if h.get('review') and not h['covered'] else ''))
    s = doc['summary']
    print(f"{len(scanned)} files, {s['hits']} hazardous calls ({s['covered']} covered: "
          + ', '.join(f'{k} {v}' for k, v in s['coveredBy'].items()) + '; uncovered by reach: '
          + ', '.join(f'{k} {v}' for k, v in s['uncoveredByReach'].items()) + '); '
          + ', '.join(f'{k} {v}' for k, v in s['byKind'].items()) + ('' if a.verbose else ' (-v lists input-only and covered calls)'))
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


def cmd_known(a):
    """Add a run's unknown UI files to the known list (profiles/known-ui-files.json), each with a note and its
    hazard scan summary."""
    doc = json.loads(Path(a.report).read_text(encoding='utf-8'))
    unknown = [f for f in doc.get('uiFiles', {}).get('unknown', []) if f.get('sha256')]
    known_path = Path(a.known) if a.known else (default_profiles_dir() or Path('profiles')) / 'known-ui-files.json'
    known = json.loads(known_path.read_text(encoding='utf-8'))
    have = {(e['name'].lower(), e['sha256'].upper()) for e in known.get('files', [])}
    methods, _, curated = load_methods(None)
    methods = {k: v for k, v in methods.items() if any(e['kind'] != 'cache' for e in v)}
    added = []
    for f in unknown:
        key = (f['name'].lower(), f['sha256'].upper())
        if key in have:
            continue
        have.add(key)
        summary = 'not a Lua file'
        if f.get('path', '').lower().endswith('.lua') and Path(f['path']).is_file():
            _, hits = scan([(f['name'], f['path'], f.get('kind', ''), f.get('source', ''))], methods, curated, {})
            kinds = defaultdict(int)
            for h in hits:
                kinds[h['kind']] += 1
            summary = ('hazard scan: ' + (f"{len(hits)} calls ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))})"
                                          if hits else 'none'))
        added.append(dict(name=f['name'], sha256=f['sha256'].upper(), source=f.get('source', ''),
                          note=f'{a.note}; {summary}'))
    known['files'] = sorted(known.get('files', []) + added, key=lambda e: (e['name'].lower(), e.get('source', '')))
    for e in added:
        print(f"{e['name']:40} {e['source']:45} {e['note']}")
    print(f'{len(added)} files to add to {known_path}' + ('' if a.write else ' (dry run: --write writes them)'))
    if a.write:
        known_path.write_text(json.dumps(known, indent=1) + '\n', encoding='utf-8')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m civ5headless.hazards', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scan', help='scan UI Lua for state-changing DLL calls')
    s.add_argument('paths', nargs='*', help='Lua files or folders')
    s.add_argument('--report', help='host-report.json of a run: scan the add-ins and UI files it loaded')
    s.add_argument('--unknown-only', action='store_true', help='with --report: only the UI files the run reported as unknown')
    s.add_argument('--dll-source', help='CvGameCoreDLL_Expansion2 folder: derive the methods from its Lua bindings')
    s.add_argument('--profiles', help='profiles folder (default: the repository\'s profiles/)')
    s.add_argument('--all', action='store_true', help='also report calls that only reach a lazy cache (kind cache)')
    s.add_argument('--verbose', '-v', action='store_true', help='also print calls covered by a profile')
    s.add_argument('--json', help='write the full result here')
    m = sub.add_parser('methods', help='derive the state-changing methods from DLL sources')
    m.add_argument('--dll-source', required=True, action='append', help='repeatable: the union is written')
    m.add_argument('--label', action='append', help='a label per --dll-source, written into the output')
    m.add_argument('--json', help='output file (default: standard output)')
    k = sub.add_parser('known', help='add the unknown UI files of a run to the known list (reviewed or verified)')
    k.add_argument('--report', required=True, help='host-report.json of the run')
    k.add_argument('--note', required=True, help='why these files need no profile (for example how they were verified)')
    k.add_argument('--known', help='known list (default: profiles/known-ui-files.json of the repository)')
    k.add_argument('--write', action='store_true', help='write the list (default: dry run)')
    a = ap.parse_args(argv)
    return {'scan': cmd_scan, 'methods': cmd_methods, 'known': cmd_known}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())

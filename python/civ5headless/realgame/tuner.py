"""FireTuner client: run Lua in the real game's UI contexts through its debug port.

  python -m civ5headless.realgame.tuner serve [--game-port 4318] [--wait 90]
  python -m civ5headless.realgame.tuner states | stop
  python -m civ5headless.realgame.tuner exec [--context InGame] (--code LUA | --file FILE.lua)

The game listens on 127.0.0.1:4318 when config.ini has `EnableTuner = 1`. Packets are a little-endian (length, id)
header and NUL-separated UTF-8 strings. `LSQ:` lists the Lua contexts (id, name pairs); `CMD:<context id>:<lua>` runs
a short console command in one; the game broadcasts print output with id 0xFFFFFFFF as "O" packets.

TunerConnection.execute(context, source) uploads source in 256-byte pieces into a global, then runs it through
tuner_result.lua, which returns the values as JSON printed in hex chunks behind a one-off marker. No GUI automation,
no game files, nothing but the standard library.

The real-game session (session.py) holds one connection for its whole life: repeated short-lived connections can
stall the game's tuner. `serve` does the same for manual use from other shells: one persistent connection behind a
local HTTP service with a bearer token, its port and token in a session file (default <runs>/tuner-session.json).
Commands are never retried after an ambiguous timeout.
"""
from __future__ import annotations

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid

GAME_PORT = 4318
MAX_PACKET = 524288  # receive limit of the game's tuner
MAX_SOURCE = 65536
MAX_RESULT = 262144
MAX_CONSOLE = 1400   # the game's console source buffer is much smaller than its packets
BROADCAST = 0xFFFFFFFF
RESULT_LUA = Path(__file__).resolve().parent / 'tuner_result.lua'


class TunerError(RuntimeError):
    pass


def encode_packet(text: str, ident: int) -> bytes:
    if '\0' in text:
        raise TunerError('NUL is not allowed in a protocol command')
    body = text.encode('utf-8') + b'\0'
    if len(body) > MAX_PACKET:
        raise TunerError('command exceeds the packet limit')
    return struct.pack('<II', len(body), ident) + body


def recv_exact(sock: socket.socket, count: int) -> bytes:
    parts = bytearray()
    while len(parts) < count:
        part = sock.recv(count - len(parts))
        if not part:
            raise TunerError('game disconnected')
        parts.extend(part)
    return bytes(parts)


def recv_packet(sock: socket.socket) -> tuple[int, list[str]]:
    size, ident = struct.unpack('<II', recv_exact(sock, 8))
    if not 1 <= size <= MAX_PACKET:
        raise TunerError(f'invalid packet size: {size}')
    data = recv_exact(sock, size)
    if not data.endswith(b'\0'):
        raise TunerError('packet is not NUL terminated')
    return ident, data[:-1].decode('utf-8', errors='replace').split('\0')


def parse_states(strings: list[str]) -> list[dict]:
    if len(strings) % 2:
        raise TunerError('malformed Lua context list')
    out = []
    for i in range(0, len(strings), 2):
        try:
            ident = int(strings[i])
        except ValueError as exc:
            raise TunerError('invalid Lua context id') from exc
        if not 0 <= ident <= 0xFFFFFFFF:
            raise TunerError('invalid Lua context id')
        out.append({'id': ident, 'name': strings[i + 1]})
    return out


def lua_string(text: str) -> str:
    """A Lua 5.1 string literal for any text (decimal byte escapes; Lua 5.1 has no Unicode escapes)."""
    return '"' + ''.join('\\%03d' % b for b in text.encode('utf-8')) + '"'


def wrap_lua(source: str, marker: str) -> str:
    """The result wrapper plus a call of it on source: one self-contained chunk (tests run it in Lua 5.1)."""
    if len(source.encode('utf-8')) > MAX_SOURCE:
        raise TunerError('Lua source exceeds 64 KiB')
    return RESULT_LUA.read_text(encoding='utf-8') + '\nCiv5StackAutomationRun(' + lua_string(source) + ',' + lua_string(marker) + ')'


def decode_result(chunks: list[str]) -> dict:
    parts = {}
    expected = None
    for chunk in chunks:
        header, hex_data = chunk.split(':', 1)
        index, total = map(int, header.split('/', 1))
        if not 1 <= index <= total <= (MAX_RESULT + 255) // 256 or index in parts:
            raise TunerError('invalid or duplicate result chunk')
        if expected is not None and total != expected:
            raise TunerError('inconsistent result chunk count')
        expected = total
        part = bytes.fromhex(hex_data)
        if not 1 <= len(part) <= 256:
            raise TunerError('invalid result chunk size')
        parts[index] = part
    if expected is None or len(parts) != expected:
        raise TunerError('incomplete Lua result')
    return json.loads(b''.join(parts[i] for i in range(1, expected + 1)).decode('utf-8'))


class TunerConnection:
    """One connection to the game's tuner; requests are serialised, replies matched by id."""

    def __init__(self, port: int = GAME_PORT, connect_timeout: float = 3):
        self.sock = socket.create_connection(('127.0.0.1', port), connect_timeout)
        self.sock.settimeout(None)
        self.condition = threading.Condition()
        self.serial = threading.Lock()
        self.next_id = 1
        self.pending_id = None
        self.reply = None
        self.output = deque(maxlen=128)
        self.output_bytes = 0
        self.output_dropped = 0
        self.marker = None
        self.structured = []
        self.initialized_contexts = set()
        self.error = None
        threading.Thread(target=self._reader, daemon=True).start()

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def _reader(self):
        try:
            while True:
                ident, strings = recv_packet(self.sock)
                with self.condition:
                    if ident == self.pending_id:
                        self.reply = strings
                    elif ident == BROADCAST and strings and strings[0] == 'O':
                        if self.pending_id is not None:
                            for text in strings[1:]:
                                size = len(text.encode('utf-8'))
                                if self.marker and self.marker in text:
                                    if len(self.structured) < (MAX_RESULT + 255) // 256 and size <= 1024:
                                        self.structured.append(text.split(self.marker, 1)[1])
                                    else:
                                        self.error = 'invalid or duplicate Lua result'
                                elif len(self.output) == self.output.maxlen or self.output_bytes + size > MAX_RESULT:
                                    self.output_dropped += 1
                                else:
                                    self.output.append(text)
                                    self.output_bytes += size
                    elif ident == BROADCAST and strings == ['Closing']:
                        raise TunerError('the game is closing')
                    self.condition.notify_all()
        except (OSError, TunerError) as exc:
            with self.condition:
                self.error = str(exc)
                self.condition.notify_all()

    def request(self, command: str, timeout: float = 15, marker=None) -> dict:
        with self.serial:
            with self.condition:
                if self.error:
                    raise TunerError(self.error)
                ident = self.next_id
                self.next_id += 1
                self.pending_id = ident
                self.reply = None
                self.output.clear()
                self.structured.clear()
                self.marker = marker
                self.output_bytes = self.output_dropped = 0
                self.sock.sendall(encode_packet(command, ident))
                deadline = time.monotonic() + timeout
                while self.reply is None and not self.error:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.error = 'the game did not reply in time; the outcome is unknown and the command was not retried'
                        self.close()
                        break
                    self.condition.wait(remaining)
                self.pending_id = None
                if self.error and self.reply is None:
                    raise TunerError(self.error)
                return {'reply': self.reply, 'output': list(self.output), 'output_dropped': self.output_dropped,
                        'structured': list(self.structured)}

    def states(self, timeout=15):
        return parse_states(self.request('LSQ:', timeout)['reply'])

    def execute(self, context: str, source: str, timeout=15):
        """Run source in the named context: {ok, values | error, context, output, output_dropped}."""
        deadline = time.monotonic() + timeout

        def budget():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TunerError('the command budget expired before the next request')
            return remaining
        if len(source.encode('utf-8')) > MAX_SOURCE:
            raise TunerError('Lua source exceeds 64 KiB')
        found = [s for s in self.states(budget()) if s['name'] == context]
        if len(found) != 1:
            raise TunerError(f'expected one Lua context named {context!r}, found {len(found)}')
        marker = 'C5RESULT_' + uuid.uuid4().hex + ':'
        ident = found[0]['id']
        if ident not in self.initialized_contexts:
            self.upload(ident, RESULT_LUA.read_text(encoding='utf-8'), budget())
            self.raw(ident, "local f,e=loadstring(Civ5StackAutomationUpload,'Civ5AutomationResults');"
                            'Civ5StackAutomationUpload=nil;assert(f,e)()', budget())
            self.initialized_contexts.add(ident)
        self.upload(ident, source, budget())
        command = 'local s=Civ5StackAutomationUpload;Civ5StackAutomationUpload=nil;Civ5StackAutomationRun(s,' + lua_string(marker) + ')'
        result = self.raw(ident, command, budget(), marker)
        parsed = decode_result(result['structured'])
        parsed['context'] = found[0]
        parsed['output'] = [line for line in result['output'] if marker not in line]
        parsed['output_dropped'] = result['output_dropped']
        return parsed

    def raw(self, ident, code, timeout, marker=None):
        if len(code.encode('utf-8')) > MAX_CONSOLE:
            raise TunerError('console command exceeds its safe size')
        result = self.request(f'CMD:{ident}:{code}', timeout, marker)
        if any(value.startswith('ERR') for value in result['reply']):
            raise TunerError(f'the game rejected the Lua command: {result["reply"]!r}')
        return result

    def upload(self, ident, source, timeout):
        deadline = time.monotonic() + timeout
        self.raw(ident, "Civ5StackAutomationUpload=''", timeout)
        data = source.encode('utf-8')
        for offset in range(0, len(data), 256):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TunerError('the upload budget expired; the uploaded source was not run')
            chunk = '"' + ''.join('\\%03d' % b for b in data[offset:offset + 256]) + '"'
            self.raw(ident, 'Civ5StackAutomationUpload=Civ5StackAutomationUpload..' + chunk, remaining)


def connect(port=GAME_PORT, wait=90, alive=None):
    """Connect, retrying until wait seconds pass (alive(): False stops early, e.g. when the game exited)."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return TunerConnection(port)
        except OSError:
            if time.monotonic() >= deadline or (alive is not None and not alive()):
                raise
            time.sleep(1)


# ---- the persistent service (manual use) ----

def serve(session, game_port=GAME_PORT, port=0, wait=90):
    session = Path(session)
    if session.exists():
        raise TunerError(f'{session} exists: stop the previous service, or remove the stale file after checking its pid')
    token = secrets.token_urlsafe(32)
    connection = connect(game_port, wait)
    try:
        print(json.dumps({'connected': True, 'contexts': connection.states()}), flush=True)
    except Exception:
        connection.close()
        raise
    command_lock = threading.Lock()  # context lookup and execution are one transaction

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.headers.get('Authorization') != 'Bearer ' + token:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= MAX_PACKET:
                    raise TunerError('invalid request size')
                job = json.loads(self.rfile.read(length))
                if not isinstance(job, dict):
                    raise TunerError('expected a JSON request object')
                timeout = float(job.get('timeout', 15))
                if not 0 < timeout <= 120:
                    raise TunerError('timeout must be greater than zero and at most 120 seconds')
                if not command_lock.acquire(blocking=False):
                    raise TunerError('another command is running; this request was not queued or run')
                try:
                    if self.path == '/states':
                        result = {'ok': True, 'contexts': connection.states(timeout)}
                    elif self.path == '/exec':
                        if not isinstance(job.get('context'), str) or not isinstance(job.get('source'), str):
                            raise TunerError('context and source must be strings')
                        result = connection.execute(job['context'], job['source'], timeout)
                    elif self.path == '/stop':
                        result = {'ok': True, 'stopping': True}
                        threading.Thread(target=server.shutdown, daemon=True).start()
                    else:
                        raise TunerError('unknown endpoint')
                finally:
                    command_lock.release()
                payload = json.dumps(result, ensure_ascii=True).encode()
                self.send_response(200)
            except (TunerError, ValueError, KeyError, TypeError, OSError) as exc:
                payload = json.dumps({'ok': False, 'error': str(exc)}).encode()
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(json.dumps({'port': server.server_port, 'token': token, 'pid': os.getpid()}), encoding='utf-8')
    print(json.dumps({'ready': True, 'port': server.server_port, 'session': str(session)}), flush=True)
    try:
        server.serve_forever()
    finally:
        connection.close()
        server.server_close()
        session.unlink(missing_ok=True)


def call_service(session, endpoint, job, timeout=15):
    data = json.loads(Path(session).read_text(encoding='utf-8'))
    request = urllib.request.Request(f"http://127.0.0.1:{int(data['port'])}/{endpoint}", data=json.dumps(job).encode(),
                                     headers={'Authorization': 'Bearer ' + data['token'], 'Content-Type': 'application/json'})
    try:
        response = urllib.request.urlopen(request, timeout=timeout + 5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return json.load(response)


def main(argv=None, cfg=None):
    from .. import config
    cfg = cfg or config.load()
    p = argparse.ArgumentParser(prog='python -m civ5headless.realgame.tuner', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--session', type=Path, default=cfg.runs / 'tuner-session.json' if cfg.runs else None,
                   help='service session file (default: <runs>/tuner-session.json)')
    p.add_argument('--timeout', type=float, default=15)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('serve')
    s.add_argument('--port', type=int, default=0)
    s.add_argument('--game-port', type=int, default=GAME_PORT)
    s.add_argument('--wait', type=float, default=90, help='seconds to wait for the game to open its tuner port')
    sub.add_parser('states')
    sub.add_parser('stop')
    e = sub.add_parser('exec')
    e.add_argument('--context', default='InGame')
    src = e.add_mutually_exclusive_group(required=True)
    src.add_argument('--code')
    src.add_argument('--file', type=Path)
    a = p.parse_args(argv)
    if a.session is None:
        p.error('no --session and no runs folder in the configuration')
    try:
        if a.command == 'serve':
            serve(a.session, a.game_port, a.port, a.wait)
            return 0
        if a.command in ('states', 'stop'):
            result = call_service(a.session, a.command, {'timeout': a.timeout}, a.timeout)
            if a.command == 'stop' and result.get('ok'):
                deadline = time.monotonic() + 5
                while a.session.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
        else:
            code = a.code if a.code is not None else a.file.read_text(encoding='utf-8-sig')
            result = call_service(a.session, 'exec', {'context': a.context, 'source': code, 'timeout': a.timeout}, a.timeout)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result.get('ok') else 1
    except (TunerError, OSError, ValueError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

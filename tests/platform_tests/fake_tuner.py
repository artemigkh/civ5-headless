"""A fake game tuner for tests: the FireTuner protocol on a local port, with Python standing in for Lua.

FakeTuner(handler, contexts) listens on 127.0.0.1 (a free port). It answers LSQ: with its contexts and understands
the console commands the client sends: resetting and appending the upload global, initialising the result wrapper,
and running the uploaded source behind a marker. handler(context, source) returns the list of values the Lua would
return, or raises LuaError (a Lua error); the result travels back the way tuner_result.lua sends it: hex chunks
behind the marker in broadcast "O" packets, then the command's reply. The packet code is written out here rather
than imported, so a mistake in the client's framing does not cancel out.
"""
import json
import re
import socket
import struct
import threading

BROADCAST = 0xFFFFFFFF
ESCAPED = re.compile(r'"((?:\\\d{3})*)"')


class LuaError(Exception):
    pass


def unescape(literal):
    """The bytes of a Lua string literal made of decimal escapes."""
    return bytes(int(literal[i + 1:i + 4]) for i in range(0, len(literal), 4))


def packet(strings, ident):
    body = b'\0'.join(s.encode('utf-8') for s in strings) + b'\0'
    return struct.pack('<II', len(body), ident) + body


def read_packet(sock):
    head = b''
    while len(head) < 8:
        part = sock.recv(8 - len(head))
        if not part:
            return None
        head += part
    size, ident = struct.unpack('<II', head)
    body = b''
    while len(body) < size:
        part = sock.recv(size - len(body))
        if not part:
            return None
        body += part
    return ident, body[:-1].decode('utf-8')


class FakeTuner:
    def __init__(self, handler, contexts=('MainMenu',)):
        self.handler = handler
        self.contexts = {}
        self.next_context = 1
        for name in contexts:
            self.add(name)
        self.uploads = {}
        self.commands = []      # (context, source) of every run
        self.connections = 0
        self.lock = threading.RLock()
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(4)
        self.port = self.listener.getsockname()[1]
        self.closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def add(self, name):
        if name not in self.contexts:
            self.contexts[name] = self.next_context
            self.next_context += 1

    def remove(self, name):
        self.contexts.pop(name, None)

    def close(self):
        self.closed = True
        self.listener.close()

    def _accept(self):
        while not self.closed:
            try:
                sock, _ = self.listener.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock):
        with sock:
            while True:
                got = read_packet(sock)
                if got is None:
                    return
                ident, text = got
                with self.lock:
                    if text == 'LSQ:':
                        flat = []
                        for name, cid in self.contexts.items():
                            flat += [str(cid), name]
                        sock.sendall(packet(flat, ident))
                        continue
                    m = re.fullmatch(r'CMD:(\d+):(.*)', text, re.S)
                    if not m:
                        sock.sendall(packet(['ERR unknown command'], ident))
                        continue
                    cid, code = int(m.group(1)), m.group(2)
                    name = next((n for n, i in self.contexts.items() if i == cid), None)
                    if name is None:
                        sock.sendall(packet(['ERR no such context'], ident))
                        continue
                    for line in self._console(name, code):
                        sock.sendall(packet(['O', line], BROADCAST))
                    sock.sendall(packet(['OK'], ident))

    def _console(self, context, code):
        """Output lines of one console command."""
        if code == "Civ5StackAutomationUpload=''":
            self.uploads[context] = b''
            return []
        if code.startswith('Civ5StackAutomationUpload=Civ5StackAutomationUpload..'):
            self.uploads[context] += unescape(ESCAPED.search(code).group(1))
            return []
        if code.startswith('local f,e=loadstring(Civ5StackAutomationUpload'):
            assert b'Civ5StackAutomationRun' in self.uploads.pop(context)
            return []
        if code.startswith('local s=Civ5StackAutomationUpload'):
            source = self.uploads.pop(context).decode('utf-8')
            marker = unescape(ESCAPED.search(code).group(1)).decode('utf-8')
            self.commands.append((context, source))
            try:
                payload = {'ok': True, 'values': list(self.handler(context, source))}
            except LuaError as error:
                payload = {'ok': False, 'error': str(error)}
            data = json.dumps(payload).encode('utf-8')
            total = (len(data) + 255) // 256
            return [f'{marker}{i + 1}/{total}:' + data[i * 256:(i + 1) * 256].hex() for i in range(total)]
        raise AssertionError(f'unexpected console command: {code[:80]}')

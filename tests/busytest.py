"""busytest.py BUILD_DIR - checks that dbxapi32.dll keeps its connection when
DOSBox Staging's API is busy, as it is while the DOSBox window is dragged:
Staging's main loop stands still, and memory requests get a 500 with
{"error": "Failed to execute command: timeout"} after 250 ms.

A fake API (this process) serves 16 MB of RAM while BUILD_DIR's busytest.exe
reads through the DLL, and goes through phases. "Busy" answers every memory
request except reads at offset 0, so that a DLL measuring the RAM gets its
first read through and then only busy answers.

1. Busy while attached (a window drag): 0-1 s normal, 1-7 s busy, then
   normal. No read may fail: while DOSBox stands still, its cached memory is
   current, and the connection has to stay.
2. Busy while re-attaching: 0-1 s normal, 1-1.5 s failing (404, the DLL
   detaches), 1.5-8 s busy, then normal. Reads have to work again from 10 s
   on: the DLL may not take the RAM size from busy answers.
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAM = 16 << 20
SCENARIOS = [
    ('busy while attached (window dragged)', [(0, 'normal'), (1000, 'busy'), (7000, 'normal')], 10000, 0),
    ('busy while re-attaching after a failure',
     [(0, 'normal'), (1000, 'failing'), (1500, 'busy'), (8000, 'normal')], 11000, 10000),
]
tick = ctypes.windll.kernel32.GetTickCount
tick.restype = ctypes.c_uint32
run = {'t0': 0, 'phases': []}


def phase():
    t = (tick() - run['t0']) & 0xFFFFFFFF
    return [p for s, p in run['phases'] if t >= s][-1]


class Api(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, kind='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, code, msg):
        self.send(code, json.dumps({'error': msg}).encode())

    def do_GET(self):
        if self.path == '/api/v1/dosbox/info':
            return self.send(200, json.dumps({'version': 'fake'}).encode())
        m = re.match(r'/api/v1/memory/(0x[0-9a-fA-F]+|\d+)/(\d+)$', self.path)
        if not m:
            return self.error(404, 'not found')
        off, n = int(m.group(1), 0), int(m.group(2))
        p = phase()
        if p == 'failing':
            return self.error(404, 'not found')
        if p == 'busy' and off != 0:
            threading.Event().wait(0.25)
            return self.error(500, 'Failed to execute command: timeout')
        if off + n > RAM:
            return self.error(500, f'Address range 0x{off} + {n} exceeds emulated memory size ({RAM} bytes)')
        self.send(200, bytes((off + i) & 0xFF for i in range(n)), 'application/octet-stream')


def scenario(build, name, phases, ms, check_from):
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    run.update(t0=tick(), phases=phases)
    out = subprocess.run([os.path.join(build, 'busytest.exe'), str(os.getpid()), str(ms), str(RAM)],
                         cwd=build, capture_output=True, text=True, timeout=120)
    srv.shutdown()
    srv.server_close()
    if out.returncode:
        sys.exit(out.stderr or f'busytest.exe exit {out.returncode}')
    reads = [((int(t) - run['t0']) & 0xFFFFFFFF, res) for t, _, res in (l.split() for l in out.stdout.splitlines())]
    checked = [r for r in reads if r[0] >= check_from]
    failed = [r for r in checked if r[1] != 'ok']
    ok = checked and not failed
    print(f'{"ok    " if ok else "FAILED"} {name}: {len(checked)} reads checked, {len(failed)} failed'
          + (f' (first at {failed[0][0]} ms)' if failed else ''))
    return ok


def main():
    results = [scenario(sys.argv[1], *s) for s in SCENARIOS]
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()

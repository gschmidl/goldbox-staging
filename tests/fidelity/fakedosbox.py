"""A stand-in for DOSBox Staging for the fidelity tests.

- a top-level window (hidden) with a title the original tools look for: the
  sandboxed dbxapi32.dll serves the process that owns it when that process
  answers Staging's API on its port, which this one does;
- Staging's HTTP API on a port of 127.0.0.1: GET /api/v1/memory/<off>/<len>,
  PUT /api/v1/memory/<off>, GET /api/v1/dosbox/info, with Staging's error
  answers (500 + {"error": ...}) past the end of the memory;
- the files Staging's webserver would serve (the pages, the data folders),
  from a table of URL prefixes.

Every memory write is logged with its time and who made it (the original's
DLL or the page), and the reads can be counted. The memory and the logs
belong to the test (FakeDosbox.mem, .writes)."""
import ctypes
import json
import re
import threading
import time
from ctypes import wintypes
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', ctypes.c_uint), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]


user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]

WM_CLOSE, WM_DESTROY, WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0010, 0x0002, 0x0100, 0x0101, 0x0102


class FakeDosbox:
    def __init__(self, title, mem_size=4 << 20, routes=None, rect=(-2540, 560, 640, 400)):
        """title: the window title (contains "DOSBox"); routes: {URL prefix:
        folder} for the webserver's files; rect: the hidden window's place
        (x, y, w, h), which tools that dock beside DOSBox look at."""
        self.title = title
        self.mem = bytearray(mem_size)
        self.routes = dict(routes or {})
        self.writes = []         # (time, offset, bytes, who)
        self.reads = 0
        self.keys = []           # (time, message, vk, lparam) the window received
        self.lock = threading.Lock()
        self.hwnd = None
        self.rect = self._rect = rect
        self._ready = threading.Event()
        self._win_thread = threading.Thread(target=self._window, daemon=True)
        self._win_thread.start()
        self._ready.wait(10)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a):
                pass

            def send(self, code, body, ctype='application/octet-stream', mtime=None):
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                if mtime is not None:   # as a webserver does: the file's date
                    self.send_header('Last-Modified', formatdate(mtime, usegmt=True))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

            def error(self, code, msg):
                self.send(code, json.dumps({'error': msg}).encode(), 'application/json')

            def who(self):
                ua = self.headers.get('User-Agent', '')
                return 'original' if ua.startswith('dbxapi32') else 'page'

            def do_GET(self):
                path = self.path.split('?')[0]
                m = re.match(r'^/api/v1/memory/(0x[0-9a-fA-F]+|\d+)/(\d+)$', path)
                if m:
                    off, n = int(m.group(1), 0), int(m.group(2))
                    size = len(fake.mem)
                    if off >= size or off + n > size:
                        return self.error(500, f'Address range 0x{off:x} + {n} exceeds emulated memory '
                                               f'size ({size} bytes)')
                    with fake.lock:
                        fake.reads += 1
                        body = bytes(fake.mem[off:off + n])
                    return self.send(200, body)
                if path == '/api/v1/dosbox/info':
                    return self.send(200, json.dumps({'version': '0.84.0-fake', 'program': 'FAKE'}).encode(),
                                     'application/json')
                fp = fake.file(unquote(path.lstrip('/')))
                if fp is None:
                    return self.send(404, b'', 'text/plain')
                ctype = 'text/html; charset=utf-8' if fp.suffix.lower() == '.html' else 'application/octet-stream'
                return self.send(200, fp.read_bytes(), ctype, fp.stat().st_mtime)

            do_HEAD = do_GET

            def do_PUT(self):
                m = re.match(r'^/api/v1/memory/(0x[0-9a-fA-F]+|\d+)$', self.path.split('?')[0])
                n = int(self.headers.get('Content-Length', 0))
                data = self.rfile.read(n)
                if not m:
                    return self.error(404, 'not found')
                off = int(m.group(1), 0)
                if off + n > len(fake.mem):
                    return self.error(500, f'Address range 0x{off:x} + {n} exceeds emulated memory '
                                           f'size ({len(fake.mem)} bytes)')
                with fake.lock:
                    fake.mem[off:off + n] = data
                    fake.writes.append((time.monotonic(), off, data, self.who()))
                self.send(200, b'', 'text/plain')

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass   # clients closing their connections (WinHTTP, the browser)

        self.server = Server(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    # ---- the window ------------------------------------------------------------
    def _window(self):
        hinst = kernel32.GetModuleHandleW(None)
        cls = f'FakeDOSBox{id(self)}'

        def proc(h, msg, wp, lp):
            if msg in (WM_KEYDOWN, WM_KEYUP, WM_CHAR):
                self.keys.append((time.monotonic(), msg, wp, lp))
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(h)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(h, msg, wp, lp)

        self._proc = WNDPROC(proc)
        wc = WNDCLASSW(0, self._proc, 0, 0, hinst, None, None, None, None, cls)
        user32.RegisterClassW(ctypes.byref(wc))
        x, y, w, h = self._rect
        self.hwnd = user32.CreateWindowExW(0, cls, self.title, 0x00CF0000, x, y, w, h,
                                           None, None, hinst, None)   # WS_OVERLAPPEDWINDOW, not shown
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self._win_thread.join(5)

    # ---- files -------------------------------------------------------------------
    BLANK = '__blank.html'   # an empty page of this origin, for the tests' own setup

    def file(self, rel):
        if rel == self.BLANK:
            return Path(__file__).with_name('blank.html')
        for prefix in sorted(self.routes, key=len, reverse=True):
            if rel == prefix.rstrip('/') or rel.startswith(prefix):
                root = Path(self.routes[prefix])
                sub = rel[len(prefix):] if rel.startswith(prefix) else ''
                fp = root / sub if sub else root
                if fp.is_file():
                    return fp
                # case-insensitive, as DOS file names come in any case
                if root.is_dir() and sub and '/' not in sub:
                    for c in root.iterdir():
                        if c.name.lower() == sub.lower() and c.is_file():
                            return c
                return None
        return None

    # ---- memory ------------------------------------------------------------------
    def put(self, off, data):
        with self.lock:
            self.mem[off:off + len(data)] = data

    def get(self, off, n):
        with self.lock:
            return bytes(self.mem[off:off + n])

    def reset(self, image=None, size=None):
        """New memory contents (zeros, or image), the logs emptied."""
        with self.lock:
            if size and size != len(self.mem):
                self.mem = bytearray(size)
            self.mem[:] = bytes(len(self.mem))
            if image:
                self.mem[:len(image)] = image
            self.writes.clear()
            self.keys.clear()
            self.reads = 0

    def take_writes(self):
        with self.lock:
            w = list(self.writes)
            self.writes.clear()
        return w

"""Running and driving a page for the fidelity tests: a headless Microsoft
Edge (or Chrome) with its own profile, controlled through the DevTools
protocol over a WebSocket (no packages needed)."""
import base64
import hashlib
import json
import os
import queue
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path


def find_browser():
    """Edge or Chrome: the BROWSER environment variable, the App Paths
    registry entries, or PATH."""
    if os.environ.get('BROWSER') and Path(os.environ['BROWSER']).is_file():
        return os.environ['BROWSER']
    try:
        import winreg
        for exe in ('msedge.exe', 'chrome.exe'):
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, rf'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}') as k:
                        p = winreg.QueryValue(k, None)
                        if p and Path(p).is_file():
                            return p
                except OSError:
                    pass
    except ImportError:
        pass
    for exe in ('msedge', 'chrome', 'chromium', 'google-chrome'):
        p = shutil.which(exe)
        if p:
            return p
    raise RuntimeError('no Edge or Chrome found: set BROWSER to its executable')


class WebSocket:
    """Just enough of RFC 6455 for the DevTools protocol."""

    def __init__(self, url):
        assert url.startswith('ws://')
        hostport, path = url[5:].split('/', 1)
        host, port = hostport.rsplit(':', 1)
        self.sock = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n'
                           f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                           f'Sec-WebSocket-Version: 13\r\n\r\n').encode())
        head = b''
        while b'\r\n\r\n' not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError('websocket handshake failed')
            head += chunk
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise ConnectionError(head.decode('latin-1'))
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode())
                                  .digest()).decode()
        if accept.encode() not in head:
            raise ConnectionError('bad Sec-WebSocket-Accept')
        self.sock.settimeout(None)
        self.lock = threading.Lock()

    def send(self, text):
        data = text.encode()
        n = len(data)
        head = bytearray([0x81])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack('>H', n)
        else:
            head += bytes([0x80 | 127]) + struct.pack('>Q', n)
        mask = os.urandom(4)
        body = bytes(b ^ mask[i & 3] for i, b in enumerate(data)) if n < 4096 else self._mask(data, mask)
        with self.lock:
            self.sock.sendall(bytes(head) + mask + body)

    @staticmethod
    def _mask(data, mask):
        import numpy as np
        m = np.frombuffer((mask * (len(data) // 4 + 1))[:len(data)], np.uint8)
        return (np.frombuffer(data, np.uint8) ^ m).tobytes()

    def _read(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError('websocket closed')
            buf += chunk
        return bytes(buf)

    def recv(self):
        msg = bytearray()
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
            op = b0 & 0x0F
            if op == 8:
                raise ConnectionError('websocket closed')
            if op == 9:
                with self.lock:
                    self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op in (0, 1, 2):
                msg += data
                if b0 & 0x80:
                    return msg.decode()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    """A headless browser with one page target."""

    def __init__(self, width=1400, height=1000, downloads=None):
        self.profile = tempfile.mkdtemp(prefix='fidelity-browser-')
        self.downloads = Path(downloads or Path(self.profile) / 'downloads')
        self.downloads.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen([find_browser(), '--headless=new', '--remote-debugging-port=0',
                                      f'--user-data-dir={self.profile}', '--no-first-run',
                                      '--no-default-browser-check', '--disable-extensions',
                                      '--disable-background-networking', '--disable-sync',
                                      '--disable-component-update', '--disable-features=msEdgeSidebarV2',
                                      '--force-device-scale-factor=1', '--hide-scrollbars',
                                      '--font-render-hinting=none', f'--window-size={width},{height}',
                                      'about:blank'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(self.profile) / 'DevToolsActivePort'
        end = time.monotonic() + 30
        while not port_file.exists() or not port_file.read_text().strip():
            if time.monotonic() > end:
                raise RuntimeError('the browser did not start')
            time.sleep(0.1)
        self.port = int(port_file.read_text().split()[0])
        targets = []
        while not [t for t in targets if t.get('type') == 'page']:
            with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/list') as r:
                targets = json.load(r)
            time.sleep(0.1)
        page = [t for t in targets if t['type'] == 'page'][0]
        self.ws = WebSocket(page['webSocketDebuggerUrl'])
        self.next_id = 0
        self.pending = {}
        self.events = queue.Queue()
        self.dialogs = []            # (type, message) of alert/confirm/prompt
        self.dialog_answers = []     # what the next dialogs answer: True/False/text
        self.console = []
        self.errors = []
        threading.Thread(target=self._reader, daemon=True).start()
        self.call('Page.enable')
        self.call('Runtime.enable')
        self.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1,
                  mobile=False)
        self.call('Browser.setDownloadBehavior', behavior='allow', downloadPath=str(self.downloads),
                  eventsEnabled=True)

    def _reader(self):
        try:
            while True:
                msg = json.loads(self.ws.recv())
                if 'id' in msg:
                    q = self.pending.pop(msg['id'], None)
                    if q:
                        q.put(msg)
                    continue
                m = msg.get('method')
                p = msg.get('params', {})
                if m == 'Page.javascriptDialogOpening':
                    self.dialogs.append((p.get('type'), p.get('message')))
                    ans = self.dialog_answers.pop(0) if self.dialog_answers else True
                    args = {'accept': ans is not False}
                    if isinstance(ans, str):
                        args['promptText'] = ans
                    threading.Thread(target=self.call, args=('Page.handleJavaScriptDialog',),
                                     kwargs=args, daemon=True).start()
                elif m == 'Runtime.consoleAPICalled':
                    self.console.append((p.get('type'), ' '.join(str(a.get('value', a.get('description', '')))
                                                                 for a in p.get('args', []))))
                elif m == 'Runtime.exceptionThrown':
                    d = p.get('exceptionDetails', {})
                    self.errors.append(d.get('exception', {}).get('description') or d.get('text'))
                self.events.put(msg)
        except (ConnectionError, OSError):
            pass

    def call(self, method, timeout=60, **params):
        self.next_id += 1
        i = self.next_id
        q = queue.Queue()
        self.pending[i] = q
        self.ws.send(json.dumps({'id': i, 'method': method, 'params': params}))
        try:
            msg = q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(method)
        if 'error' in msg:
            raise RuntimeError(f'{method}: {msg["error"]}')
        return msg.get('result', {})

    def js(self, expr, timeout=60):
        """The value of a JavaScript expression (promises awaited)."""
        r = self.call('Runtime.evaluate', timeout=timeout, expression=expr, awaitPromise=True,
                      returnByValue=True, userGesture=True)
        if 'exceptionDetails' in r:
            d = r['exceptionDetails']
            raise RuntimeError(f'{expr[:80]}: {d.get("exception", {}).get("description") or d.get("text")}')
        return r.get('result', {}).get('value')

    def goto(self, url, wait='load'):
        while not self.events.empty():
            self.events.get_nowait()
        self.call('Page.navigate', url=url)
        end = time.monotonic() + 30
        while time.monotonic() < end:
            try:
                ev = self.events.get(timeout=1)
            except queue.Empty:
                continue
            if ev.get('method') == 'Page.loadEventFired':
                return
        raise TimeoutError(url)

    def wait(self, expr, timeout=20.0, every=0.1):
        """Waits until a JavaScript expression is truthy; returns its value."""
        end = time.monotonic() + timeout
        while True:
            v = self.js(expr)
            if v:
                return v
            if time.monotonic() > end:
                raise TimeoutError(expr)
            time.sleep(every)

    # ---- input ---------------------------------------------------------------------
    MODS = {'alt': 1, 'ctrl': 2, 'meta': 4, 'shift': 8}

    def mouse(self, x, y, what='move', mods=()):
        m = sum(self.MODS[k] for k in mods)
        self.call('Input.dispatchMouseEvent', type='mouseMoved', x=x, y=y, modifiers=m)
        if what in ('left', 'right', 'double'):
            button = 'right' if what == 'right' else 'left'
            for count in ((1, 2) if what == 'double' else (1,)):
                self.call('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y, button=button,
                          clickCount=count, modifiers=m)
                self.call('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y, button=button,
                          clickCount=count, modifiers=m)

    def key(self, key, code=None, vk=0, text=None, mods=()):
        m = sum(self.MODS[k] for k in mods)
        args = dict(key=key, code=code or key, windowsVirtualKeyCode=vk, nativeVirtualKeyCode=vk, modifiers=m)
        self.call('Input.dispatchKeyEvent', type='keyDown' if text is None else 'keyDown', text=text or '',
                  **args)
        self.call('Input.dispatchKeyEvent', type='keyUp', **args)

    def viewport(self, width, height):
        """The page's size in CSS pixels (the browser starts at 1400 x 1000)."""
        self.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)

    def canvas_png(self, selector):
        """A canvas's pixels as PNG bytes."""
        url = self.js(f'document.querySelector({json.dumps(selector)}).toDataURL("image/png")')
        return base64.b64decode(url.split(',', 1)[1])

    def inject(self, source):
        """Runs a script in every page loaded from now on, before the page's own."""
        self.call('Page.addScriptToEvaluateOnNewDocument', source=source)

    def canvas(self, selector):
        """A canvas as an RGB image; with instrument.js loaded, the text drawn
        on it is in image.info['texts'] (text, box, colour, font each)."""
        from PIL import Image
        import io
        r = self.js(f'window.__fidCanvas ? __fidCanvas({json.dumps(selector)}) : '
                    f'{{png: document.querySelector({json.dumps(selector)}).toDataURL("image/png"), boxes: []}}')
        if not r:
            return None
        img = Image.open(io.BytesIO(base64.b64decode(r['png'].split(',', 1)[1]))).convert('RGB')
        img.info['texts'] = r.get('boxes') or []
        return img

    def screenshot(self, clip=None):
        args = {'format': 'png'}
        if clip:
            args['clip'] = dict(x=clip[0], y=clip[1], width=clip[2], height=clip[3], scale=1)
        return base64.b64decode(self.call('Page.captureScreenshot', **args)['data'])

    def close(self):
        try:
            self.call('Browser.close', timeout=5)
        except Exception:
            pass
        self.ws.close()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

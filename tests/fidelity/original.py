"""Running and driving an original tool (Delphi, 32-bit) for the fidelity
tests, without real input: the tool runs with the sandboxed dbxapi32.dll
(sandbox.c), which takes the cursor position, the keys held down, the
foreground window and dialog answers from shared memory this module writes.
Clicks and keys are posted to the tool's windows; menus are read from their
handles and their commands posted; windows are captured with PrintWindow.

This process stays DPI-unaware, like the tools, so coordinates agree."""
import ctypes
import mmap
import os
import shutil
import struct
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
for f, res, args in [
    ('PostMessageW', wintypes.BOOL, [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]),
    ('SendMessageW', ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]),
    ('SendMessageTimeoutW', ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
                                               ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]),
    ('GetWindowTextW', ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
    ('GetClassNameW', ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
    ('GetWindowThreadProcessId', wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
    ('IsWindowVisible', wintypes.BOOL, [wintypes.HWND]),
    ('IsWindowEnabled', wintypes.BOOL, [wintypes.HWND]),
    ('IsWindow', wintypes.BOOL, [wintypes.HWND]),
    ('GetWindowRect', wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]),
    ('GetClientRect', wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]),
    ('ClientToScreen', wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]),
    ('ScreenToClient', wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]),
    ('SetWindowPos', wintypes.BOOL, [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_uint]),
    ('GetParent', wintypes.HWND, [wintypes.HWND]),
    ('GetWindow', wintypes.HWND, [wintypes.HWND, ctypes.c_uint]),
    ('GetDlgCtrlID', ctypes.c_int, [wintypes.HWND]),
    ('GetMenu', wintypes.HMENU, [wintypes.HWND]),
    ('GetMenuItemCount', ctypes.c_int, [wintypes.HMENU]),
    ('GetSubMenu', wintypes.HMENU, [wintypes.HMENU, ctypes.c_int]),
    ('GetMenuItemID', ctypes.c_uint, [wintypes.HMENU, ctypes.c_int]),
    ('GetMenuState', ctypes.c_uint, [wintypes.HMENU, ctypes.c_uint, ctypes.c_uint]),
    ('GetMenuStringW', ctypes.c_int, [wintypes.HMENU, ctypes.c_uint, wintypes.LPWSTR, ctypes.c_int, ctypes.c_uint]),
    ('EnumWindows', wintypes.BOOL, [WNDENUMPROC, wintypes.LPARAM]),
    ('EnumChildWindows', wintypes.BOOL, [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]),
    ('EnumThreadWindows', wintypes.BOOL, [wintypes.DWORD, WNDENUMPROC, wintypes.LPARAM]),
    ('PrintWindow', wintypes.BOOL, [wintypes.HWND, wintypes.HDC, ctypes.c_uint]),
    ('GetDC', wintypes.HDC, [wintypes.HWND]),
    ('ReleaseDC', ctypes.c_int, [wintypes.HWND, wintypes.HDC]),
    ('GetWindowLongW', ctypes.c_long, [wintypes.HWND, ctypes.c_int]),
]:
    fn = getattr(user32, f)
    fn.restype, fn.argtypes = res, args
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_size_t
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GdiFlush.restype = wintypes.BOOL

WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH = 0x000C, 0x000D, 0x000E
WM_CLOSE, WM_COMMAND, WM_CONTEXTMENU, WM_CANCELMODE = 0x0010, 0x0111, 0x007B, 0x001F
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0200, 0x0201, 0x0202, 0x0203
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MOUSEWHEEL = 0x0204, 0x0205, 0x020A
MK_LBUTTON, MK_RBUTTON, MK_SHIFT, MK_CONTROL = 1, 2, 4, 8
BM_CLICK = 0x00F5
LB_GETCOUNT, LB_GETTEXT, LB_GETTEXTLEN, LB_GETCURSEL, LB_SETCURSEL = 0x018B, 0x0189, 0x018A, 0x0188, 0x0186
LB_GETITEMDATA, BM_GETCHECK = 0x0199, 0x00F0
CB_GETCOUNT, CB_GETLBTEXT, CB_GETLBTEXTLEN, CB_GETCURSEL, CB_SETCURSEL = 0x0146, 0x0148, 0x0149, 0x0147, 0x014E
LBN_SELCHANGE, LBN_DBLCLK, CBN_SELCHANGE, EN_CHANGE = 1, 2, 1, 0x0300
MN_GETHMENU = 0x01E1
MF_BYPOSITION, MF_POPUP, MF_SEPARATOR, MF_GRAYED, MF_DISABLED, MF_CHECKED = 0x400, 0x10, 0x800, 1, 2, 8
VK = {'shift': 0x10, 'ctrl': 0x11, 'alt': 0x12}
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 1, 4, 0x10

# The left monitor of the tester's desktop: test windows go there.
LEFT = (-2560, 0)


def _text(fn, h, n=1024):
    b = ctypes.create_unicode_buffer(n)
    fn(h, b, n)
    return b.value


def unescape(s):
    """The sandbox log's escapes (\\xNN for control characters and \\)."""
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\' and s[i + 1:i + 2] == 'x':
            out.append(chr(int(s[i + 2:i + 4], 16)))
            i += 4
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def tick():
    return kernel32.GetTickCount()


def window_text(h):
    n = user32.SendMessageW(h, WM_GETTEXTLENGTH, 0, 0)
    b = ctypes.create_unicode_buffer(max(n, 0) + 2)
    user32.SendMessageW(h, WM_GETTEXT, n + 1, ctypes.addressof(b))
    return b.value


def class_name(h):
    return _text(user32.GetClassNameW, h, 256)


def rect(h, client=False):
    r = wintypes.RECT()
    (user32.GetClientRect if client else user32.GetWindowRect)(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def to_screen(h, x, y):
    p = wintypes.POINT(x, y)
    user32.ClientToScreen(h, ctypes.byref(p))
    return p.x, p.y


def pid_of(h):
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value, tid


def top_windows(pid=None):
    out = []

    def cb(h, _):
        if pid is None or pid_of(h)[0] == pid:
            out.append(h)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def children(h):
    out = []

    def cb(k, _):
        out.append(k)
        return True
    user32.EnumChildWindows(h, WNDENUMPROC(cb), 0)
    return out


class Shared:
    """The block sandbox.c reads (struct Shared)."""
    FMT = '<4l256s260sl'

    def __init__(self, name):
        self.name = name
        self.mm = mmap.mmap(-1, 4096, tagname=name)
        self.cursor = (-32000, -32000)
        self.foreground = 0
        self.keys = bytearray(256)
        self.write()

    def write(self, msgbox_answer=None, file_answer=None):
        self.mm.seek(0)
        cur = struct.unpack(self.FMT, self.mm.read(struct.calcsize(self.FMT)))
        ans = cur[3] if msgbox_answer is None else msgbox_answer
        fa = cur[5] if file_answer is None else file_answer.encode('mbcs') + b'\0'
        self.mm.seek(0)
        self.mm.write(struct.pack(self.FMT, self.cursor[0], self.cursor[1], self.foreground, ans,
                                  bytes(self.keys), fa.ljust(260, b'\0')[:260], cur[6]))

    def msgbox_count(self):
        self.mm.seek(struct.calcsize(self.FMT) - 4)
        return struct.unpack('<l', self.mm.read(4))[0]


def prepare_tool(src, dest, sandbox_dll, skip=()):
    """A copy of a tool folder, patched for the API (the repo's patch.py)
    and given the sandboxed DLL. Patched sources are fine: their *.orig
    files are copied back first."""
    src, dest = Path(src), Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*skip, 'dbxapi32.*'))
    for orig in dest.rglob('*.orig'):
        target = orig.with_suffix('')
        if target.exists():
            target.unlink()
        orig.rename(target)
    out = subprocess.run([sys.executable, str(REPO / 'patch.py'), str(dest)], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f'patch.py failed on {dest}:\n{out.stdout}{out.stderr}')
    for dll in dest.rglob('dbxapi32.dll'):
        shutil.copyfile(sandbox_dll, dll)
    return out.stdout


class Tool:
    """One running original."""

    def __init__(self, exe, args, fake, work, title_hint=None):
        self.exe = Path(exe)
        self.fake = fake
        self.log_path = Path(work) / f'sandbox-{os.getpid()}-{int(time.time() * 1000)}.log'
        self.shared = Shared(f'dbxtest-{os.getpid()}-{id(self)}')
        self.shared.foreground = 0
        self.shared.write()
        env = dict(os.environ, DBXTEST=self.shared.name, DBXTEST_LOG=str(self.log_path),
                   DBXAPI_PORT=str(fake.port), DBXTEST_LEFT=f'{LEFT[0]},{LEFT[1]}')
        self.proc = subprocess.Popen([str(self.exe)] + list(args), cwd=str(self.exe.parent), env=env)
        self.pid = self.proc.pid
        self.main = None

    # ---- windows -------------------------------------------------------------------
    def windows(self, visible=True):
        return [h for h in top_windows(self.pid) if not visible or user32.IsWindowVisible(h)]

    def find(self, cls=None, title=None, visible=True, timeout=10.0):
        end = time.monotonic() + timeout
        while True:
            for h in self.windows(visible):
                if (cls is None or class_name(h) == cls) and (title is None or title in window_text(h)):
                    return h
            if time.monotonic() > end or self.proc.poll() is not None:
                return None
            time.sleep(0.05)

    def place(self, h, x=None, y=None):
        """Moves a window onto the left monitor (no activation)."""
        x = LEFT[0] + 20 if x is None else x
        y = LEFT[1] + 20 if y is None else y
        user32.SetWindowPos(h, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def controls(self, h=None, visible=True):
        """(class, hwnd, text, rect) of every child window."""
        h = h or self.main
        out = []
        for k in children(h):
            if visible and not user32.IsWindowVisible(k):
                continue
            out.append((class_name(k), k, window_text(k), rect(k)))
        return out

    def control(self, cls, n=0, h=None, text=None):
        found = [c for c in self.controls(h) if c[0] == cls and (text is None or c[2].replace('&', '') == text)]
        return found[n][1] if len(found) > n else None

    def list_items(self, h):
        combo = 'Combo' in class_name(h)
        cnt = user32.SendMessageW(h, CB_GETCOUNT if combo else LB_GETCOUNT, 0, 0)
        out = []
        for i in range(max(cnt, 0)):
            n = user32.SendMessageW(h, CB_GETLBTEXTLEN if combo else LB_GETTEXTLEN, i, 0)
            b = ctypes.create_unicode_buffer(max(n, 0) + 2)
            user32.SendMessageW(h, CB_GETLBTEXT if combo else LB_GETTEXT, i, ctypes.addressof(b))
            out.append(b.value)
        return out

    def listview_items(self, h, columns=1):
        """The rows of a list view (comctl32's, in the tool's own 32-bit process): its texts
        are read through a buffer in that process (LVM_GETITEMTEXTW)."""
        LVM_GETITEMCOUNT, LVM_GETITEMTEXTW = 0x1004, 0x1073
        n = user32.SendMessageW(h, LVM_GETITEMCOUNT, 0, 0)
        proc = kernel32.OpenProcess(0x0008 | 0x0010 | 0x0020, False, self.pid)   # VM operation, read, write
        if not proc:
            return []
        try:
            remote = kernel32.VirtualAllocEx(proc, None, 4096, 0x1000, 0x04)
            rows = []
            for i in range(max(n, 0)):
                row = []
                for c in range(columns):
                    # LVITEMW of a 32-bit process: mask, iItem, iSubItem, state, stateMask, pszText, cchTextMax ...
                    item = struct.pack('<IiiIIIi', 0, i, c, 0, 0, remote + 256, 1000).ljust(64, b'\0')
                    kernel32.WriteProcessMemory(proc, remote, item, len(item), None)
                    k = user32.SendMessageW(h, LVM_GETITEMTEXTW, i, remote)
                    buf = ctypes.create_string_buffer(2 * max(k, 0) + 2)
                    kernel32.ReadProcessMemory(proc, remote + 256, buf, 2 * max(k, 0), None)
                    row.append(buf.raw[:2 * max(k, 0)].decode('utf-16-le'))
                rows.append(row)
            kernel32.VirtualFreeEx(proc, remote, 0, 0x8000)
            return rows
        finally:
            kernel32.CloseHandle(proc)

    def read_memory(self, addr, n):
        """n bytes of the tool's own memory at addr (its globals, for a look at what it worked out)."""
        proc = kernel32.OpenProcess(0x0010, False, self.pid)
        try:
            buf = ctypes.create_string_buffer(n)
            kernel32.ReadProcessMemory(proc, addr, buf, n, None)
            return buf.raw
        finally:
            kernel32.CloseHandle(proc)

    def listview_select(self, h, index):
        """Selects (and focuses) a list view's row, as a click would leave it."""
        LVM_SETITEMSTATE = 0x102B
        proc = kernel32.OpenProcess(0x0008 | 0x0010 | 0x0020, False, self.pid)
        if not proc:
            return
        try:
            remote = kernel32.VirtualAllocEx(proc, None, 4096, 0x1000, 0x04)
            item = struct.pack('<IiiII', 0x8, index, 0, 3, 3).ljust(64, b'\0')   # LVIF_STATE, selected + focused
            kernel32.WriteProcessMemory(proc, remote, item, len(item), None)
            user32.SendMessageW(h, LVM_SETITEMSTATE, index, remote)
            kernel32.VirtualFreeEx(proc, remote, 0, 0x8000)
        finally:
            kernel32.CloseHandle(proc)

    # ---- a form's controls by name -----------------------------------------------------
    def form_controls(self, form, table):
        """The form's child windows that table names: {(class, x, y in the form's client area):
        name} (a form's own places)."""
        out = {}
        for cls, h, _, r in self.controls(form, visible=False):
            p = wintypes.POINT(r[0], r[1])
            user32.ScreenToClient(form, ctypes.byref(p))
            name = table.get((cls, p.x, p.y))
            if name:
                out[name] = h
        return out

    def check_list_checked(self, h, i):
        """A TCheckListBox item's check: its item data is the VCL's wrapper object (VMT, data,
        state), none for an item never checked."""
        p = user32.SendMessageW(h, LB_GETITEMDATA, i, 0) & 0xFFFFFFFF
        return bool(p) and p != 0xFFFFFFFF and self.read_memory(p + 8, 1)[0] == 1

    def control_values(self, controls):
        """What named controls show: an edit's text, a combo box's choice and entries, a check
        box's check, a panel's caption, a list box's entries and choice, a check list's entries
        and checks, a list view's rows (three columns); whether each is enabled (not panels)."""
        out = {}
        for name, h in controls.items():
            cls, en = class_name(h), bool(user32.IsWindowEnabled(h))
            if cls == 'TEdit':
                out[name] = {'text': window_text(h), 'enabled': en}
            elif cls == 'TComboBox':
                items, sel = self.list_items(h), user32.SendMessageW(h, CB_GETCURSEL, 0, 0)
                out[name] = {'text': items[sel] if 0 <= sel < len(items) else '', 'items': items, 'enabled': en}
            elif cls == 'TCheckBox':
                out[name] = {'checked': user32.SendMessageW(h, BM_GETCHECK, 0, 0) == 1, 'enabled': en}
            elif cls == 'TPanel':
                out[name] = {'text': window_text(h)}
            elif cls == 'TButton':
                out[name] = {'enabled': en}
            elif cls == 'TListBox':
                out[name] = {'items': self.list_items(h), 'index': user32.SendMessageW(h, LB_GETCURSEL, 0, 0), 'enabled': en}
            elif cls == 'TCheckListBox':
                out[name] = {'items': [[t, self.check_list_checked(h, i)] for i, t in enumerate(self.list_items(h))], 'enabled': en}
            elif cls == 'TListView':
                out[name] = {'rows': self.listview_items(h, 3), 'enabled': en}
        return out

    def list_selection(self, h):
        return user32.SendMessageW(h, CB_GETCURSEL if 'Combo' in class_name(h) else LB_GETCURSEL, 0, 0)

    def select(self, h, i, double=False):
        combo = 'Combo' in class_name(h)
        user32.SendMessageW(h, CB_SETCURSEL if combo else LB_SETCURSEL, i, 0)
        code = CBN_SELCHANGE if combo else (LBN_DBLCLK if double else LBN_SELCHANGE)
        if double and not combo:
            user32.PostMessageW(user32.GetParent(h), WM_COMMAND,
                                (LBN_SELCHANGE << 16) | (user32.GetDlgCtrlID(h) & 0xFFFF), h)
        user32.PostMessageW(user32.GetParent(h), WM_COMMAND, (code << 16) | (user32.GetDlgCtrlID(h) & 0xFFFF), h)

    def set_text(self, h, text):
        b = ctypes.create_unicode_buffer(text)
        user32.SendMessageW(h, WM_SETTEXT, 0, ctypes.addressof(b))
        user32.PostMessageW(user32.GetParent(h), WM_COMMAND, (EN_CHANGE << 16) | (user32.GetDlgCtrlID(h) & 0xFFFF), h)

    def click_button(self, h):
        user32.PostMessageW(h, BM_CLICK, 0, 0)

    # ---- input ---------------------------------------------------------------------
    def hold(self, *mods):
        """The modifier keys held down from now on ('ctrl', 'shift', 'alt')."""
        for v in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
            self.shared.keys[v] = 0
        for m in mods:
            self.shared.keys[VK[m]] = 0x80
            self.shared.keys[{'shift': 0xA0, 'ctrl': 0xA2, 'alt': 0xA4}[m]] = 0x80
        self.shared.write()

    def cursor(self, h, x, y):
        self.shared.cursor = to_screen(h, x, y)
        self.shared.write()

    def mouse(self, h, x, y, what='move', mods=()):
        """Posts mouse messages at client (x, y) of h, the cursor following."""
        self.hold(*mods)
        self.cursor(h, x, y)
        keys = (MK_CONTROL if 'ctrl' in mods else 0) | (MK_SHIFT if 'shift' in mods else 0)
        lp = (y & 0xFFFF) << 16 | (x & 0xFFFF)
        user32.PostMessageW(h, WM_MOUSEMOVE, keys, lp)
        if what == 'left':
            user32.PostMessageW(h, WM_LBUTTONDOWN, keys | MK_LBUTTON, lp)
            user32.PostMessageW(h, WM_LBUTTONUP, keys, lp)
        elif what == 'double':
            user32.PostMessageW(h, WM_LBUTTONDOWN, keys | MK_LBUTTON, lp)
            user32.PostMessageW(h, WM_LBUTTONUP, keys, lp)
            user32.PostMessageW(h, WM_LBUTTONDBLCLK, keys | MK_LBUTTON, lp)
            user32.PostMessageW(h, WM_LBUTTONUP, keys, lp)
        elif what == 'right':
            user32.PostMessageW(h, WM_RBUTTONDOWN, keys | MK_RBUTTON, lp)
            user32.PostMessageW(h, WM_RBUTTONUP, keys, lp)

    def key(self, h, vk, char=None, mods=()):
        self.hold(*mods)
        scan = user32.MapVirtualKeyW(vk, 0) if hasattr(user32, 'MapVirtualKeyW') else 0
        user32.PostMessageW(h, WM_KEYDOWN, vk, 1 | (scan << 16))
        if char:
            user32.PostMessageW(h, WM_CHAR, ord(char), 1 | (scan << 16))
        user32.PostMessageW(h, WM_KEYUP, vk, 1 | (scan << 16) | (3 << 30))

    # ---- menus ---------------------------------------------------------------------
    @staticmethod
    def read_menu(hm):
        """[(caption, id, enabled, checked, children)] of a menu handle."""
        out = []
        for i in range(max(user32.GetMenuItemCount(hm), 0)):
            st = user32.GetMenuState(hm, i, MF_BYPOSITION)
            b = ctypes.create_unicode_buffer(256)
            user32.GetMenuStringW(hm, i, b, 256, MF_BYPOSITION)
            sub = user32.GetSubMenu(hm, i)
            if st & MF_SEPARATOR and not sub:
                out.append(('-', 0, False, False, None))
                continue
            out.append((b.value, user32.GetMenuItemID(hm, i) if not sub else 0,
                        not st & (MF_GRAYED | MF_DISABLED), bool(st & MF_CHECKED),
                        Tool.read_menu(sub) if sub else None))
        return out

    def main_menu(self, h=None):
        hm = user32.GetMenu(h or self.main)
        return self.read_menu(hm) if hm else []

    def popup(self, h, x=-1, y=-1, timeout=3.0):
        """Opens the popup menu of window h (WM_CONTEXTMENU, at screen x, y or
        as from the keyboard), reads it and closes it again."""
        lp = 0xFFFFFFFF if x < 0 else ((y & 0xFFFF) << 16 | (x & 0xFFFF))
        user32.PostMessageW(h, WM_CONTEXTMENU, h, lp)
        end = time.monotonic() + timeout
        menu_wnd = None
        while time.monotonic() < end and not menu_wnd:
            for w in top_windows(self.pid):
                if class_name(w) == '#32768' and user32.IsWindowVisible(w):
                    menu_wnd = w
                    break
            time.sleep(0.03)
        if not menu_wnd:
            return None
        hm = user32.SendMessageW(menu_wnd, MN_GETHMENU, 0, 0)
        items = self.read_menu(hm)
        self.close_menus()
        return items

    def close_menus(self):
        for _ in range(20):
            open_ = [w for w in top_windows(self.pid) if class_name(w) == '#32768' and user32.IsWindowVisible(w)]
            if not open_:
                return
            for w in open_:
                user32.PostMessageW(w, WM_KEYDOWN, 0x1B, 0)
            for w in self.windows():
                user32.PostMessageW(w, WM_CANCELMODE, 0, 0)
            time.sleep(0.05)

    @staticmethod
    def find_item(items, path):
        """The item at a path of captions ('Window', 'Size to 512'); '&',
        trailing tabs (shortcut texts) and spaces at the ends are ignored."""
        for cap, id_, en, ch, sub in items:
            if cap.replace('&', '').split('\t')[0].strip() == path[0].strip():
                if len(path) == 1:
                    return cap, id_, en, ch, sub
                return Tool.find_item(sub or [], path[1:])
        return None

    def command(self, id_, h=None):
        """Posts a menu command: to the form (main menus) or to the hidden
        utility windows (popup menus are dispatched by the VCL's PopupList)."""
        if h:
            user32.PostMessageW(h, WM_COMMAND, id_, 0)
            return
        for w in top_windows(self.pid):
            if class_name(w) == 'TPUtilWindow':
                user32.PostMessageW(w, WM_COMMAND, id_, 0)

    # ---- capture -------------------------------------------------------------------
    def capture(self, h=None, client=True):
        """The window's client area (or the whole window) as an RGB image (PrintWindow fails
        now and then while the tool is busy: tried a few times)."""
        h = h or self.main
        for _ in range(5):
            img = self._capture(h, client)
            if img is not None or not user32.IsWindow(h):
                return img
            time.sleep(0.2)
        return None

    def _capture(self, h, client):
        l, t, r, b = rect(h, client=True) if client else (0, 0, rect(h)[2] - rect(h)[0], rect(h)[3] - rect(h)[1])
        w, hgt = r - l, b - t
        if w <= 0 or hgt <= 0:
            return None
        hdc = user32.GetDC(None)
        mdc = gdi32.CreateCompatibleDC(hdc)
        bmi = struct.pack('<IiiHHIIiiII', 40, w, -hgt, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        hbm = gdi32.CreateDIBSection(mdc, bmi, 0, ctypes.byref(bits), None, 0)
        self.last_dib = hbm or 0
        old = gdi32.SelectObject(mdc, hbm)
        # PW_CLIENTONLY, without PW_RENDERFULLCONTENT: the window paints itself
        # into the bitmap at its own size (DWM's copy of a DPI-unaware window
        # comes scaled and smoothed)
        ok = user32.PrintWindow(h, mdc, 1 if client else 0)
        gdi32.GdiFlush()
        arr = np.ctypeslib.as_array((ctypes.c_ubyte * (w * hgt * 4)).from_address(bits.value)).reshape(hgt, w, 4)
        img = Image.fromarray(arr[:, :, [2, 1, 0]].copy(), 'RGB')
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, hdc)
        return img if ok else None

    # ---- the end -------------------------------------------------------------------
    def log(self):
        try:
            return self.log_path.read_text('latin-1').splitlines()
        except OSError:
            return []

    def capture_texts(self, h=None):
        """capture() and the text in the picture: what the window painted
        into the capture's bitmap, followed back through the sandbox's log
        (the text drawn into each bitmap since it was last cleared, and the
        text of the pictures copied into it)."""
        h = h or self.main
        t0 = tick() - 20
        img = self.capture(h)
        if img is None:
            return None
        # PrintWindow's painting shows as the window painting itself
        want = '%08x' % h
        got = []
        for _ in range(20):
            frames = {}   # bitmap -> (tick of its last clear, [texts since], size)
            got = None
            for line in self.log():
                parts = line.split(' ', 2)
                if len(parts) < 3:
                    continue
                kind, rest = parts[1], parts[2]
                if kind == 'show' and int(parts[0]) >= t0:
                    f = rest.split(' ')
                    if f[0].lower().rjust(8, '0') == want:
                        got = list(frames[f[1]][1]) if f[1] in frames else []
                        got += frames.get('w' + f[0], (0, []))[1]
                self._frame_line(frames, int(parts[0]), kind, rest)
            if got is not None:
                break
            time.sleep(0.05)   # the log is written as the tool goes
        img.info['texts'] = got or []
        return img

    @staticmethod
    def _frame_line(frames, tick, kind, rest):
        if kind == 'delete':
            frames.pop(rest.split()[0], None)
        elif kind == 'clear':
            f = rest.split()
            bmp, w, h = f[0], int(f[1]), int(f[2])
            src = f[4] if len(f) > 4 and f[3] == 'blit' else None
            frames[bmp] = (tick, list(frames[src][1]) if src in frames else [], (w, h))
        elif kind == 'blit':
            f = rest.split()
            dst, src = f[0], f[3]
            if src in frames:
                old = frames.get(dst, (tick, [], (int(f[1]), int(f[2]))))
                frames[dst] = (old[0], old[1] + frames[src][1], old[2])
        elif kind in ('text', 'drawtext'):
            head, text = rest.split('|', 1)
            f = head.split(' ')
            bmp, w, h, wnd = f[0], int(f[1]), int(f[2]), f[3]
            if wnd.strip('0') not in ('', '(nil)'):
                bmp = 'w' + wnd   # straight onto a window
            if kind == 'text':
                x, y, align, col, height, weight = int(f[4]), int(f[5]), int(f[6]), f[7], int(f[8]), int(f[9])
                face, r = ' '.join(f[10:]), None
            else:
                r = tuple(int(v) for v in f[4:8])
                x, y, align, col, height, weight = r[0], r[1], int(f[8]), f[9], int(f[10]), int(f[11])
                face = ' '.join(f[12:])
            c = int(col, 16)   # COLORREF: 00bbggrr
            item = dict(text=unescape(text), x=x, y=y, align=align, rect=r,
                        colour='#%02x%02x%02x' % (c & 255, c >> 8 & 255, c >> 16 & 255),
                        height=abs(height), weight=weight, face=face)
            frames.setdefault(bmp, (tick, [], (w, h)))[1].append(item)

    def texts(self, size, before=None, window=None):
        """The text in the picture a window shows (or, without one, the
        last picture of the given size the tool drew) before tick `before`,
        from the sandbox's log: the text drawn into that bitmap since it was
        last cleared, with the text of the pictures copied into it (dicts:
        text, x, y, colour, height, weight, face, align, rect)."""
        frames = {}   # bitmap -> (tick of its last clear, [texts since], size)
        shown = {}    # window -> the bitmap it showed last
        for line in self.log():
            parts = line.split(' ', 2)
            if len(parts) < 3:
                continue
            tick, kind, rest = int(parts[0]), parts[1], parts[2]
            if before is not None and tick > before:
                break
            if kind == 'clear':
                f = rest.split()
                bmp, w, h = f[0], int(f[1]), int(f[2])
                src = f[4] if len(f) > 4 and f[3] == 'blit' else None
                frames[bmp] = (tick, list(frames[src][1]) if src in frames else [], (w, h))
            elif kind == 'blit':
                f = rest.split()
                dst, src = f[0], f[3]
                if src in frames:
                    old = frames.get(dst, (tick, [], (int(f[1]), int(f[2]))))
                    frames[dst] = (old[0], old[1] + frames[src][1], old[2])
            elif kind == 'show':
                f = rest.split()
                shown[f[0]] = f[1]
            elif kind in ('text', 'drawtext'):
                head, text = rest.split('|', 1)
                f = head.split(' ')
                bmp, w, h, wnd = f[0], int(f[1]), int(f[2]), f[3]
                if wnd not in ('(nil)', '00000000', '0'):
                    bmp = 'w' + wnd
                if kind == 'text':
                    x, y, align, col, height, weight = int(f[4]), int(f[5]), int(f[6]), f[7], int(f[8]), int(f[9])
                    face, r = ' '.join(f[10:]), None
                else:
                    r = tuple(int(v) for v in f[4:8])
                    x, y, align, col, height, weight = r[0], r[1], int(f[8]), f[9], int(f[10]), int(f[11])
                    face = ' '.join(f[12:])
                c = int(col, 16)   # COLORREF: 00bbggrr
                item = dict(text=unescape(text), x=x, y=y, align=align, rect=r,
                            colour='#%02x%02x%02x' % (c & 255, c >> 8 & 255, c >> 16 & 255),
                            height=abs(height), weight=weight, face=face)
                frames.setdefault(bmp, (tick, [], (w, h)))[1].append(item)
        if window is not None:
            key = '%08X' % window
            for wnd, bmp in shown.items():
                if wnd.upper().lstrip('0X').rjust(8, '0') == key:
                    return list(frames.get(bmp, (0, [], None))[1]) + list(frames.get('w' + wnd, (0, []))[1])
        same = [v for v in frames.values() if v[2] == tuple(size)]
        best = max(same, key=lambda v: v[0], default=(0, [], None))
        return best[1]

    def close(self, timeout=5.0):
        """Asks the tool to close (its forms save their settings then) and
        stops exactly this process if it does not."""
        if self.proc.poll() is None:
            # like a user: the main window only (closing all at once makes
            # some of the tools fail as they shut down)
            for w in ([self.main] if self.main and user32.IsWindow(self.main) else self.windows()):
                user32.PostMessageW(w, WM_CLOSE, 0, 0)
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                pass
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(5)
        self.shared.mm.close()


user32.MapVirtualKeyW.restype = ctypes.c_uint
user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]

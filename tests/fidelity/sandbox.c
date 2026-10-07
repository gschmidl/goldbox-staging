/*
 * sandbox.c - the test-only part of the dbxapi32.dll that tests/fidelity runs
 * the original tools with (build.sh builds it into build/sandbox/). It is
 * never shipped.
 *
 * The tests run the originals against a fake DOSBox on the tester's desktop,
 * so when the DLL loads, everything that would reach outside the tool is
 * caught in the tool's import table:
 *  - no input is injected: keybd_event, SendInput, mouse_event and
 *    SetCursorPos are only logged;
 *  - no other program's window is shown, moved or brought to the front,
 *    SetForegroundWindow does nothing, no hotkey is registered; the tool's
 *    own windows go to the monitor named by DBXTEST_LEFT instead of the
 *    primary one;
 *  - the clipboard is not touched (what would be copied is logged), nothing
 *    is started (ShellExecuteA is logged), and no real process is opened
 *    (the DLL's own OpenProcess fails for every process the API does not
 *    serve).
 * The input state the tool sees comes from the test, through the shared
 * memory named by the environment variable DBXTEST: the cursor position,
 * the keys held down, the foreground window, the window under the cursor
 * (the tool's own windows only), the answers to message boxes and file
 * dialogs. Without it the cursor is far away and no key is down.
 * What was caught is appended to the file named by DBXTEST_LOG, a line each:
 * "<ms> <what> <details>".
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commdlg.h>
#include <shellapi.h>
#include <shlobj.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

/* The block the test shares with the tool (tests/fidelity/original.py). */
typedef struct {
	LONG cursor_x, cursor_y;    /* GetCursorPos, in the tool's coordinates */
	LONG foreground;            /* what GetForegroundWindow returns */
	LONG msgbox_answer;         /* the next MessageBoxA's result, 0 = OK/Yes */
	BYTE keys[256];             /* key states: 0x80 down, 0x01 toggled */
	char file_answer[MAX_PATH]; /* the next file/folder dialog's choice, "" = cancel */
	LONG msgbox_count;          /* message boxes shown so far */
} Shared;

static Shared fallback = {-32000, -32000, 0, 0, {0}, "", 0};
static Shared *sh = &fallback;
static CRITICAL_SECTION log_lock;
static char log_path[MAX_PATH];
static int hooked;

/* The log goes through a Win32 handle: the tool keeps drawing while the C
 * runtime shuts down at its exit, when C streams are closed already. */
static void note(const char *fmt, ...)
{
	static HANDLE f = INVALID_HANDLE_VALUE;
	static char line[70000];
	if (!log_path[0])
		return;
	EnterCriticalSection(&log_lock);
	if (f == INVALID_HANDLE_VALUE)
		f = CreateFileA(log_path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
		                NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
	if (f != INVALID_HANDLE_VALUE) {
		int n = _snprintf(line, sizeof line - 2, "%lu ", (unsigned long)GetTickCount());
		va_list ap;
		va_start(ap, fmt);
		int k = _vsnprintf(line + n, sizeof line - 2 - n, fmt, ap);
		va_end(ap);
		n = k < 0 ? (int)sizeof line - 2 : n + k;
		line[n++] = '\n';
		DWORD done;
		WriteFile(f, line, (DWORD)n, &done, NULL);
	}
	LeaveCriticalSection(&log_lock);
}

/* a string for the log: control characters as \xNN, at most n bytes */
static const char *esc(const char *s, char *buf, size_t n)
{
	size_t o = 0;
	if (!s)
		s = "(null)";
	for (; *s && o + 5 < n; s++) {
		unsigned char c = (unsigned char)*s;
		if (c < 32 || c == '\\')
			o += sprintf(buf + o, "\\x%02x", c);
		else
			buf[o++] = (char)c;
	}
	buf[o] = 0;
	return buf;
}

static int own_window(HWND h)
{
	DWORD pid = 0;
	if (!h)
		return 0;
	GetWindowThreadProcessId(h, &pid);
	return pid == GetCurrentProcessId();
}

/* The tests' windows belong on one monitor of the tester's (DBXTEST_LEFT = "x,y",
 * its top left corner): a window of the tool that would appear on the primary
 * monitor (a form centred on the screen, a message dialog, a form at its designed
 * place) goes there instead, by the same offset. */
static POINT left_origin;
static int have_left;

static void to_left(int *x, int *y, int w, int h)
{
	if (!have_left)
		return;
	RECT r = {*x, *y, *x + (w > 0 ? w : 1), *y + (h > 0 ? h : 1)};
	HMONITOR m = MonitorFromRect(&r, MONITOR_DEFAULTTONULL);
	MONITORINFO mi;
	mi.cbSize = sizeof mi;
	if (!m || !GetMonitorInfoA(m, &mi) || !(mi.dwFlags & MONITORINFOF_PRIMARY))
		return;
	*x += left_origin.x - mi.rcMonitor.left;
	*y += left_origin.y - mi.rcMonitor.top;
}

static int top_level(HWND h)
{
	return !(GetWindowLongA(h, GWL_STYLE) & WS_CHILD);
}

/* ---- input ---------------------------------------------------------------- */

static VOID WINAPI sb_keybd_event(BYTE vk, BYTE scan, DWORD flags, ULONG_PTR extra)
{
	(void)extra;
	note("keybd %u %u %lu", vk, scan, (unsigned long)flags);
}

static UINT WINAPI sb_SendInput(UINT n, LPINPUT in, int size)
{
	(void)size;
	for (UINT i = 0; i < n; i++) {
		if (in[i].type == INPUT_KEYBOARD)
			note("keybd %u %u %lu", in[i].ki.wVk, in[i].ki.wScan,
			     (unsigned long)in[i].ki.dwFlags);
		else
			note("input %lu", (unsigned long)in[i].type);
	}
	return n;
}

static VOID WINAPI sb_mouse_event(DWORD flags, DWORD dx, DWORD dy, DWORD data, ULONG_PTR extra)
{
	(void)extra;
	note("mouse %lu %lu %lu %lu", (unsigned long)flags, (unsigned long)dx,
	     (unsigned long)dy, (unsigned long)data);
}

static BOOL WINAPI sb_SetCursorPos(int x, int y)
{
	note("setcursor %d %d", x, y);
	sh->cursor_x = x;
	sh->cursor_y = y;
	return TRUE;
}

static BOOL WINAPI sb_GetCursorPos(LPPOINT p)
{
	if (!p)
		return FALSE;
	p->x = sh->cursor_x;
	p->y = sh->cursor_y;
	return TRUE;
}

static SHORT WINAPI sb_GetKeyState(int vk)
{
	BYTE k = sh->keys[vk & 0xFF];
	return (SHORT)((k & 0x80 ? 0x8000 : 0) | (k & 1));
}

static SHORT WINAPI sb_GetAsyncKeyState(int vk)
{
	return (SHORT)(sh->keys[vk & 0xFF] & 0x80 ? 0x8000 : 0);
}

static BOOL WINAPI sb_GetKeyboardState(PBYTE keys)
{
	memcpy(keys, sh->keys, 256);
	return TRUE;
}

/* the deepest visible child of one of the tool's own top-level windows */
typedef struct {
	POINT pt;
	HWND found;
} FindAt;

static BOOL CALLBACK find_top(HWND h, LPARAM l)
{
	FindAt *f = (FindAt *)l;
	RECT r;
	if (!IsWindowVisible(h) || !GetWindowRect(h, &r) || !PtInRect(&r, f->pt))
		return TRUE;
	HWND w = h;
	for (;;) {
		POINT c = f->pt;
		ScreenToClient(w, &c);
		HWND k = ChildWindowFromPointEx(w, c, CWP_SKIPINVISIBLE | CWP_SKIPTRANSPARENT);
		if (!k || k == w)
			break;
		w = k;
	}
	f->found = w;
	return FALSE;
}

static BOOL CALLBACK find_thread(HWND h, LPARAM l)
{
	DWORD pid = 0, tid = GetWindowThreadProcessId(h, &pid);
	if (pid != GetCurrentProcessId())
		return TRUE;
	FindAt *f = (FindAt *)l;
	EnumThreadWindows(tid, find_top, l);
	return f->found == NULL;
}

static HWND WINAPI sb_WindowFromPoint(POINT pt)
{
	FindAt f = {pt, NULL};
	EnumWindows(find_thread, (LPARAM)&f); /* top-level windows in Z order */
	return f.found;
}

/* ---- windows -------------------------------------------------------------- */

static HWND WINAPI sb_GetForegroundWindow(void)
{
	return (HWND)(LONG_PTR)sh->foreground;
}

static BOOL WINAPI sb_SetForegroundWindow(HWND h)
{
	note("setforeground %p%s", (void *)h, own_window(h) ? " own" : "");
	return TRUE;
}

static BOOL WINAPI sb_ShowWindow(HWND h, int cmd)
{
	if (own_window(h))
		return ShowWindow(h, cmd);
	note("showwindow %p %d", (void *)h, cmd);
	return TRUE;
}

static BOOL WINAPI sb_SetWindowPos(HWND h, HWND after, int x, int y, int cx, int cy, UINT flags)
{
	if (own_window(h)) {
		if (!(flags & SWP_NOMOVE) && top_level(h))
			to_left(&x, &y, cx, cy);
		return SetWindowPos(h, after, x, y, cx, cy, flags);
	}
	note("setwindowpos %p %d %d %d %d %u", (void *)h, x, y, cx, cy, flags);
	return TRUE;
}

static BOOL WINAPI sb_MoveWindow(HWND h, int x, int y, int w, int hgt, BOOL repaint)
{
	if (own_window(h)) {
		if (top_level(h))
			to_left(&x, &y, w, hgt);
		return MoveWindow(h, x, y, w, hgt, repaint);
	}
	note("movewindow %p %d %d %d %d", (void *)h, x, y, w, hgt);
	return TRUE;
}

static HWND WINAPI sb_CreateWindowExA(DWORD ex, LPCSTR cls, LPCSTR name, DWORD style, int x, int y, int w,
                                      int h, HWND parent, HMENU menu, HINSTANCE inst, LPVOID param)
{
	if (!(style & WS_CHILD) && x != CW_USEDEFAULT && y != CW_USEDEFAULT)
		to_left(&x, &y, w, h);
	return CreateWindowExA(ex, cls, name, style, x, y, w, h, parent, menu, inst, param);
}

static BOOL WINAPI sb_BringWindowToTop(HWND h)
{
	if (own_window(h))
		return BringWindowToTop(h);
	note("bringtotop %p", (void *)h);
	return TRUE;
}

static BOOL WINAPI sb_RegisterHotKey(HWND h, int id, UINT mods, UINT vk)
{
	(void)h;
	note("hotkey %d %u %u", id, mods, vk);
	return TRUE;
}

static BOOL WINAPI sb_UnregisterHotKey(HWND h, int id)
{
	(void)h;
	(void)id;
	return TRUE;
}

/* ---- dialogs -------------------------------------------------------------- */

static int WINAPI sb_MessageBoxA(HWND h, LPCSTR text, LPCSTR caption, UINT type)
{
	(void)h;
	char a[2048], b[256];
	int answer = sh->msgbox_answer;
	sh->msgbox_answer = 0;
	sh->msgbox_count++;
	if (!answer) {
		UINT kind = type & MB_TYPEMASK;
		answer = kind == MB_YESNO || kind == MB_YESNOCANCEL ? IDYES
		         : kind == MB_RETRYCANCEL ? IDRETRY
		         : kind == MB_ABORTRETRYIGNORE ? IDIGNORE : IDOK;
	}
	note("msgbox %u %d %s|%s", type, answer, esc(caption, b, sizeof b), esc(text, a, sizeof a));
	return answer;
}

static BOOL file_dialog(const char *kind, LPOPENFILENAMEA o)
{
	char a[512], b[512];
	note("%s %s|%s", kind, esc(o->lpstrFilter ? o->lpstrFilter : "", a, sizeof a),
	     esc(o->lpstrFile ? o->lpstrFile : "", b, sizeof b));
	if (!sh->file_answer[0] || !o->lpstrFile || o->nMaxFile <= strlen(sh->file_answer))
		return FALSE;
	strcpy(o->lpstrFile, sh->file_answer);
	sh->file_answer[0] = 0;
	return TRUE;
}

static BOOL WINAPI sb_GetOpenFileNameA(LPOPENFILENAMEA o)
{
	return file_dialog("openfile", o);
}

static BOOL WINAPI sb_GetSaveFileNameA(LPOPENFILENAMEA o)
{
	return file_dialog("savefile", o);
}

static PIDLIST_ABSOLUTE WINAPI sb_SHBrowseForFolderA(LPBROWSEINFOA bi)
{
	char a[256];
	note("browsefolder %s", esc(bi && bi->lpszTitle ? bi->lpszTitle : "", a, sizeof a));
	if (!sh->file_answer[0])
		return NULL;
	WCHAR w[MAX_PATH];
	MultiByteToWideChar(CP_ACP, 0, sh->file_answer, -1, w, MAX_PATH);
	sh->file_answer[0] = 0;
	return ILCreateFromPathW(w);
}

/* ---- clipboard, programs ------------------------------------------------------ */

static BOOL WINAPI sb_OpenClipboard(HWND h)
{
	(void)h;
	return TRUE;
}

static BOOL WINAPI sb_EmptyClipboard(void)
{
	return TRUE;
}

static BOOL WINAPI sb_CloseClipboard(void)
{
	return TRUE;
}

static HANDLE WINAPI sb_SetClipboardData(UINT format, HANDLE data)
{
	if (format == CF_TEXT && data) {
		const char *t = GlobalLock(data);
		static char buf[65536];
		note("clipboard %s", esc(t, buf, sizeof buf));
		GlobalUnlock(data);
	} else {
		note("clipboard format %u", format);
	}
	return data;
}

static HANDLE WINAPI sb_GetClipboardData(UINT format)
{
	(void)format;
	return NULL;
}

static HINSTANCE WINAPI sb_ShellExecuteA(HWND h, LPCSTR verb, LPCSTR file, LPCSTR params,
                                         LPCSTR dir, INT show)
{
	(void)h;
	(void)dir;
	char a[64], b[512], c[512];
	note("shell %s|%s|%s %d", esc(verb, a, sizeof a), esc(file, b, sizeof b),
	     esc(params, c, sizeof c), show);
	return (HINSTANCE)42;
}

/* ---- what the tool draws -------------------------------------------------------
 * Text and full clears of a bitmap are logged, so that the test knows what text
 * a picture holds: "text <bitmap> <w> <h> <window> <x> <y> <align> <colour>
 * <font height> <weight> <face>|<text>", "clear <bitmap> <w> <h> <colour>". */

static void dc_target(HDC dc, HBITMAP *bmp, LONG *w, LONG *h, HWND *wnd)
{
	BITMAP b;
	*bmp = (HBITMAP)GetCurrentObject(dc, OBJ_BITMAP);
	*w = *h = 0;
	if (*bmp && GetObjectA(*bmp, sizeof b, &b)) {
		*w = b.bmWidth;
		*h = b.bmHeight;
	}
	*wnd = WindowFromDC(dc);
}

static void log_text(HDC dc, int x, int y, const char *s, int n, const RECT *r, UINT format)
{
	static char buf[4096], text[1024];
	HBITMAP bmp;
	LONG w, h;
	HWND wnd;
	LOGFONTA lf;
	if (!log_path[0] || !s)
		return;
	if (n < 0)
		n = (int)strlen(s);
	if (n > (int)sizeof text - 1)
		n = sizeof text - 1;
	memcpy(text, s, n);
	text[n] = 0;
	dc_target(dc, &bmp, &w, &h, &wnd);
	memset(&lf, 0, sizeof lf);
	GetObjectA(GetCurrentObject(dc, OBJ_FONT), sizeof lf, &lf);
	if (r)
		note("drawtext %p %ld %ld %p %ld %ld %ld %ld %u %06lx %ld %ld %s|%s", (void *)bmp, w, h, (void *)wnd,
		     r->left, r->top, r->right, r->bottom, format, (unsigned long)GetTextColor(dc), lf.lfHeight,
		     lf.lfWeight, lf.lfFaceName, esc(text, buf, sizeof buf));
	else
		note("text %p %ld %ld %p %d %d %u %06lx %ld %ld %s|%s", (void *)bmp, w, h, (void *)wnd, x, y,
		     GetTextAlign(dc), (unsigned long)GetTextColor(dc), lf.lfHeight, lf.lfWeight, lf.lfFaceName,
		     esc(text, buf, sizeof buf));
}

static BOOL WINAPI sb_ExtTextOutA(HDC dc, int x, int y, UINT opts, const RECT *rc, LPCSTR s, UINT n,
                                  const INT *dx)
{
	log_text(dc, x, y, s, (int)n, NULL, 0);
	return ExtTextOutA(dc, x, y, opts, rc, s, n, dx);
}

static BOOL WINAPI sb_TextOutA(HDC dc, int x, int y, LPCSTR s, int n)
{
	log_text(dc, x, y, s, n, NULL, 0);
	return TextOutA(dc, x, y, s, n);
}

static int WINAPI sb_DrawTextA(HDC dc, LPCSTR s, int n, LPRECT r, UINT format)
{
	if (!(format & DT_CALCRECT))
		log_text(dc, 0, 0, s, n, r, format);
	return DrawTextA(dc, s, n, r, format);
}

/* A picture copied from one bitmap into another: "blit <to> <w> <h> <from>
 * <x> <y> <w> <h>"; over all of a bitmap it starts a new frame, which holds
 * the text of the copied picture. */
static void blit(HDC dc, int x, int y, int w, int h, HDC src)
{
	HBITMAP bmp, sbmp = NULL;
	LONG bw, bh, sw, sh;
	HWND wnd, swnd;
	if (!log_path[0])
		return;
	dc_target(dc, &bmp, &bw, &bh, &wnd);
	if (src)
		dc_target(src, &sbmp, &sw, &sh, &swnd);
	if (wnd) {
		/* onto a window: what it shows now */
		if (sbmp && !swnd)
			note("show %p %p %d %d %d %d", (void *)wnd, (void *)sbmp, x, y, w, h);
		return;
	}
	if (bw && x <= 0 && y <= 0 && x + w >= bw && y + h >= bh)
		note("clear %p %ld %ld blit %p", (void *)bmp, bw, bh, (void *)sbmp);
	else if (bw && sbmp && sbmp != bmp)
		note("blit %p %ld %ld %p %d %d %d %d", (void *)bmp, bw, bh, (void *)sbmp, x, y, w, h);
}

static BOOL WINAPI sb_BitBlt(HDC dc, int x, int y, int w, int h, HDC src, int sx, int sy, DWORD rop)
{
	blit(dc, x, y, w, h, src);
	return BitBlt(dc, x, y, w, h, src, sx, sy, rop);
}

static BOOL WINAPI sb_StretchBlt(HDC dc, int x, int y, int w, int h, HDC src, int sx, int sy, int sw, int sh,
                                 DWORD rop)
{
	blit(dc, x, y, w, h, src);
	return StretchBlt(dc, x, y, w, h, src, sx, sy, sw, sh, rop);
}

/* a deleted bitmap's handle may come back for a new one: "delete <bitmap>" */
static BOOL WINAPI sb_DeleteObject(HGDIOBJ h)
{
	if (log_path[0] && h && GetObjectType(h) == OBJ_BITMAP)
		note("delete %p", (void *)h);
	return DeleteObject(h);
}

static int WINAPI sb_FillRect(HDC dc, const RECT *r, HBRUSH brush)
{
	HBITMAP bmp;
	LONG w, h;
	HWND wnd;
	dc_target(dc, &bmp, &w, &h, &wnd);
	if (log_path[0] && w && r->left <= 0 && r->top <= 0 && r->right >= w && r->bottom >= h) {
		LOGBRUSH lb;
		memset(&lb, 0, sizeof lb);
		GetObjectA(brush, sizeof lb, &lb);
		note("clear %p %ld %ld %06lx", (void *)bmp, w, h, (unsigned long)lb.lbColor);
	}
	return FillRect(dc, r, brush);
}

/* VCL copies a bitmap it shares (TBitmap.Assign, then drawn on) into a new DIB section
 * with GetDIBits: the new section's bits are remembered as they are made, and a copy of
 * all of a bitmap into them is "clear <to> <w> <h> blit <from>" like a blit. */
static struct { void *bits; HBITMAP bmp; } sections[64];
static int next_section;

static HBITMAP WINAPI sb_CreateDIBSection(HDC dc, const BITMAPINFO *bi, UINT usage, void **bits, HANDLE sec,
                                          DWORD off)
{
	HBITMAP h = CreateDIBSection(dc, bi, usage, bits, sec, off);
	if (log_path[0] && h && bits && *bits) {
		EnterCriticalSection(&log_lock);
		for (int i = 0; i < 64; i++)   /* the memory of a deleted section comes back for new ones */
			if (sections[i].bits == *bits)
				sections[i].bits = NULL;
		sections[next_section].bits = *bits;
		sections[next_section].bmp = h;
		next_section = (next_section + 1) % 64;
		LeaveCriticalSection(&log_lock);
	}
	return h;
}

static int WINAPI sb_GetDIBits(HDC dc, HBITMAP bmp, UINT start, UINT lines, void *bits, BITMAPINFO *bi, UINT usage)
{
	int n = GetDIBits(dc, bmp, start, lines, bits, bi, usage);
	BITMAP b;
	if (log_path[0] && bits && n > 0 && start == 0 && GetObjectA(bmp, sizeof b, &b) && (LONG)lines >= b.bmHeight) {
		for (int i = 0; i < 64; i++) {
			if (sections[i].bits == bits && sections[i].bmp != bmp) {
				note("clear %p %ld %ld blit %p", (void *)sections[i].bmp, b.bmWidth, b.bmHeight, (void *)bmp);
				break;
			}
		}
	}
	return n;
}

/* ... and then a bitmap of its own made from a DIB section's bits (CreateDIBitmap, or
 * SetDIBits into one): a copy of the section */
static void from_section(HBITMAP h, const void *bits)
{
	BITMAP b;
	if (!log_path[0] || !h || !bits || !GetObjectA(h, sizeof b, &b))
		return;
	for (int i = 0; i < 64; i++) {
		if (sections[i].bits == bits && sections[i].bmp != h) {
			note("clear %p %ld %ld blit %p", (void *)h, b.bmWidth, b.bmHeight, (void *)sections[i].bmp);
			return;
		}
	}
}

static HBITMAP WINAPI sb_CreateDIBitmap(HDC dc, const BITMAPINFOHEADER *hdr, DWORD init, const void *bits,
                                        const BITMAPINFO *bi, UINT usage)
{
	HBITMAP h = CreateDIBitmap(dc, hdr, init, bits, bi, usage);
	if (init & CBM_INIT)
		from_section(h, bits);
	return h;
}

static int WINAPI sb_SetDIBits(HDC dc, HBITMAP bmp, UINT start, UINT lines, const void *bits, const BITMAPINFO *bi,
                               UINT usage)
{
	int n = SetDIBits(dc, bmp, start, lines, bits, bi, usage);
	if (n > 0 && start == 0)
		from_section(bmp, bits);
	return n;
}

/* ---- the DLL's own way out ---------------------------------------------------- */

/* The DLL calls the real OpenProcess for a process the API does not serve;
 * this module's own import entry is hooked, so the real one is kept here. */
static HANDLE(WINAPI *real_OpenProcess)(DWORD, BOOL, DWORD);

static HANDLE WINAPI sb_OpenProcess(DWORD access, BOOL inherit, DWORD pid)
{
	if (pid == GetCurrentProcessId() && real_OpenProcess)
		return real_OpenProcess(access, inherit, pid);
	note("openprocess %lu refused", (unsigned long)pid);
	SetLastError(ERROR_ACCESS_DENIED);
	return NULL;
}

/* ---- import table hooks ------------------------------------------------------- */

typedef struct {
	const char *dll, *name;
	void *hook;
} Hook;

static const Hook tool_hooks[] = {
	{"user32.dll", "keybd_event", (void *)sb_keybd_event},
	{"user32.dll", "SendInput", (void *)sb_SendInput},
	{"user32.dll", "mouse_event", (void *)sb_mouse_event},
	{"user32.dll", "SetCursorPos", (void *)sb_SetCursorPos},
	{"user32.dll", "GetCursorPos", (void *)sb_GetCursorPos},
	{"user32.dll", "GetKeyState", (void *)sb_GetKeyState},
	{"user32.dll", "GetAsyncKeyState", (void *)sb_GetAsyncKeyState},
	{"user32.dll", "GetKeyboardState", (void *)sb_GetKeyboardState},
	{"user32.dll", "WindowFromPoint", (void *)sb_WindowFromPoint},
	{"user32.dll", "GetForegroundWindow", (void *)sb_GetForegroundWindow},
	{"user32.dll", "SetForegroundWindow", (void *)sb_SetForegroundWindow},
	{"user32.dll", "ShowWindow", (void *)sb_ShowWindow},
	{"user32.dll", "SetWindowPos", (void *)sb_SetWindowPos},
	{"user32.dll", "MoveWindow", (void *)sb_MoveWindow},
	{"user32.dll", "CreateWindowExA", (void *)sb_CreateWindowExA},
	{"user32.dll", "BringWindowToTop", (void *)sb_BringWindowToTop},
	{"user32.dll", "RegisterHotKey", (void *)sb_RegisterHotKey},
	{"user32.dll", "UnregisterHotKey", (void *)sb_UnregisterHotKey},
	{"user32.dll", "MessageBoxA", (void *)sb_MessageBoxA},
	{"user32.dll", "OpenClipboard", (void *)sb_OpenClipboard},
	{"user32.dll", "EmptyClipboard", (void *)sb_EmptyClipboard},
	{"user32.dll", "CloseClipboard", (void *)sb_CloseClipboard},
	{"user32.dll", "SetClipboardData", (void *)sb_SetClipboardData},
	{"user32.dll", "GetClipboardData", (void *)sb_GetClipboardData},
	{"comdlg32.dll", "GetOpenFileNameA", (void *)sb_GetOpenFileNameA},
	{"comdlg32.dll", "GetSaveFileNameA", (void *)sb_GetSaveFileNameA},
	{"shell32.dll", "SHBrowseForFolderA", (void *)sb_SHBrowseForFolderA},
	{"shell32.dll", "ShellExecuteA", (void *)sb_ShellExecuteA},
	{"gdi32.dll", "ExtTextOutA", (void *)sb_ExtTextOutA},
	{"gdi32.dll", "TextOutA", (void *)sb_TextOutA},
	{"user32.dll", "DrawTextA", (void *)sb_DrawTextA},
	{"user32.dll", "FillRect", (void *)sb_FillRect},
	{"gdi32.dll", "BitBlt", (void *)sb_BitBlt},
	{"gdi32.dll", "StretchBlt", (void *)sb_StretchBlt},
	{"gdi32.dll", "DeleteObject", (void *)sb_DeleteObject},
	{"gdi32.dll", "CreateDIBSection", (void *)sb_CreateDIBSection},
	{"gdi32.dll", "GetDIBits", (void *)sb_GetDIBits},
	{"gdi32.dll", "CreateDIBitmap", (void *)sb_CreateDIBitmap},
	{"gdi32.dll", "SetDIBits", (void *)sb_SetDIBits},
};

static const Hook own_hooks[] = {
	{"kernel32.dll", "OpenProcess", (void *)sb_OpenProcess},
};

/* Points every import table entry of module mod that holds one of the hooked
 * functions at its hook; returns how many entries were changed. */
static int hook_module(HMODULE mod, const Hook *hooks, int n)
{
	void *real[64];
	for (int i = 0; i < n; i++) {
		HMODULE dll = GetModuleHandleA(hooks[i].dll);
		real[i] = dll ? (void *)GetProcAddress(dll, hooks[i].name) : NULL;
	}
	BYTE *base = (BYTE *)mod;
	IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
	IMAGE_DATA_DIRECTORY *dir = &nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
	if (!dir->VirtualAddress)
		return 0;
	int changed = 0;
	for (IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir->VirtualAddress);
	     d->Name; d++) {
		for (void **slot = (void **)(base + d->FirstThunk); *slot; slot++) {
			for (int i = 0; i < n; i++) {
				if (!real[i] || *slot != real[i])
					continue;
				DWORD old;
				if (VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &old)) {
					*slot = hooks[i].hook;
					VirtualProtect(slot, sizeof *slot, old, &old);
					changed++;
				}
				break;
			}
		}
	}
	return changed;
}

__attribute__((constructor)) static void sandbox_start(void)
{
	InitializeCriticalSection(&log_lock);
	DWORD n = GetEnvironmentVariableA("DBXTEST_LOG", log_path, sizeof log_path);
	if (!n || n >= sizeof log_path)
		log_path[0] = 0;
	char name[128];
	n = GetEnvironmentVariableA("DBXTEST", name, sizeof name);
	if (n && n < sizeof name) {
		HANDLE m = OpenFileMappingA(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, name);
		Shared *p = m ? (Shared *)MapViewOfFile(m, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0,
		                                        sizeof(Shared))
		              : NULL;
		if (p)
			sh = p;
	}
	char left[64];
	n = GetEnvironmentVariableA("DBXTEST_LEFT", left, sizeof left);
	if (n && n < sizeof left && sscanf(left, "%ld,%ld", &left_origin.x, &left_origin.y) == 2)
		have_left = 1;
	real_OpenProcess = (HANDLE(WINAPI *)(DWORD, BOOL, DWORD))(void *)GetProcAddress(
	        GetModuleHandleA("kernel32.dll"), "OpenProcess");
	HMODULE self = NULL;
	GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
	                       GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
	                   (LPCSTR)(void *)sandbox_start, &self);
	hooked = hook_module(GetModuleHandleA(NULL), tool_hooks,
	                     (int)(sizeof tool_hooks / sizeof *tool_hooks));
	int own = self ? hook_module(self, own_hooks, 1) : 0;
	note("sandbox %d tool imports, %d own, shared memory %s", hooked, own,
	     sh == &fallback ? "none" : "mapped");
}

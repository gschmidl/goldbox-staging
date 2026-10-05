/*
 * dbxapi32.dll - lets the 32-bit tools that read DOSBox's memory (Gold Box
 * Companion, The All-Seeing Eye, Ultimapper 5) work with DOSBox Staging 0.83+
 * through its HTTP API.
 *
 * The tools import OpenProcess/ReadProcessMemory/WriteProcessMemory (and
 * CreateFileA) through one kernel32 import descriptor, which is renamed to
 * this DLL; everything else in it is forwarded to kernel32.
 *
 * When a tool opens a DOSBox whose HTTP API answers on one of the ports that
 * DOSBox listens on, it gets a stand-in handle (to its own process) instead:
 * DOSBox is never opened. Reads and writes through that handle go to
 * /api/v1/memory, with the emulated machine's RAM shown as one block at
 * RAM_WINDOW (the start of the tools' default search range). Any other
 * process, e.g. a vanilla DOSBox 0.74, gets the real calls.
 *
 * Settings: dbxapi32.ini next to the DLL, section [dbxapi]:
 *   port=0  (0: find the API port; else only this port)  cache_ms=40  log=0
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock2.h>
#include <iphlpapi.h>
#include <winhttp.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Where the emulated RAM appears in the tool's address space: the start of
 * the tools' default search range. */
#define RAM_WINDOW 0x01000000u
/* The tools use signed 32-bit addresses. */
#define RAM_WINDOW_MAX (0x7FFFFFFFu - RAM_WINDOW)

#define BLOCK_SHIFT 18
#define BLOCK_SIZE  (1u << BLOCK_SHIFT)

/* How long a decision about which process the API serves is reused. */
#define SERVED_CACHE_MS 1000

/* Staging's default API ports, tried first: 0.83 used 8086, 0.84 8080. */
static const int usual_ports[] = {8086, 8080};

static CRITICAL_SECTION lock;
static char ini_path[MAX_PATH];
static char log_path[MAX_PATH];

static int cfg_port;          /* 0 = find it */
static DWORD cfg_cache_ms = 40;
static int cfg_log = 0;

static HINTERNET h_session, h_connect;
static int conn_port, conn_v6; /* where h_connect points */

static DWORD api_pid;      /* process attached through the API; 0 = none */
static int api_port, api_v6; /* where its API answers (kept after detach) */
static DWORD api_mem_size; /* bytes of emulated RAM shown */
static DWORD standin_pid;  /* process the stand-in handles stand for */
static DWORD retry_tick;   /* last attempt to re-attach to it */
static DWORD decided_pid, decided_tick;
static int decided_served;

typedef struct {
	DWORD tick;
	int valid;
	unsigned char *data;
} Block;
static Block *blocks;
static DWORD n_blocks;

static void dbg(const char *fmt, ...)
{
	if (!cfg_log)
		return;
	FILE *f = fopen(log_path, "a");
	if (!f)
		return;
	SYSTEMTIME t;
	GetLocalTime(&t);
	fprintf(f, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond,
	        t.wMilliseconds);
	va_list ap;
	va_start(ap, fmt);
	vfprintf(f, fmt, ap);
	va_end(ap);
	fputc('\n', f);
	fclose(f);
}

static void load_config(HMODULE self)
{
	GetModuleFileNameA(self, ini_path, sizeof ini_path);
	char *slash = strrchr(ini_path, '\\');
	if (slash)
		slash[1] = 0;
	strcpy(log_path, ini_path);
	strcat(log_path, "dbxapi32.log");
	strcat(ini_path, "dbxapi32.ini");

	cfg_port = GetPrivateProfileIntA("dbxapi", "port", 0, ini_path);
	cfg_cache_ms = GetPrivateProfileIntA("dbxapi", "cache_ms", 40, ini_path);
	cfg_log = GetPrivateProfileIntA("dbxapi", "log", 0, ini_path);

	const char *env = getenv("DBXAPI_PORT");
	if (env && *env)
		cfg_port = atoi(env);
}

/* ---- the ports a process listens on ------------------------------------ */

typedef struct {
	int port, v6, rank;
} Cand;
enum { MAX_CANDS = 32 };

/* dwLocalPort holds the port in network byte order */
static int row_port(DWORD p)
{
	return (int)(((p & 0xff) << 8) | ((p >> 8) & 0xff));
}

static int add_cand(Cand *c, int n, int port, int v6, int loopback)
{
	for (int i = 0; i < n; i++)
		if (c[i].port == port)
			return n;
	if (n == MAX_CANDS)
		return n;
	int rank = 2 + !loopback;
	for (int i = 0; i < (int)(sizeof usual_ports / sizeof *usual_ports); i++)
		if (port == usual_ports[i])
			rank = 0;
	c[n].port = port;
	c[n].v6 = v6;
	c[n].rank = rank;
	return n + 1;
}

/* TCP ports process pid listens on, reachable through the loopback address
 * (bound to it or to all addresses), Staging's usual API ports first.
 * Returns their number, or -1 if the TCP tables can't be read. */
static int listening_ports(DWORD pid, Cand *c)
{
	int n = 0;
	DWORD size = 0;
	if (GetExtendedTcpTable(NULL, &size, FALSE, AF_INET,
	                        TCP_TABLE_OWNER_PID_LISTENER,
	                        0) != ERROR_INSUFFICIENT_BUFFER)
		return -1;
	MIB_TCPTABLE_OWNER_PID *t4 = malloc(size);
	if (!t4 || GetExtendedTcpTable(t4, &size, FALSE, AF_INET,
	                               TCP_TABLE_OWNER_PID_LISTENER, 0) != NO_ERROR) {
		free(t4);
		return -1;
	}
	for (DWORD i = 0; i < t4->dwNumEntries; i++) {
		MIB_TCPROW_OWNER_PID *r = &t4->table[i];
		int loopback = r->dwLocalAddr == 0x0100007F; /* 127.0.0.1 */
		if (r->dwOwningPid == pid && (loopback || r->dwLocalAddr == 0))
			n = add_cand(c, n, row_port(r->dwLocalPort), 0, loopback);
	}
	free(t4);

	size = 0;
	if (GetExtendedTcpTable(NULL, &size, FALSE, AF_INET6,
	                        TCP_TABLE_OWNER_PID_LISTENER,
	                        0) == ERROR_INSUFFICIENT_BUFFER) {
		MIB_TCP6TABLE_OWNER_PID *t6 = malloc(size);
		if (t6 && GetExtendedTcpTable(t6, &size, FALSE, AF_INET6,
		                              TCP_TABLE_OWNER_PID_LISTENER,
		                              0) == NO_ERROR) {
			static const UCHAR any[16], one[16] = {[15] = 1};
			for (DWORD i = 0; i < t6->dwNumEntries; i++) {
				MIB_TCP6ROW_OWNER_PID *r = &t6->table[i];
				int loopback = !memcmp(r->ucLocalAddr, one, 16);
				if (r->dwOwningPid == pid &&
				    (loopback || !memcmp(r->ucLocalAddr, any, 16)))
					n = add_cand(c, n, row_port(r->dwLocalPort), 1, loopback);
			}
		}
		free(t6);
	}
	for (int i = 1; i < n; i++) /* stable sort by rank */
		for (int j = i; j > 0 && c[j - 1].rank > c[j].rank; j--) {
			Cand t = c[j];
			c[j] = c[j - 1];
			c[j - 1] = t;
		}
	return n;
}

static int listens_on(DWORD pid, int port)
{
	Cand c[MAX_CANDS];
	int n = listening_ports(pid, c);
	for (int i = 0; i < n; i++)
		if (c[i].port == port)
			return 1;
	return n < 0; /* can't tell: assume it does */
}

/* ---- HTTP ------------------------------------------------------------- */

static void http_reset(void)
{
	if (h_connect)
		WinHttpCloseHandle(h_connect);
	if (h_session)
		WinHttpCloseHandle(h_session);
	h_connect = h_session = NULL;
}

static int http_open(int port, int v6)
{
	if (h_connect && conn_port == port && conn_v6 == v6)
		return 1;
	http_reset();
	h_session = WinHttpOpen(L"dbxapi32/1.0", WINHTTP_ACCESS_TYPE_NO_PROXY,
	                        WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
	if (!h_session)
		return 0;
	WinHttpSetTimeouts(h_session, 2000, 2000, 5000, 5000);
	h_connect = WinHttpConnect(h_session, v6 ? L"[::1]" : L"127.0.0.1",
	                           (INTERNET_PORT)port, 0);
	if (!h_connect) {
		http_reset();
		return 0;
	}
	conn_port = port;
	conn_v6 = v6;
	return 1;
}

/* Performs a request to the API at port/v6 and returns the HTTP status (0
 * on transport failure). Up to out_max bytes of the response body go to
 * out. `quick` uses short timeouts (for probing ports). */
static DWORD http_request(int port, int v6, const WCHAR *verb, const WCHAR *path,
                          const void *body, DWORD body_len, void *out,
                          DWORD out_max, DWORD *out_len, int quick)
{
	if (out_len)
		*out_len = 0;
	if (!http_open(port, v6))
		return 0;

	HINTERNET req = WinHttpOpenRequest(h_connect, verb, path, NULL,
	                                   WINHTTP_NO_REFERER,
	                                   WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
	if (!req)
		return 0;
	if (quick)
		WinHttpSetTimeouts(req, 500, 500, 1000, 1000);
	/* Staging accepts "localhost" for loopback and all-address binds */
	WCHAR host[32];
	swprintf(host, 32, L"Host: localhost:%d", port);
	WinHttpAddRequestHeaders(req, host, (DWORD)-1L,
	                         WINHTTP_ADDREQ_FLAG_ADD | WINHTTP_ADDREQ_FLAG_REPLACE);

	const WCHAR *hdr = body ? L"Content-Type: application/octet-stream\r\n"
	                        : WINHTTP_NO_ADDITIONAL_HEADERS;
	DWORD status = 0;
	if (!WinHttpSendRequest(req, hdr, body ? (DWORD)-1L : 0, (void *)body,
	                        body_len, body_len, 0) ||
	    !WinHttpReceiveResponse(req, NULL)) {
		if (!quick)
			dbg("request %ls failed, error %lu", path, GetLastError());
		WinHttpCloseHandle(req);
		http_reset();
		return 0;
	}
	DWORD sz = sizeof status;
	WinHttpQueryHeaders(req, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
	                    WINHTTP_HEADER_NAME_BY_INDEX, &status, &sz,
	                    WINHTTP_NO_HEADER_INDEX);
	DWORD got = 0;
	for (;;) {
		char scratch[4096];
		DWORD avail = 0, n = 0;
		if (!WinHttpQueryDataAvailable(req, &avail) || avail == 0)
			break;
		if (out && got < out_max) {
			DWORD want = out_max - got;
			if (want > avail)
				want = avail;
			if (!WinHttpReadData(req, (char *)out + got, want, &n))
				break;
			got += n;
		} else {
			if (avail > sizeof scratch)
				avail = sizeof scratch;
			if (!WinHttpReadData(req, scratch, avail, &n))
				break;
		}
	}
	if (out_len)
		*out_len = got;
	WinHttpCloseHandle(req);
	return status;
}

static int api_read(DWORD linear, void *buf, DWORD len)
{
	WCHAR path[96];
	swprintf(path, 96, L"/api/v1/memory/0x%lx/%lu", (unsigned long)linear,
	         (unsigned long)len);
	DWORD got = 0;
	return http_request(api_port, api_v6, L"GET", path, NULL, 0, buf, len,
	                    &got, 0) == 200 &&
	       got == len;
}

static int api_write(DWORD linear, const void *buf, DWORD len)
{
	WCHAR path[64];
	swprintf(path, 64, L"/api/v1/memory/0x%lx", (unsigned long)linear);
	return http_request(api_port, api_v6, L"PUT", path, buf, len, NULL, 0,
	                    NULL, 0) == 200;
}

/* Is the DOSBox Staging HTTP API at this port? */
static int probe_api(int port, int v6)
{
	char body[1024];
	DWORD got = 0;
	DWORD status = http_request(port, v6, L"GET", L"/api/v1/dosbox/info", NULL,
	                            0, body, sizeof body - 1, &got, 1);
	body[got] = 0;
	return status == 200 && strstr(body, "\"version\"") != NULL;
}

/* Finds the port where process pid's API answers: among the ports it
 * listens on, or (TCP tables unavailable) the usual ones. */
static int find_api(DWORD pid, int *port, int *v6)
{
	Cand c[MAX_CANDS];
	int n = listening_ports(pid, c);
	if (n < 0) {
		n = 0;
		for (int i = 0; i < (int)(sizeof usual_ports / sizeof *usual_ports); i++)
			n = add_cand(c, n, usual_ports[i], 0, 1);
	}
	for (int i = 0; i < n; i++) {
		if (cfg_port && c[i].port != cfg_port)
			continue;
		int ok = probe_api(c[i].port, c[i].v6);
		dbg("pid %lu: port %d%s %s", pid, c[i].port, c[i].v6 ? " (IPv6)" : "",
		    ok ? "is the API" : "is not the API");
		if (ok) {
			*port = c[i].port;
			*v6 = c[i].v6;
			return 1;
		}
	}
	return 0;
}

/* ---- attaching ---------------------------------------------------------- */

static void drop_cache(void)
{
	for (DWORD i = 0; i < n_blocks; i++)
		free(blocks[i].data);
	free(blocks);
	blocks = NULL;
	n_blocks = 0;
}

static void detach(void)
{
	if (api_pid)
		dbg("detached from pid %lu", api_pid);
	api_pid = 0;
	api_mem_size = 0;
	decided_pid = 0;
	drop_cache();
}

/* Emulated RAM size: the API rejects reads past its end. */
static DWORD probe_mem_size(void)
{
	unsigned char b;
	if (!api_read(0, &b, 1))
		return 0;
	DWORD lo = 1, hi = 0; /* lo: known readable size */
	for (DWORD s = 1u << 20; s && s <= 0x80000000u; s <<= 1) {
		if (api_read(s - 1, &b, 1))
			lo = s;
		else {
			hi = s;
			break;
		}
	}
	while (hi && hi - lo > 1) { /* smallest unreadable size in (lo, hi] */
		DWORD mid = lo + (hi - lo) / 2;
		if (api_read(mid - 1, &b, 1))
			lo = mid;
		else
			hi = mid;
	}
	return lo;
}

static int attach(DWORD pid, int port, int v6)
{
	detach();
	api_port = port;
	api_v6 = v6;
	DWORD size = probe_mem_size();
	if (!size)
		return 0;
	api_mem_size = size < RAM_WINDOW_MAX ? size : RAM_WINDOW_MAX;
	n_blocks = (api_mem_size + BLOCK_SIZE - 1) >> BLOCK_SHIFT;
	blocks = calloc(n_blocks, sizeof *blocks);
	if (!blocks)
		return 0;
	api_pid = pid;
	dbg("pid %lu: API on port %d%s, %lu bytes of emulated RAM at 0x%08lx", pid,
	    port, v6 ? " (IPv6)" : "", size, (unsigned long)RAM_WINDOW);
	return 1;
}

/* tools/patch_tools.py gives tools with far-pointer converters a RAM base
 * variable behind this marker: 0 = convert as before (DOSBox 0.74 layout),
 * else the address where guest linear 0 appears, minus the tools' 0x20 bias. */
static const char rambase_marker[16] = "dbxapi32:rambase";
static volatile DWORD *rambase_var;
static int rambase_searched;

static void set_rambase(int served)
{
	if (!rambase_searched) {
		rambase_searched = 1;
		BYTE *image = (BYTE *)GetModuleHandleA(NULL);
		IMAGE_NT_HEADERS *nt =
		        (IMAGE_NT_HEADERS *)(image + ((IMAGE_DOS_HEADER *)image)->e_lfanew);
		IMAGE_SECTION_HEADER *s = IMAGE_FIRST_SECTION(nt);
		for (int i = 0; i < nt->FileHeader.NumberOfSections && !rambase_var; i++, s++) {
			if (!(s->Characteristics & IMAGE_SCN_MEM_WRITE))
				continue;
			BYTE *p = image + s->VirtualAddress;
			DWORD n = s->Misc.VirtualSize;
			for (DWORD k = 0; k + sizeof rambase_marker + 4 <= n; k += 4)
				if (!memcmp(p + k, rambase_marker, sizeof rambase_marker)) {
					rambase_var = (volatile DWORD *)(p + k + sizeof rambase_marker);
					break;
				}
		}
		dbg("RAM base variable %s", rambase_var ? "found" : "not present");
	}
	if (rambase_var)
		*rambase_var = served ? RAM_WINDOW - 0x20 : 0;
}

/* Does the API serve this process? (Caller holds the lock.)
 * A DOSBox attached before stays served while it still listens on its API
 * port -- if the API is just busy, reads fail rather than reaching the real
 * process. */
static int serves_pid(DWORD pid)
{
	DWORD now = GetTickCount();
	if (pid == decided_pid && now - decided_tick < SERVED_CACHE_MS)
		return decided_served;

	int port = 0, v6 = 0, served;
	if (pid == api_pid && listens_on(pid, api_port)) {
		served = 1; /* still attached */
	} else if ((served = find_api(pid, &port, &v6)) != 0) {
		if (!attach(pid, port, v6))
			dbg("pid %lu: API on port %d doesn't serve memory", pid, port);
	} else if (pid == standin_pid && api_port && listens_on(pid, api_port)) {
		served = 1; /* busy */
	} else {
		if (pid == api_pid)
			detach();
		if (pid != decided_pid || decided_served)
			dbg("pid %lu: no DOSBox Staging API on its ports", pid);
	}
	decided_pid = pid;
	decided_tick = now;
	decided_served = served;
	if (served)
		standin_pid = pid;
	set_rambase(served);
	return served;
}

/* Reads and writes through a stand-in after the API stopped answering: like
 * a real handle, it keeps working once the same DOSBox answers again. Tools
 * that open the process once per session (ASE) depend on this. */
static int ensure_attached(void)
{
	if (api_pid)
		return 1;
	DWORD now = GetTickCount();
	if (!standin_pid || now - retry_tick < SERVED_CACHE_MS)
		return 0;
	retry_tick = now;
	int port = api_port, v6 = api_v6;
	if (!port || !listens_on(standin_pid, port))
		if (!find_api(standin_pid, &port, &v6))
			return 0; /* that DOSBox is gone */
	return attach(standin_pid, port, v6);
}

/* Stand-ins are handles to the tool's own process, which the tools never
 * read or write otherwise. */
static int is_standin(HANDLE process)
{
	return GetProcessId(process) == GetCurrentProcessId();
}

static int in_window(DWORD addr, DWORD len)
{
	if (addr < RAM_WINDOW)
		return 0;
	DWORD off = addr - RAM_WINDOW;
	return off < api_mem_size && len <= api_mem_size - off;
}

static Block *get_block(DWORD i)
{
	Block *b = &blocks[i];
	DWORD now = GetTickCount();
	if (b->valid && now - b->tick <= cfg_cache_ms)
		return b;
	if (!b->data && !(b->data = malloc(BLOCK_SIZE)))
		return NULL;
	DWORD start = i << BLOCK_SHIFT;
	DWORD len = api_mem_size - start < BLOCK_SIZE ? api_mem_size - start
	                                              : BLOCK_SIZE;
	if (!api_read(start, b->data, len)) {
		b->valid = 0;
		return NULL;
	}
	b->valid = 1;
	b->tick = now;
	return b;
}

/* ---- the redirected calls ------------------------------------------------ */

HANDLE WINAPI Shim_OpenProcess(DWORD access, BOOL inherit, DWORD pid)
{
	EnterCriticalSection(&lock);
	int served = serves_pid(pid);
	LeaveCriticalSection(&lock);
	if (!served)
		return OpenProcess(access, inherit, pid);

	HANDLE h = NULL;
	if (!DuplicateHandle(GetCurrentProcess(), GetCurrentProcess(),
	                     GetCurrentProcess(), &h,
	                     PROCESS_QUERY_LIMITED_INFORMATION, inherit, 0))
		return NULL;
	return h;
}

BOOL WINAPI Shim_ReadProcessMemory(HANDLE process, LPCVOID address,
                                   LPVOID buffer, SIZE_T size, SIZE_T *read)
{
	if (!is_standin(process))
		return ReadProcessMemory(process, address, buffer, size, read);

	EnterCriticalSection(&lock);
	DWORD addr = (DWORD)(UINT_PTR)address;
	BOOL ok = FALSE;
	if (read)
		*read = 0;
	if (!ensure_attached()) {
		/* the API doesn't answer (DOSBox closed or busy) */
	} else if (size == 0) {
		ok = TRUE;
	} else if (in_window(addr, (DWORD)size)) {
		DWORD off = addr - RAM_WINDOW, done = 0;
		ok = TRUE;
		while (done < size) {
			DWORD pos = off + done;
			Block *b = get_block(pos >> BLOCK_SHIFT);
			if (!b) {
				ok = FALSE;
				break;
			}
			DWORD in_blk = pos & (BLOCK_SIZE - 1);
			DWORD n = BLOCK_SIZE - in_blk;
			if (n > size - done)
				n = (DWORD)size - done;
			memcpy((char *)buffer + done, b->data + in_blk, n);
			done += n;
		}
		if (!ok) /* the API stopped answering */
			detach();
	}
	if (ok && read)
		*read = size;
	LeaveCriticalSection(&lock);
	if (!ok)
		SetLastError(ERROR_PARTIAL_COPY);
	return ok;
}

BOOL WINAPI Shim_WriteProcessMemory(HANDLE process, LPVOID address,
                                    LPCVOID buffer, SIZE_T size,
                                    SIZE_T *written)
{
	if (!is_standin(process))
		return WriteProcessMemory(process, address, buffer, size, written);

	EnterCriticalSection(&lock);
	DWORD addr = (DWORD)(UINT_PTR)address;
	BOOL ok = FALSE;
	if (written)
		*written = 0;
	if (!ensure_attached()) {
		/* the API doesn't answer (DOSBox closed or busy) */
	} else if (size == 0) {
		ok = TRUE;
	} else if (in_window(addr, (DWORD)size)) {
		DWORD off = addr - RAM_WINDOW;
		ok = api_write(off, buffer, (DWORD)size);
		dbg("write 0x%lx (+%lu) -> %s", off, (unsigned long)size,
		    ok ? "ok" : "FAILED");
		/* keep cached blocks coherent */
		for (DWORD done = 0; ok && done < size;) {
			DWORD pos = off + done;
			Block *b = &blocks[pos >> BLOCK_SHIFT];
			DWORD in_blk = pos & (BLOCK_SIZE - 1);
			DWORD n = BLOCK_SIZE - in_blk;
			if (n > size - done)
				n = (DWORD)size - done;
			if (b->valid)
				memcpy(b->data + in_blk, (const char *)buffer + done, n);
			done += n;
		}
	}
	if (ok && written)
		*written = size;
	LeaveCriticalSection(&lock);
	if (!ok)
		SetLastError(ERROR_PARTIAL_COPY);
	return ok;
}

/* DOSBox Staging opens every game file on the host with write access, even
 * when the game only reads it (vanilla 0.74 used the DOS open mode). The
 * tools open game files read-only with fmShareDenyWrite, which Windows
 * refuses while such a handle exists, so read-only opens also allow other
 * writers. */
HANDLE WINAPI Shim_CreateFileA(LPCSTR name, DWORD access, DWORD share,
                               LPSECURITY_ATTRIBUTES sa, DWORD disposition,
                               DWORD flags, HANDLE template_file)
{
	if (!(access & (GENERIC_WRITE | GENERIC_ALL | FILE_WRITE_DATA |
	                FILE_APPEND_DATA)))
		share |= FILE_SHARE_READ | FILE_SHARE_WRITE;
	return CreateFileA(name, access, share, sa, disposition, flags,
	                   template_file);
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
	(void)reserved;
	if (reason == DLL_PROCESS_ATTACH) {
		DisableThreadLibraryCalls(inst);
		InitializeCriticalSection(&lock);
		load_config(inst);
		if (cfg_port)
			dbg("loaded: API port %d, RAM window 0x%08lx, cache %lu ms", cfg_port,
			    (unsigned long)RAM_WINDOW, cfg_cache_ms);
		else
			dbg("loaded: API port found per DOSBox, RAM window 0x%08lx, cache %lu ms",
			    (unsigned long)RAM_WINDOW, cfg_cache_ms);
	}
	return TRUE;
}

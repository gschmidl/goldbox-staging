/*
 * dlltest.exe PID - exercises dbxapi32.dll the way the tools do: through
 * OpenProcess/ReadProcessMemory/WriteProcessMemory imported from it.
 * Needs a running DOSBox Staging with the HTTP API (PID = its process id).
 * Writes only to a scratch area of the BIOS data area's intra-application
 * communications area (0040:00F0, 16 bytes) and restores it.
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define RAM_WINDOW 0x01000000u
#define ICA        0x4F0u /* linear address of 0040:00F0 */

/* the DLL's exports, called the way the patched tools call them */
static HANDLE(WINAPI *pOpenProcess)(DWORD, BOOL, DWORD);
static BOOL(WINAPI *pRead)(HANDLE, LPCVOID, LPVOID, SIZE_T, SIZE_T *);
static BOOL(WINAPI *pWrite)(HANDLE, LPVOID, LPCVOID, SIZE_T, SIZE_T *);
#define OpenProcess pOpenProcess
#define ReadProcessMemory pRead
#define WriteProcessMemory pWrite

static int failures;

static void check(int ok, const char *what)
{
	printf("%-58s %s\n", what, ok ? "ok" : "FAILED");
	if (!ok)
		failures++;
}

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: dlltest PID\n");
		return 2;
	}
	DWORD pid = strtoul(argv[1], NULL, 0);
	HMODULE dll = LoadLibraryA("dbxapi32.dll");
	if (!dll) {
		fprintf(stderr, "dbxapi32.dll not found\n");
		return 2;
	}
	pOpenProcess = (void *)GetProcAddress(dll, "OpenProcess");
	pRead = (void *)GetProcAddress(dll, "ReadProcessMemory");
	pWrite = (void *)GetProcAddress(dll, "WriteProcessMemory");
	if (!pOpenProcess || !pRead || !pWrite) {
		fprintf(stderr, "dbxapi32.dll lacks the shimmed exports\n");
		return 2;
	}
	HANDLE h = OpenProcess(PROCESS_ALL_ACCESS, FALSE, pid);
	check(h != NULL, "OpenProcess(DOSBox) returns a handle");
	check(GetProcessId(h) == GetCurrentProcessId(),
	      "...a stand-in for our own process (DOSBox never opened)");

	unsigned char ivt[8], buf[16], saved[16], pat[16];
	SIZE_T n = 0;
	check(ReadProcessMemory(h, (LPCVOID)(UINT_PTR)RAM_WINDOW, ivt, 8, &n) && n == 8,
	      "read guest linear 0 (interrupt vector table)");

	check(!ReadProcessMemory(h, (LPCVOID)(UINT_PTR)(RAM_WINDOW - 4), buf, 4, &n) &&
	          n == 0 && GetLastError() == ERROR_PARTIAL_COPY,
	      "read just below the window fails (ERROR_PARTIAL_COPY)");
	check(!ReadProcessMemory(h, (LPCVOID)(UINT_PTR)0x7FFFFF00u, buf, 16, &n) && n == 0,
	      "read far above guest RAM fails");

	/* write / read back / cache coherence / restore */
	LPVOID ica = (LPVOID)(UINT_PTR)(RAM_WINDOW + ICA);
	check(ReadProcessMemory(h, ica, saved, 16, &n) && n == 16, "read 0040:00F0");
	for (int i = 0; i < 16; i++)
		pat[i] = (unsigned char)(0xA5 ^ i);
	check(WriteProcessMemory(h, ica, pat, 16, &n) && n == 16, "write 16 bytes at 0040:00F0");
	memset(buf, 0, sizeof buf);
	check(ReadProcessMemory(h, ica, buf, 16, &n) && !memcmp(buf, pat, 16),
	      "read back immediately (cached block updated)");
	Sleep(200); /* past the cache lifetime: comes from DOSBox again */
	memset(buf, 0, sizeof buf);
	check(ReadProcessMemory(h, ica, buf, 16, &n) && !memcmp(buf, pat, 16),
	      "read back after the cache expired (value is in DOSBox)");
	check(WriteProcessMemory(h, ica, saved, 16, &n) && n == 16, "restore 0040:00F0");

	/* a read spanning two 256 KB cache blocks */
	static unsigned char big[0x9000];
	DWORD span = 0x40000 - 0x4000;
	check(ReadProcessMemory(h, (LPCVOID)(UINT_PTR)(RAM_WINDOW + span), big,
	                        sizeof big, &n) && n == sizeof big,
	      "read 36 KB across a cache block boundary");

	/* the scanner's pattern: many 0x7800-byte reads */
	DWORD t0 = GetTickCount(), reads = 0;
	for (DWORD a = RAM_WINDOW; a < RAM_WINDOW + 0x2000000u; a += 0x7800 - 0x40, reads++)
		if (!ReadProcessMemory(h, (LPCVOID)(UINT_PTR)a, big, 0x7800, &n))
			break;
	printf("scanned 32 MB in %lu reads, %lu ms\n", reads, GetTickCount() - t0);

	/* a process that isn't the API's gets the real calls: a suspended copy
	 * of this program, whose image starts with "MZ" at 0x400000 */
	STARTUPINFOA si = {sizeof si};
	PROCESS_INFORMATION pi;
	char cmd[MAX_PATH + 16];
	GetModuleFileNameA(NULL, cmd, MAX_PATH);
	if (CreateProcessA(cmd, NULL, NULL, NULL, FALSE, CREATE_SUSPENDED, NULL, NULL,
	                   &si, &pi)) {
		HANDLE other = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
		                           FALSE, pi.dwProcessId);
		char mz[2] = {0};
		check(other && GetProcessId(other) == pi.dwProcessId &&
		          ReadProcessMemory(other, (LPCVOID)0x400000, mz, 2, &n) &&
		          mz[0] == 'M' && mz[1] == 'Z',
		      "other processes still get the real calls");
		CloseHandle(other);
		TerminateProcess(pi.hProcess, 0);
		CloseHandle(pi.hThread);
		CloseHandle(pi.hProcess);
	} else {
		check(0, "start a child process for the real-call test");
	}
	CloseHandle(h);

	printf("%s (%d failure%s)\n", failures ? "FAILED" : "all ok", failures,
	       failures == 1 ? "" : "s");
	return failures != 0;
}

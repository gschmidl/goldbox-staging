/*
 * busytest.exe PID MS RAMSIZE - reads through dbxapi32.dll like a tool
 * polling a game: every 50 ms, 16 bytes at linear 0x400 and 16 bytes near
 * the end of the RAMSIZE bytes of emulated RAM, for MS milliseconds. Prints
 * one line per read, "<GetTickCount> <low|high> ok|FAIL". tests/busytest.py
 * runs it against a fake API that turns busy (as Staging's does while its
 * window is dragged) and checks the result.
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

#define RAM_WINDOW 0x01000000u

static HANDLE(WINAPI *pOpenProcess)(DWORD, BOOL, DWORD);
static BOOL(WINAPI *pRead)(HANDLE, LPCVOID, LPVOID, SIZE_T, SIZE_T *);

int main(int argc, char **argv)
{
	if (argc < 4) {
		fprintf(stderr, "usage: busytest PID MS RAMSIZE\n");
		return 2;
	}
	DWORD pid = strtoul(argv[1], NULL, 0), ms = strtoul(argv[2], NULL, 0);
	DWORD ram = strtoul(argv[3], NULL, 0);
	HMODULE dll = LoadLibraryA("dbxapi32.dll");
	if (!dll) {
		fprintf(stderr, "dbxapi32.dll not found\n");
		return 2;
	}
	pOpenProcess = (void *)GetProcAddress(dll, "OpenProcess");
	pRead = (void *)GetProcAddress(dll, "ReadProcessMemory");
	HANDLE h = pOpenProcess(PROCESS_ALL_ACCESS, FALSE, pid);
	if (!h || GetProcessId(h) != GetCurrentProcessId()) {
		fprintf(stderr, "no stand-in handle for pid %lu\n", pid);
		return 2;
	}
	for (DWORD t0 = GetTickCount(); GetTickCount() - t0 < ms; Sleep(50)) {
		unsigned char buf[16];
		SIZE_T n;
		BOOL low = pRead(h, (LPCVOID)(UINT_PTR)(RAM_WINDOW + 0x400), buf, 16, &n);
		printf("%lu low %s\n", GetTickCount(), low ? "ok" : "FAIL");
		BOOL high = pRead(h, (LPCVOID)(UINT_PTR)(RAM_WINDOW + ram - 0x1000), buf, 16, &n);
		printf("%lu high %s\n", GetTickCount(), high ? "ok" : "FAIL");
		fflush(stdout);
	}
	CloseHandle(h);
	return 0;
}

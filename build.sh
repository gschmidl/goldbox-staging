#!/bin/sh
# Builds dbxapi32.dll and the DLL test into build/ with a 32-bit MinGW-w64
# cross compiler (i686-w64-mingw32-gcc, e.g. from a Linux/WSL package).
set -e
cd "$(dirname "$0")"
CC=${CC:-i686-w64-mingw32-gcc}
mkdir -p build
"$CC" -O2 -Wall -Wextra -shared -o build/dbxapi32.dll \
    src/dbxapi32.c src/dbxapi32.def \
    -lwinhttp -liphlpapi -static-libgcc -Wl,--enable-stdcall-fixup -s
"$CC" -O2 -Wall -o build/dlltest.exe tests/dlltest.c \
    -Wl,--image-base=0x400000 -Wl,--disable-dynamicbase -static-libgcc
"$CC" -O2 -Wall -o build/busytest.exe tests/busytest.c -static-libgcc
echo "built build/dbxapi32.dll, build/dlltest.exe and build/busytest.exe"

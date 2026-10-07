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
# the same DLL with the test sandbox (tests/fidelity, not in the release zip), never shipped
if [ -f tests/fidelity/sandbox.c ]; then
    mkdir -p build/sandbox
    "$CC" -O2 -Wall -Wextra -shared -o build/sandbox/dbxapi32.dll \
        src/dbxapi32.c tests/fidelity/sandbox.c src/dbxapi32.def \
        -lwinhttp -liphlpapi -lshell32 -lgdi32 -static-libgcc -Wl,--enable-stdcall-fixup -s
    echo "built build/sandbox/dbxapi32.dll"
fi

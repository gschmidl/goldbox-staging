"""gen_def.py OUT.def EXE... - writes dbxapi32.def for the given tools.

Exports every function of the redirected kernel32 import descriptor of each
EXE: the shimmed ones go to Shim_*, all others are forwarded to kernel32.
"""
import sys

import pefile

SHIMS = {"OpenProcess": 12, "ReadProcessMemory": 20,
         "WriteProcessMemory": 20, "CreateFileA": 28}
WANT = {b"ReadProcessMemory", b"WriteProcessMemory", b"OpenProcess"}

names = set()
for path in sys.argv[2:]:
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        got = {i.name for i in e.imports if i.name}
        if e.dll.lower() in (b"kernel32.dll", b"dbxapi32.dll") and got & WANT:
            names |= {n.decode() for n in got}
missing = set(SHIMS) - names
assert not missing, f"not imported: {missing}"
with open(sys.argv[1], "w", newline="\n") as out:
    out.write("LIBRARY dbxapi32.dll\nEXPORTS\n")
    for n in sorted(SHIMS):
        out.write(f"    {n}=Shim_{n}@{SHIMS[n]}\n")
    for n in sorted(names - set(SHIMS)):
        out.write(f"    {n}=kernel32.{n}\n")
print(f"{len(names)} exports")

"""Patch Joonas Hirvonen's DOSBox companion tools for DOSBox Staging.

Supported builds (checked by MD5; anything else is refused):
  GBC 2.65 (10-Jun-2021): GBC.exe, GBC_Audio.exe, ECL_Monitor.exe, FRUA_Tool.exe
  The All-Seeing Eye 1.10: ASE.exe (the May 2020 release and eXo's Nov 2020 build)
  The All-Seeing Eye 3 0.12: ASE3.exe
  Ultimapper 5: Ultimapper_5.exe (Release 4, Feb 2024, and eXo's Nov 2020 build)

1. Import redirect: the kernel32.dll import descriptor that holds
   ReadProcessMemory/WriteProcessMemory/OpenProcess is renamed to
   "dbxapi32.dll" (same length). dbxapi32.dll serves those calls through
   DOSBox Staging's HTTP API and forwards the rest to kernel32.

2. Far-pointer converters (GBC, GBC_Audio, ECL_Monitor): they turn the
   game's seg:off pointers into addresses with the *program* base found by
   the ID search, which is only right where DOSBox 0.74 loaded the game.
   Each converter's 'mov eax,[pBase]; add REG,[eax]' becomes a jump to a
   stub in the code section's slack:

       call L / L: pop eax                ; position-independent
       cmp  dword [eax+RAMBASE], 0
       je   orig
       add  REG, [eax+RAMBASE]            ; set by dbxapi32.dll when it serves
       jmp  back                          ;   the process through the API
   orig:
       mov  eax, [eax+pBase]              ; otherwise the original code:
       add  REG, [eax]                    ;   vanilla 0.74/ECE keep working
       jmp  back

   RAMBASE is a dword in the data section's slack, right after the marker
   b"dbxapi32:rambase", where dbxapi32.dll finds it.

3. Preset window title "DOSBox 0.74" (Ultimapper: "DOSBox 0.74-2.1") ->
   "DOSBox": matches DOSBox 0.74, ECE and DOSBox Staging (with
   window_titlebar dosbox=always) alike. Only used when a tool creates fresh
   settings.

usage: patch_tools.py EXE [EXE...]     (patches in place, keeps EXE.orig)
       patch_tools.py --revert EXE...  (restores from EXE.orig)
"""
import hashlib
import os
import shutil
import struct
import sys

import pefile

NEW_DLL = b"dbxapi32.dll"
WANT = {b"ReadProcessMemory", b"WriteProcessMemory", b"OpenProcess"}
MARKER = b"dbxapi32:rambase"

# Far-pointer converters as (virtual address, original 7 bytes). Each computes
# seg*16 + off + 0x20 + [program base]; found by auditing every use of the
# program base in each tool (all other uses are program-relative).
_GBC_CONV = [(0xA30F9, "a12c3b0c000310"), (0xA31FE, "a12c3b0c000338"),
             (0xA329B, "a12c3b0c000330")]
_GBCA_CONV = [(0xA30F9, "a12c5b0c000310"), (0xA31FE, "a12c5b0c000338"),
              (0xA329B, "a12c5b0c000330")]
_ECL_CONV = [(0x7337F, "a1145308000330")]

OLD_TITLE, NEW_TITLE = b"DOSBox 0.74", b"DOSBox"
GOG_TITLE = b"DOSBox 0.74-2.1"

# md5 of the original -> (description, converters, kind of title preset, title)
#   "short": Delphi short string constant in code
#   "ansi":  Delphi long string constant in code
#   "dfm":   string property in a form resource
BUILDS = {
    "aa4de265b04f15a11364244286598c1a": ("GBC.exe 2.65", _GBC_CONV, "short", OLD_TITLE),
    "e327e8f1be62f489b9bd044635515c7e": ("GBC_Audio.exe 2.65", _GBCA_CONV, "short", OLD_TITLE),
    "6da192aec2a93279f72a1c711a5a8d81": ("ECL_Monitor.exe 2.65", _ECL_CONV, "short", OLD_TITLE),
    "5846a8bae5b52a2c144577a9aca64838": ("FRUA_Tool.exe 2.65", [], "short", OLD_TITLE),
    "409fa97b89d374a8ea8f1bc7965ff523": ("ASE.exe 1.10 (May 2020)", [], "ansi", OLD_TITLE),
    "812dade225794f20230f3ab07b304449": ("ASE.exe 1.10 (eXo, Nov 2020)", [], "ansi", OLD_TITLE),
    "c0d90966b8e528e0b5a5241e3c0f7a74": ("ASE3.exe 0.12", [], "dfm", OLD_TITLE),
    "40a3d9fe5931525f68e36f1a99f25e02": ("Ultimapper_5.exe Release 4 (Feb 2024)", [], "ansi", GOG_TITLE),
    "4bf0f9e9550ff874f667258d8e368293": ("Ultimapper_5.exe (eXo, Nov 2020)", [], "ansi", GOG_TITLE),
}

# modrm of 'add REG,[eax]' -> modrm of 'add REG,[eax+disp32]'
_DISP32 = {0x10: 0x90, 0x38: 0xB8, 0x30: 0xB0}  # edx, edi, esi


def _section(pe, name):
    for s in pe.sections:
        if s.Name.rstrip(b"\0") == name:
            return s
    raise LookupError(name)


def _redirect_imports(pe, data, path):
    hits = [e for e in pe.DIRECTORY_ENTRY_IMPORT
            if e.dll.lower() == b"kernel32.dll"
            and {i.name for i in e.imports if i.name} & WANT]
    assert len(hits) == 1, f"{path}: expected one process-memory import descriptor"
    e = hits[0]
    off = pe.get_offset_from_rva(e.struct.Name)
    assert data[off:off + 13].lower() == b"kernel32.dll\0"
    assert not [d for d in pe.DIRECTORY_ENTRY_IMPORT
                if d is not e and d.struct.Name == e.struct.Name]
    data[off:off + 12] = NEW_DLL
    print(f"{path}: imports -> {NEW_DLL.decode()}")


def _grow(data, sect, need):
    """Claims `need` bytes of a section's raw slack; returns their RVA."""
    start = (sect.Misc_VirtualSize + 15) & ~15
    assert start + need <= sect.SizeOfRawData, f"no room in {sect.Name}"
    slack = data[sect.PointerToRawData + start:sect.PointerToRawData + start + need]
    assert not any(slack), f"slack of {sect.Name} is not empty"
    hdr = sect.get_file_offset() + 8  # Misc_VirtualSize
    data[hdr:hdr + 4] = struct.pack("<I", start + need)
    sect.Misc_VirtualSize = start + need
    return sect.VirtualAddress + start


def _patch_converters(pe, data, path, sites):
    if not sites:
        return
    sites = [(va, bytes.fromhex(orig)) for va, orig in sites]
    base = pe.OPTIONAL_HEADER.ImageBase
    code, dat = _section(pe, b"CODE"), _section(pe, b"DATA")
    for va, orig in sites:
        off = pe.get_offset_from_rva(va - base)
        assert bytes(data[off:off + 7]) == orig, f"{path}: unexpected bytes at {va:#x}"

    var_rva = _grow(data, dat, len(MARKER) + 4) + len(MARKER)
    voff = pe.get_offset_from_rva(var_rva - len(MARKER))
    data[voff:voff + len(MARKER) + 4] = MARKER + b"\0\0\0\0"

    relocs = {}
    if hasattr(pe, "DIRECTORY_ENTRY_BASERELOC"):
        for block in pe.DIRECTORY_ENTRY_BASERELOC:
            for entry in block.entries:
                relocs[entry.rva] = entry

    stub_len = 39
    stubs_rva = _grow(data, code, stub_len * len(sites))
    for i, (va, orig) in enumerate(sites):
        site_rva = va - base
        pbase_rva = struct.unpack("<I", orig[1:5])[0] - base
        modrm = orig[6]
        stub_rva = stubs_rva + i * stub_len
        label = stub_rva + 5  # after the call
        back = site_rva + 7

        def rel(src_end, dst):
            return struct.pack("<i", dst - src_end)

        stub = bytearray()
        stub += b"\xe8\0\0\0\0" + b"\x58"                                 # call L; L: pop eax
        stub += b"\x83\xb8" + struct.pack("<i", var_rva - label) + b"\0"  # cmp [eax+v], 0
        stub += b"\x74\x0b"                                               # je orig
        stub += bytes([0x03, _DISP32[modrm]]) + struct.pack("<i", var_rva - label)
        stub += b"\xe9" + rel(stub_rva + len(stub) + 5, back)             # jmp back
        stub += b"\x8b\x80" + struct.pack("<i", pbase_rva - label)        # orig: mov eax,[eax+p]
        stub += bytes([0x03, modrm])                                      # add REG,[eax]
        stub += b"\xe9" + rel(stub_rva + len(stub) + 5, back)             # jmp back
        assert len(stub) == stub_len
        soff = pe.get_offset_from_rva(stub_rva)
        data[soff:soff + stub_len] = stub

        off = pe.get_offset_from_rva(site_rva)
        data[off:off + 7] = b"\xe9" + rel(site_rva + 5, stub_rva) + b"\x90\x90"
        # the replaced 'mov eax,[pBase]' had an absolute-address fixup
        for r in range(site_rva, site_rva + 7):
            entry = relocs.get(r)
            if entry and entry.type != 0:
                woff = entry.struct.get_file_offset()
                word = struct.unpack("<H", data[woff:woff + 2])[0]
                data[woff:woff + 2] = struct.pack("<H", word & 0x0FFF)
        print(f"{path}: converter at {va:#x} -> stub at {base + stub_rva:#x}")
    print(f"{path}: RAM base variable at {base + var_rva:#x}")


def _only(data, needle, path):
    pos = data.find(needle)
    assert pos != -1 and data.find(needle, pos + 1) == -1, \
        f"{path}: expected exactly one {needle!r}"
    return pos


def _patch_title(pe, data, path, kind, old):
    if kind == "short":
        pos = _only(data, bytes([len(old)]) + old, path)
        data[pos] = len(NEW_TITLE)
    elif kind == "ansi":
        pos = _only(data, struct.pack("<I", len(old)) + old + b"\0", path)
        data[pos:pos + 4] = struct.pack("<I", len(NEW_TITLE))
        data[pos + 4 + len(NEW_TITLE)] = 0
    else:  # "dfm": a vaString property; the form resource shrinks
        needle = b"\x06" + bytes([len(old)]) + old
        pos = _only(data, needle, path)
        res = None
        for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            for n in t.directory.entries:
                for lang in n.directory.entries:
                    entry = lang.data.struct
                    start = pe.get_offset_from_rva(entry.OffsetToData)
                    if start <= pos < start + entry.Size:
                        res = (entry, start)
        assert res, f"{path}: title preset not inside a resource"
        entry, start = res
        end = start + entry.Size
        cut = len(old) - len(NEW_TITLE)
        new = b"\x06" + bytes([len(NEW_TITLE)]) + NEW_TITLE
        data[pos:end] = new + data[pos + len(needle):end] + bytes(cut)
        size_off = entry.get_file_offset() + 4  # IMAGE_RESOURCE_DATA_ENTRY.Size
        data[size_off:size_off + 4] = struct.pack("<I", entry.Size - cut)
    print(f"{path}: preset window title -> {NEW_TITLE.decode()!r}")


def patch(path):
    if not os.path.exists(path + ".orig"):
        shutil.copy2(path, path + ".orig")
    src = path + ".orig"
    raw = open(src, "rb").read()
    build = BUILDS.get(hashlib.md5(raw).hexdigest())
    if not build:
        raise SystemExit(f"{path}: unsupported build (md5 {hashlib.md5(raw).hexdigest()}); "
                         "supported: " + ", ".join(b[0] for b in BUILDS.values()))
    desc, converters, title_kind, title = build
    print(f"{path}: {desc}")
    pe = pefile.PE(data=raw)
    data = bytearray(raw)
    _redirect_imports(pe, data, path)
    _patch_converters(pe, data, path, converters)
    _patch_title(pe, data, path, title_kind, title)
    pe.close()
    open(path, "wb").write(data)


def revert(path):
    if os.path.exists(path + ".orig"):
        shutil.move(path + ".orig", path)
        print(f"{path}: restored")


def main(argv):
    if argv and argv[0] == "--revert":
        for p in argv[1:]:
            revert(p)
    else:
        for p in argv:
            patch(p)


if __name__ == "__main__":
    main(sys.argv[1:])

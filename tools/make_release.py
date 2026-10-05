"""make_release.py --gbc DIR --ase FILE [FILE...] --ase3 FILE --ultimapper FILE [FILE...]
                  [--zip OUT.zip]

Maintainer tool: patches the original builds with patch_tools.py and
fix_gamedat.py (both need pefile), records the byte changes per build in
../patches.json for patch.py, and optionally builds the release zip.

  --gbc   a GBC 2.65 folder (GBC.exe, GBC_Audio.exe, ECL_Monitor.exe,
          FRUA_Tool.exe and Games\\...\\Game.dat)
  --ase   ASE.exe builds (1.10)
  --ase3  ASE3.exe (0.12)
  --ultimapper  Ultimapper_5.exe builds
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import fix_gamedat  # noqa: E402
import patch_tools  # noqa: E402

GBC_EXES = ["GBC.exe", "GBC_Audio.exe", "ECL_Monitor.exe", "FRUA_Tool.exe"]


def changes(old, new, gap=8):
    """Runs of changed bytes as [offset, hex]; runs closer than `gap` merge."""
    assert len(old) == len(new)
    runs, i, n = [], 0, len(old)
    while i < n:
        if old[i] == new[i]:
            i += 1
            continue
        start = end = i
        while i < n:
            if old[i] != new[i]:
                end = i
                i += 1
            elif i - end <= gap:
                i += 1
            else:
                break
        runs.append([start, new[start:end + 1].hex()])
    return runs


def entry(name, orig_path, patched_path, description):
    old = open(orig_path, "rb").read()
    new = open(patched_path, "rb").read()
    return {"file": name, "description": description, "size": len(old),
            "md5": hashlib.md5(old).hexdigest(),
            "patched_md5": hashlib.md5(new).hexdigest(),
            "changes": changes(old, new)}


def describe(path):
    return patch_tools.BUILDS[hashlib.md5(open(path, "rb").read()).hexdigest()][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gbc", required=True)
    ap.add_argument("--ase", nargs="+", required=True)
    ap.add_argument("--ase3", required=True)
    ap.add_argument("--ultimapper", nargs="+", required=True)
    ap.add_argument("--zip", help="write the release zip here")
    args = ap.parse_args()

    files = []
    with tempfile.TemporaryDirectory() as tmp:
        gbc = os.path.join(tmp, "GBC")
        for name in GBC_EXES + [f"Games/{g}/Game.dat" for g in fix_gamedat.FIXES]:
            dst = os.path.join(gbc, *name.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(args.gbc, *name.split("/")), dst)
        for exe in GBC_EXES:
            path = os.path.join(gbc, exe)
            desc = describe(path)
            patch_tools.patch(path)
            files.append(entry(exe, path + ".orig", path, desc))
        fix_gamedat.main(gbc)
        for g in fix_gamedat.FIXES:
            path = os.path.join(gbc, "Games", g, "Game.dat")
            files.append(entry(f"Games/{g}/Game.dat", path + ".orig", path,
                               f"Game.dat of {g[4:]}"))
        for i, src in enumerate(args.ase + [args.ase3] + args.ultimapper):
            name = os.path.basename(src)
            path = os.path.join(tmp, f"exe{i}", name)
            os.makedirs(os.path.dirname(path))
            shutil.copy2(src, path)
            desc = describe(path)
            patch_tools.patch(path)
            files.append(entry(name, path + ".orig", path, desc))

    with open(os.path.join(ROOT, "patches.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"files": files}, f, indent=1)
        f.write("\n")
    print(f"patches.json: {len(files)} files, "
          f"{sum(len(e['changes']) for e in files)} changed runs")

    if args.zip:
        top = os.path.splitext(os.path.basename(args.zip))[0]
        content = {
            "README.md": "README.md", "patch.py": "patch.py",
            "patches.json": "patches.json", "dbxapi32.dll": "build/dbxapi32.dll",
            "gbc_staging.conf": "conf/gbc_staging.conf",
            "source/build.sh": "build.sh",
            "source/src/dbxapi32.c": "src/dbxapi32.c",
            "source/src/dbxapi32.def": "src/dbxapi32.def",
            "source/tests/dlltest.c": "tests/dlltest.c",
            "source/tests/porttest.ps1": "tests/porttest.ps1",
        }
        for t in ("patch_tools.py", "fix_gamedat.py", "gen_def.py", "make_release.py"):
            content[f"source/tools/{t}"] = f"tools/{t}"
        with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as z:
            for arc, src in content.items():
                z.write(os.path.join(ROOT, src), f"{top}/{arc}")
        print(f"{args.zip}: {len(content)} files")


if __name__ == "__main__":
    main()

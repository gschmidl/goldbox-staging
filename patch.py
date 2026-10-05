"""patch.py DIR [DIR...] [--check | --revert]

Makes Gold Box Companion 2.65, The All-Seeing Eye 1.10, The All-Seeing Eye 3
0.12 and Ultimapper 5 work with DOSBox Staging 0.83+ through its HTTP API.
They keep working with DOSBox 0.74 and ECE. Needs only Python 3.

DIR is a folder with the tools (a GBC, ASE, ASE3 or Ultimapper5 folder) or one
with such subfolders, like eXoDOS's util folder. Every supported file found
there is patched (the original is kept as *.orig) and dbxapi32.dll is put next
to the patched programs. Files of other versions are left alone. A window
title like "DOSBox ECE" saved in ASE.dat or ASE3.dat becomes "DOSBox".

  --check   only show what would be done
  --revert  put the *.orig files back and remove dbxapi32.dll
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DLL = "dbxapi32.dll"
# next to patch.py in the release, in build/ in the source tree
DLL_SOURCE = next((p for p in (os.path.join(HERE, DLL), os.path.join(HERE, "build", DLL))
                   if os.path.isfile(p)), None)


NEW_TITLE = "DOSBox"  # matches DOSBox Staging, 0.74 and ECE alike
ASE3_TITLE = 0xC9     # the title's string[] in ASE3.dat's 424-byte record


def md5(data):
    return hashlib.md5(data).hexdigest()


def stale_title(title):
    return title.startswith("DOSBox") and title != NEW_TITLE and "Staging" not in title


def fix_ase_dat(data):
    """ASE.dat: CRLF lines, the 4th is the window title."""
    lines = data.split(b"\r\n")
    if len(lines) < 4 or not stale_title(lines[3].decode("latin-1")):
        return None
    old = lines[3].decode("latin-1")
    lines[3] = NEW_TITLE.encode()
    return old, b"\r\n".join(lines)


def fix_ase3_dat(data):
    if len(data) != 424:
        return None
    n = data[ASE3_TITLE]
    old = data[ASE3_TITLE + 1:ASE3_TITLE + 1 + n].decode("latin-1")
    if not stale_title(old):
        return None
    field = bytes([len(NEW_TITLE)]) + NEW_TITLE.encode() + bytes(n - len(NEW_TITLE))
    return old, data[:ASE3_TITLE] + field + data[ASE3_TITLE + 1 + n:]


SETTINGS = {"ASE.dat": fix_ase_dat, "ASE3.dat": fix_ase3_dat}


def fix_settings(folder, check):
    for name, fix in SETTINGS.items():
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        result = fix(open(path, "rb").read())
        if not result:
            continue
        old, data = result
        print(f"{path}: {'would change' if check else 'changing'} the saved window "
              f"title \"{old}\" to \"{NEW_TITLE}\"")
        if not check:
            if not os.path.exists(path + ".orig"):
                shutil.copy2(path, path + ".orig")
            with open(path, "wb") as f:
                f.write(data)


def load_patches():
    with open(os.path.join(HERE, "patches.json"), encoding="utf-8") as f:
        return json.load(f)["files"]


def tool_folders(root, programs):
    for sub in ("", "GBC", "ASE", "ASE3", "Ultimapper5"):
        folder = os.path.normpath(os.path.join(root, sub))
        if any(os.path.isfile(os.path.join(folder, p)) for p in programs):
            yield folder


def plan_folder(folder, patches):
    """Returns [(path, entry or None, state)], state: patch / done / unsupported."""
    plan = []
    for name in sorted({p["file"] for p in patches}):
        path = os.path.join(folder, *name.split("/"))
        if not os.path.isfile(path):
            continue
        digest = md5(open(path, "rb").read())
        variants = [p for p in patches if p["file"] == name]
        entry = next((p for p in variants if digest == p["md5"]), None)
        if entry:
            plan.append((path, entry, "patch"))
            continue
        entry = next((p for p in variants if digest == p["patched_md5"]), None)
        plan.append((path, entry, "done" if entry else "unsupported"))
    return plan


def apply_entry(path, entry):
    data = bytearray(open(path, "rb").read())
    for offset, hexbytes in entry["changes"]:
        new = bytes.fromhex(hexbytes)
        data[offset:offset + len(new)] = new
    if md5(data) != entry["patched_md5"]:
        raise SystemExit(f"{path}: patch result does not match - nothing written")
    if not os.path.exists(path + ".orig"):
        shutil.copy2(path, path + ".orig")
    with open(path, "wb") as f:
        f.write(data)


def patch(folder, patches, check):
    plan = plan_folder(folder, patches)
    programs = [(p, e, s) for p, e, s in plan if p.lower().endswith(".exe")]
    bad = [p for p, e, s in programs if s == "unsupported"]
    if bad:
        for p in bad:
            print(f"{p}: unsupported version, folder left unchanged")
        return False
    for path, entry, state in plan:
        if state == "unsupported":
            print(f"{path}: unknown version, left unchanged")
        elif state == "done":
            print(f"{path}: already patched ({entry['description']})")
        else:
            print(f"{path}: {'would patch' if check else 'patching'} {entry['description']}")
            if not check:
                apply_entry(path, entry)
    if programs:
        fix_settings(folder, check)
    if programs and not check:
        shutil.copy2(DLL_SOURCE, os.path.join(folder, DLL))
        print(f"{os.path.join(folder, DLL)}: installed")
    return True


def revert(folder, patches, check):
    for name in sorted({p["file"] for p in patches} | set(SETTINGS)):
        path = os.path.join(folder, *name.split("/"))
        if os.path.isfile(path + ".orig"):
            print(f"{path}: {'would restore' if check else 'restoring'} the original")
            if not check:
                shutil.move(path + ".orig", path)
    dll = os.path.join(folder, DLL)
    if os.path.isfile(dll):
        print(f"{dll}: {'would remove' if check else 'removing'}")
        if not check:
            os.remove(dll)
    return True


def main():
    ap = argparse.ArgumentParser(
        description="Patch Gold Box Companion, The All-Seeing Eye and Ultimapper 5 "
                    "for DOSBox Staging.")
    ap.add_argument("dirs", nargs="+", metavar="DIR",
                    help="folder with the tools, or one with GBC, ASE, ASE3 and "
                         "Ultimapper5 subfolders")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="only show what would be done")
    group.add_argument("--revert", action="store_true", help="restore the original files")
    args = ap.parse_args()

    if not args.revert and not DLL_SOURCE:
        sys.exit(f"{DLL} not found next to patch.py - nothing changed")
    patches = load_patches()
    programs = sorted({p["file"] for p in patches if "/" not in p["file"]})
    ok = True
    for root in args.dirs:
        folders = list(tool_folders(root, programs))
        if not folders:
            print(f"{root}: none of {', '.join(programs)} found")
            ok = False
        for folder in folders:
            if args.revert:
                ok &= revert(folder, patches, args.check)
            else:
                ok &= patch(folder, patches, args.check)
    if ok and not args.revert and not args.check:
        print("Done. In DOSBox Staging turn on the webserver and keep \"DOSBox Staging\" "
              "in the title - see gbc_staging.conf.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

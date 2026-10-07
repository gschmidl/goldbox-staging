"""run.py - runs the original tools and the pages on the same game states and
compares what they show and do.

  python tests/fidelity/run.py --games DIR [--ultimapper DIR] [--gbc DIR]
                               [--ase DIR] [--ase3 DIR] [--only NAME,...]
                               [--work DIR] [--out DIR]

--games is a folder with the games' folders as eXoDOS names them (ultima5,
eob1, eob2, eob3, poolrad, ...); the tool options name the original tools'
folders (unpatched or patched: a copy is patched for the test). Tools left
out are not tested. --only picks sessions (u5:town, or u5 for all of them).

Needs Windows (the originals are run there, sandboxed: build.sh builds
build/sandbox/dbxapi32.dll), Python with Pillow and numpy, and Microsoft Edge
or Chrome (BROWSER names another). The originals' windows appear on the
left monitor; they get no real input. Pictures of every difference go to
--out (default: <work>/out)."""
import argparse
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fakedosbox  # noqa: E402
import harness  # noqa: E402
import page  # noqa: E402

TOOLS = {
    'u5': ('ultimapper', 'ultima5', 'u5'),
    'ase1': ('ase', 'eob1', 'ase'),
    'ase2': ('ase', 'eob2', 'ase'),
    'ase3': ('ase3', 'eob3', 'ase3'),
    # Gold Box Companion with each of its games (eXoDOS's folders), FRUA last
    **{f'gbc{g}': ('gbc', name, 'gbc') for g, name in ((1, 'poolrad'), (2, 'curse'), (3, 'secsilbl'), (4, 'pooldark'),
                                                         (5, 'ckrynn'), (6, 'dkkrynn'), (7, 'drkqueen'), (8, 'gatesf'),
                                                         (9, 'treassav'), (11, 'brcdoom'), (12, 'brmatrix'), (10, 'unlimadv'))},
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--games', required=True)
    ap.add_argument('--ultimapper')
    ap.add_argument('--gbc')
    ap.add_argument('--ase')
    ap.add_argument('--ase3')
    ap.add_argument('--only', default='')
    ap.add_argument('--work')
    ap.add_argument('--out')
    a = ap.parse_args()
    if not harness.SANDBOX_DLL.is_file():
        sys.exit(f'{harness.SANDBOX_DLL} is missing: run build.sh first')
    work = Path(a.work or tempfile.mkdtemp(prefix='fidelity-'))
    work.mkdir(parents=True, exist_ok=True)
    out = Path(a.out or work / 'out')
    only = [o for o in a.only.split(',') if o]
    fake = fakedosbox.FakeDosbox(f'DOSBox Staging fidelity test {os.getpid()}', mem_size=1 << 20)
    browser = page.Browser()
    browser.inject((HERE / 'instrument.js').read_text('utf-8'))
    results = []
    try:
        for key, (opt, game, modname) in TOOLS.items():
            tool_dir = getattr(a, opt)
            if not tool_dir or (only and not any(o == key or o.startswith(key + ':') for o in only)):
                continue
            mod = __import__(modname)
            print(f'== {key}: preparing', flush=True)
            run = mod.Run(work, tool_dir, Path(a.games) / game, fake, browser, out)
            for name, fn in mod.SESSIONS.items():
                if only and key not in only and f'{key}:{name}' not in only:
                    continue
                t0 = time.monotonic()
                res = harness.run_session(f'{key}-{name}', fn, [lambda: mod.Original(run), lambda: mod.Page(run)], out)
                results.append(res)
                print(f'{"ok  " if res.ok else "DIFF"} {key}:{name} ({time.monotonic() - t0:.0f} s)', flush=True)
                for item, ok, detail in res.items:
                    if not ok:
                        print(f'    {item}: {detail}', flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        browser.close()
        fake.close()
    bad = [r for r in results if not r.ok]
    print(f'{len(results) - len(bad)} of {len(results)} sessions the same; pictures of the differences in {out}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()

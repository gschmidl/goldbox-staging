# Gold Box Companion, The All-Seeing Eye and Ultimapper 5 on DOSBox Staging

Makes Joonas Hirvonen's companion tools work with DOSBox Staging 0.83 and
later, through its HTTP API. Supported versions (checked by checksum):

| Tool | Files |
|---|---|
| Gold Box Companion 2.65 (10-Jun-2021) | `GBC.exe`, `GBC_Audio.exe`, `ECL_Monitor.exe`, `FRUA_Tool.exe` |
| The All-Seeing Eye 1.10 (EOB 1 and 2) | `ASE.exe`: the May 2020 release, and eXoDOS's November 2020 build |
| The All-Seeing Eye 3 0.12 (EOB 3) | `ASE3.exe` |
| Ultimapper 5 (Ultima V) | `Ultimapper_5.exe`: Release 4 (Feb 2024), and eXoDOS's November 2020 build |

Everything the tools read or write goes through `/api/v1/memory`. The DOSBox
process is never opened and nothing depends on DOSBox internals, so later
Staging versions keep working as long as that API does. The patched tools
still work with vanilla DOSBox 0.74 and DOSBox ECE, unchanged.

## Using it

Everything needed is in the release zip (`patch.py`, `patches.json`,
`dbxapi32.dll`, `gbc_staging.conf`), on the
[releases page](https://github.com/gschmidl/goldbox-staging/releases).

1. **Patch the tools** (needs Python 3, nothing else):

   ```
   python patch.py <GBC folder> <ASE folder> <Ultimapper5 folder>
   ```

   A folder with GBC, ASE, ASE3 and Ultimapper5 subfolders works too, like
   eXoDOS's `util` folder. Supported files are patched and the originals are kept as
   `*.orig`. `dbxapi32.dll` goes next to the patched programs. Other versions
   are left alone. An old window title saved in ASE's or ASE3's settings
   (`ASE.dat`, `ASE3.dat`), such as "DOSBox ECE", becomes "DOSBox". `--check`
   shows what would be done, `--revert` undoes it.
2. **Configure DOSBox Staging** with the two settings in `gbc_staging.conf`:
   either add it with `-conf`, or put its lines into your
   `dosbox-staging.conf`.

   ```
   [sdl]
   window_titlebar = program=name dosbox=always cycles=on mouse=full
   [webserver]
   webserver_enabled = on
   webserver_port = 8086
   ```

   The first keeps "DOSBox Staging" in the window title; the tools find the
   DOSBox window by its title. The others turn on the HTTP API. The port is
   optional: the tools find the API on whichever port that DOSBox listens on
   (Staging's defaults vary between 8086 and 8080).
3. Use the tools as before. Their preset window title (in Ultimapper
   "DOSBox 0.74-2.1", GOG's DOSBox) is now "DOSBox", which matches DOSBox
   Staging, 0.74 and ECE alike. Apart from ASE's and ASE3's (see step 1),
   settings saved by an earlier run keep their old title (often "DOSBox
   0.74"): change it to "DOSBox" once, in the tool's window title field.

### In eXoDOS

eXo starts the tools from the game's `exception.bat` with the game number and
window title as arguments (today `start .\util\GBC\GBC.exe 1 "DOSBox ECE"` and
DOSBox ECE r4230). For Staging, pass the Staging title and start the game in
Staging 0.83+ with `gbc_staging.conf` (copied to `emulators\dosbox`) added.
For example, Pool of Radiance (`:13gbc`):

```
start .\util\GBC\GBC.exe 1 "DOSBox Staging"
".\emulators\dosbox\<staging 0.83>\dosbox.exe" -conf "%var%\dosbox.conf" -conf ".\emulators\dosbox\options.conf" -conf ".\emulators\dosbox\gbc_staging.conf" -noconsole -exit
```

Use the game's Staging `dosbox.conf`, not `dosbox_GBC.conf` (that one is for
0.74/ECE). For Eye of the Beholder: `start .\util\ASE\ASE 1 "DOSBox Staging"`
(`2` for EOB 2). ASE3 (EOB 3) is started without arguments and takes the
title from `ASE3.dat`; eXoDOS's says "DOSBox ECE", which `patch.py` changes
to "DOSBox".
For Ultima V: `start .\util\Ultimapper5\Ultimapper_5 1 "DOSBox Staging"` with
`%var%\dosbox.conf` (`:UM5`), or `... 2 "DOSBox Staging"` with
`%var%\dosbox_upg.conf` for the upgraded version (`:UM5u`).

Start the game through its own `.bat` (or the eXo front end), not by running
`exception.bat` on its own: the game's `.bat` sets `%var%`, and without it
DOSBox finds no game config and quits at once.

GBC finds eXoDOS's game folders by the first folder named `eXo` in its own
path, so an install with another `eXo` folder above eXo's own (like
`...\eXo\eXoDOS\eXo\util\GBC`) needs the game folder set by hand once. GBC
remembers it.

### Options

`dbxapi32.ini` next to `dbxapi32.dll` is optional. Its `[dbxapi]` section
takes `port=` (use only this API port; by default it's found), `cache_ms=` (40)
and `log=1` (writes `dbxapi32.log`).

## Why the tools didn't work with Staging

1. **Memory access.** The tools find the DOSBox window, open its process and
   scan the 32-bit address range 0x01000000-0x20000000 with
   `ReadProcessMemory` for the game's data. Staging is a 64-bit program; its
   emulated RAM is not in that range.
2. **Load address.** Staging's DOS uses a different amount of low memory, so
   games load at another segment (Pool of Radiance: 0x51 paragraphs higher
   than under ECE). That broke GBC in two places:
   - the "1st ID" patterns of five games (Pool of Radiance, Curse of the Azure
     Bonds, Champions of Krynn, Countdown to Doomsday, Matrix Cubed) run into
     far calls whose segment words DOS relocates at load time, so they only
     matched at 0.74's load address;
   - GBC converts the game's far pointers (seg:off) by adding the base it
     derives from the 1st ID, i.e. it treats the program's position as fixed
     relative to the start of RAM. Three converters in GBC and GBC_Audio and
     one in ECL_Monitor do this. Everything else GBC reads is relative to the
     program and was fine.
3. **File sharing.** Staging opens every game file on the host with write
   access, even when the game only reads it (0.74 used the DOS open mode).
   GBC opens game files read-only with "deny write" sharing, which Windows
   then refuses ("Cannot open file ...\GAME.OVR").
4. **Window title.** Staging drops "DOSBox Staging" from the title while a
   program runs, unless `window_titlebar` contains `dosbox=always`; and the
   tools' preset title was "DOSBox 0.74".

## What the patch does

- **`dbxapi32.dll`.** The tools import `OpenProcess`, `ReadProcessMemory`,
  `WriteProcessMemory` and `CreateFileA` through one kernel32 import
  descriptor. Its DLL name is changed to `dbxapi32.dll` (same length, 12
  bytes); the DLL forwards all other functions of that descriptor to
  kernel32.
  - When a tool opens a DOSBox, the DLL looks at the TCP ports that process
    listens on (8086 and 8080 first) and asks each for
    `/api/v1/dosbox/info`. If one answers, the tool gets a stand-in handle
    instead of opening DOSBox. Reads and writes through it become
    `GET`/`PUT /api/v1/memory`, with the emulated RAM shown as one block at
    0x01000000 (the start of the tools' default search range), cached in
    256 KB blocks for 40 ms. A full 64 MB scan takes about 0.3 seconds.
  - Any other process (0.74, ECE) gets the real calls.
  - Read-only `CreateFileA` opens also allow other writers (point 3).
- **Far-pointer converters.** Each one now jumps to a small stub in the code
  section's slack. The stub adds the start of RAM that the DLL sets while it
  serves the tool through the API, and runs the original instructions
  otherwise. The value lives in the data section's slack behind the marker
  `dbxapi32:rambase`.
- **`Game.dat`.** The five 1st IDs are cut right after the first far call's
  offset, before the first relocated word. GBC still checks the 2nd ID (plain
  text at a fixed distance), so a match stays unambiguous.
- **Preset title** "DOSBox 0.74" becomes "DOSBox" (point 4).

All files keep their size; `patches.json` lists the changed bytes of each
supported build, and `patch.py` checks the result's checksum before writing.

## What was tested

With a local DOSBox Staging 0.84.0-alpha build (same API as the 0.83
documentation) and the tools' original builds on DOSBox ECE r4230 as the
baseline:

| Tool | Test | Result |
|---|---|---|
| GBC | Pool of Radiance: search, characters, map, HUD (eXoDOS setup) | works; addresses match ECE's after the 0x51-paragraph shift |
| GBC | the same from a plain folder, preset title, no arguments | works |
| GBC | teleport (Ctrl+click on map, writes memory) | game shows the new position |
| GBC | 1st/2nd ID of all 12 games in Staging's memory | all found; the five old IDs are not |
| GBC_Audio | Pool of Radiance search, HUD, map | works |
| ECL_Monitor | Pool of Radiance live ECL script | correct listing and program counter |
| ASE (eXoDOS build) | EOB 1: search, full level map, live position | works; offsets identical to ECE's |
| ASE (eXoDOS build) | teleport (T on map, writes memory) | game shows the new position |
| ASE (May 2020 release) | EOB 1 search with the preset title | works |
| ASE (eXoDOS build) | EOB 2 in the eXoDOS setup on Staging 0.84 | works |
| ASE3 | starts, form and preset title | works |
| ASE3 | EOB 3 in the eXoDOS setup on Staging 0.84 | works |
| Ultimapper 5 (eXoDOS build) | Ultima V on Staging 0.84: HUD (party, HP, equipment, clock), location map | works |
| Ultimapper 5 (Release 4) | the same from a plain folder, preset title, no arguments | works |
| patched GBC | Pool of Radiance on DOSBox ECE | works like the original |
| `dbxapi32.dll` | `tests/dlltest.c` | all checks pass |
| `dbxapi32.dll` | API on 8086, 8080, other ports, all addresses, IPv6; pinned `port=`; webserver off | found where expected; real calls otherwise |
| GBC, ASE, Ultimapper 5 | Pool of Radiance, EOB 1, Ultima V with the API on 8080 and no port configured | work |

Not run in-game: FRUA_Tool, the debugging tool for Unlimited Adventures
modules (eXoDOS doesn't use it). Like ASE3, it searches the memory itself and
uses no far-pointer conversion, so it only needed the DLL. Ultimapper 5 is
similar: it finds Ultima V's data
segment by the C runtime's copyright text and reads everything at fixed
offsets from there. Its writes (teleport, editor, quickfight aiming) use the
same path as the GBC and ASE teleports tested above.

## Notes

- Each DOSBox is served through its own API port, so several Staging instances
  work if they use different ports. One that can't open its port (another
  instance has it) has no API and gets the real calls, which don't reach a
  64-bit DOSBox.
- For the Staging team: the memory endpoints read *linear* addresses, through
  the A20 gate and paging (`MEM_BlockRead`). With A20 off, reads above 1 MB
  return the low memory again. Under a paged protected-mode guest, a read of
  an unmapped page may raise a page fault inside DOSBox. That hasn't come up
  with these games (EOB 3 runs in protected mode under DOS/4GW), but a
  physical-address read might be worth having.

## Building and regenerating

The release zip carries the sources in `source/`.

- `sh build.sh` builds `build/dbxapi32.dll` and `build/dlltest.exe` with a
  32-bit MinGW-w64 cross compiler (`i686-w64-mingw32-gcc`).
  `build/dlltest.exe <pid of DOSBox Staging>` checks the DLL against a running
  Staging with the webserver enabled (it writes 16 bytes of the BIOS data
  area's application area and restores them).
- `tests/porttest.ps1 -Dosbox <Staging's dosbox.exe> -Work <folder>` starts
  Staging once per webserver setup (ports 8086, 8080 and others, all
  addresses, IPv6, a pinned `port=`, webserver off) and runs `dlltest.exe`
  against each. The folder needs copies of `dlltest.exe` and `dbxapi32.dll`;
  the script writes its config and `dbxapi32.ini` there.
- `tools/patch_tools.py` (executables) and `tools/fix_gamedat.py` (Game.dat)
  do the actual patching from the original builds; they need `pefile`.
  `tools/make_release.py --gbc <GBC 2.65 folder> --ase <ASE.exe builds> --ase3
  <ASE3.exe> --ultimapper <Ultimapper_5.exe builds> --zip <name>.zip` runs them
  on copies, writes `patches.json` and builds the release zip.
- `tools/gen_def.py` writes the DLL's export list `src/dbxapi32.def` from the
  tools' imports.

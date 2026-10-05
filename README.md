# Gold Box Companion, The All-Seeing Eye and Ultimapper 5 on DOSBox Staging

Joonas Hirvonen's companion tools for the Gold Box games, Eye of the Beholder
1-3 and Ultima V, on DOSBox Staging 0.83 and later, through its HTTP API.

You have two options for running this. Pick one (companion pages are recommended), 
and ignore the instructions for the other.

- **The companion pages** (`web/`): the tools rewritten as web pages. 
  They run in any browser, on any system Staging runs on.
- **The patched tools**: the original Windows programs, patched to reach the
  game through the API.

## OPTION 1: The companion pages

HTML pages that do what the tools do. They need to be served by DOSBox. If
you decide to use these, you don't need the executable patches below.

### Setting the pages up outside of eXoDOS

1. Put the three pages where DOSBox Staging serves files from, which is one of
 - `%LOCALAPPDATA%\DOSBox\webserver`
 - a `webserver` folder next to `dosbox.exe`
 - a `resources\webserver` in the folder DOSBox is started from
 - a `resources\webserver` folder next to `dosbox.exe`
 
2. Turn the webserver on, with `conf/gbc_staging.conf` added by `-conf` or
   these lines in your config:

   ```
   [webserver]
   webserver_enabled = on
   webserver_port = 8086
   ```

3. Start the game and open
 - http://localhost:8086/gbc.html (Gold Box games)
 - http://localhost:8086/ase.html (Eye of the Beholder 1-3)
 - http://localhost:8086/ultimapper5.html (Ultima V). 

   The page finds the game by itself.

4. Once per browser, give the page the tools' data and the game, from its
   menu:
   - `gbc.html`: "GBC folder..." (Gold Box Companion's folder: icons, area
     names, effects, journals) and "Game folder..." (saved games, backups,
     PDFs).
   - `ase.html`: "ASE / ASE3 data folder..." (ASE's folder for EOB 1 and 2,
     ASE3's for EOB 3) and "Game folder..." (EOB 3's saved games).
   - `ultimapper5.html`: the Ultima V game folder (maps and tiles).

   Chromium-based browsers can also write saved games back into the game
   folder; other browsers download them.

Instead of choosing folders, the pages can take folders that the webserver
serves as URL parameters:
- `gbc.html?gbcdata=<GBC folder>&gamedata=<game folder>`
- `ase.html?asedata=<ASE folder>&ase3data=<ASE3 folder>&gamedata=<game folder>`
- `ultimapper5.html?data=<game folder>`. 

The eXoDOS patch uses these.

### Setting the pages up inside eXoDOS

`exo/patch_exo.py` (needs Python 3.8+) switches an eXoDOS installation on Windows to
using the pages. It backs up the old files.

```
python exo\patch_exo.py [--check | --revert] [--staging FOLDER] <eXo folder>
```

- `<eXo folder>` is eXoDOS's `eXo` folder, the one with `eXoDOS`, `emulators`
and `util` in it. 
- `--staging` is the DOSBox Staging folder to use, relative to the eXo folder
(default `emulators\dosbox\staging0.83.0`). Put any Staging version >= 0.83 there.
- `--check` shows what would change.
- `--revert` undoes the patch.

## OPTION 2: The patched tools

These can be used instead of the web page versions. You don't need to set up both.

Supported versions (checked by checksum):

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

### Using the tools

Everything needed is in the release zip (`patch.py`, `patches.json`,
`dbxapi32.dll`, `gbc_staging.conf`), on the
[releases page](https://github.com/gschmidl/goldbox-staging/releases).

1. **Patch the tools** (needs Python 3.8+):

   ```
   python patch.py  [--check | --revert] <GBC folder> <ASE folder> <Ultimapper5 folder>
   ```

   OR

   ```
   python patch.py  [--check | --revert] <tool folder>
   ```

  - `--check` shows what would change.
  - `--revert` undoes the patch.

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

   The port is optional: the tools find the API on whichever port 
   DOSBox listens on.

3. Use the tools as before. Apart from ASE and ASE3,
   settings saved by an earlier run keep their old title (often "DOSBox
   0.74"): change it to "DOSBox" once, in the tool's window title field.

### In eXoDOS

eXo starts the tools from the game's `exception.bat` with the game number and
window title as arguments (today `start .\util\GBC\GBC.exe 1 "DOSBox ECE"` and
DOSBox ECE r4230). For Staging, pass the Staging title and start the game in
Staging 0.83+ with `gbc_staging.conf` (copied to `emulators\dosbox`) added.

Examples:

- Pool of Radiance:
  ```
  start .\util\GBC\GBC.exe 1 "DOSBox Staging"
  ".\emulators\dosbox\<staging 0.83>\dosbox.exe" -conf "%var%\dosbox.conf" -conf ".\emulators\dosbox\options.conf" -conf ".\emulators\dosbox\gbc_staging.conf" -noconsole -exit
  ```
- For Eye of the Beholder: `start .\util\ASE\ASE 1 "DOSBox Staging"`
- ASE3 (EOB 3) is started without arguments and takes the title from `ASE3.dat`;
  eXoDOS's says "DOSBox ECE", which `patch.py` changes to "DOSBox".
- For Ultima V: `start .\util\Ultimapper5\Ultimapper_5 1 "DOSBox Staging"`

Start the game through its own `.bat` (or the eXo front end).

GBC finds eXoDOS's game folders by the first folder named `eXo` in its own
path, so an install with another `eXo` folder above eXo's own (like
`...\eXo\eXoDOS\eXo\util\GBC`) needs the game folder set by hand once. GBC
remembers it.

# Boring technical stuff you don't need to read

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
- `python tests/busytest.py build` checks the DLL (with `build/busytest.exe`)
  against a fake API that turns busy, as Staging's does while its window is
  dragged: no read may fail while it is busy, and after a failure the DLL has
  to attach again with the right RAM size, not one taken from busy answers.
- `tools/patch_tools.py` (executables) and `tools/fix_gamedat.py` (Game.dat)
  do the actual patching from the original builds; they need `pefile`.
  `tools/make_release.py --gbc <GBC 2.65 folder> --ase <ASE.exe builds> --ase3
  <ASE3.exe> --ultimapper <Ultimapper_5.exe builds> --zip <name>.zip` runs them
  on copies, writes `patches.json` and builds the release zip.
- `tools/gen_def.py` writes the DLL's export list `src/dbxapi32.def` from the
  tools' imports.
- The pages need no build: plain HTML with inline JavaScript, no libraries.
  `tools/gen_web_tables.py --gbc <GBC 2.65 folder> --ultimapper
  <Ultimapper_5.exe> --magic <MagicDefinitions.json>` regenerates the tables
  built into them (between `/*@NAME@*/` lines): from GBC's `Game.dat` files
  (patched by `patch.py`) and character file formats, Ultimapper's spell names,
  and [Ultima5Redux](https://github.com/bradhannah/Ultima5Redux)'s
  `DataFiles/MagicDefinitions.json`. `--check` only compares.

## License

MIT, see `LICENSE`. Gold Box Companion, The All-Seeing Eye and Ultimapper 5
are Joonas Hirvonen's; none of their files are included here, only the bytes
`patch.py` changes, and in the pages the small tables `tools/gen_web_tables.py`
generates from them; the pages load everything else of the tools' (icons,
maps, texts) from your copy at run time.

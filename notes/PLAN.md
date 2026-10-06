# Web rewrite of GBC, ASE (+ASE3) and Ultimapper 5

Goal (user, 2026-10-05): "rewrite the three applications as a cross-platform
single page html app. It doesn't need to sit around the dosbox window, it can
be its own window. same functionality." Then: "one each, not one total".

## Architecture

- Three self-contained pages in `web/`: `gbc.html`, `ase.html` (EOB 1-3, i.e.
  ASE + ASE3), `ultimapper5.html`. Inline CSS/JS, no libraries, no build step.
- Served by DOSBox Staging's own webserver: Staging serves static files from
  `<config dir>/webserver/` (portable: next to dosbox.exe) and
  `<resources>/webserver/`. Same origin as `/api/v1`, so no CORS (Staging sends
  no CORS headers). Open `http://localhost:8086/gbc.html` (any port works).
- Memory: `GET /api/v1/memory/<linear>/<len>` (Accept: application/octet-stream),
  `PUT /api/v1/memory/<linear>` (octet-stream body). Reads are linear.
- Data the originals ship (GBC Games\*, ASE EOB1\/EOB2\, ASE3 Maps\, Ultimapper
  Data\) and game files (saves, DAX, maps) are loaded from folders the user picks
  (input webkitdirectory or drag and drop), cached in IndexedDB per origin.
  Nothing of Hirvonen's or the games' is embedded in the pages.
- Not possible in a browser, replaced or dropped: launching games/GOG tools,
  "Open folder", window docking/on-top/title hacks, global hotkeys (page
  hotkeys only), writing into the game folder (downloads instead; Chromium's
  File System Access API where available).

## Test setup (session scratchpad, see notes/TESTING.md once written)

- Portable Staging copy `stg\` (eXo's 0.84 d6406) with `webserver` = junction
  to `web\`; mini eXo tree with saves from the patch work (xst\eXo).
- dbxapi32.dll `trace=1` logs every read/write of the original tools: run the
  original against a game to map each feature to memory.
- Forms of the originals dumped with re\dfm2txt.py (feature inventory).

## eXo integration (2026-10-05): exo/patch_exo.py

- The GBC / ASE / Ultimapper options of eXo's English launchers (16 games)
  start a DOSBox Staging folder (`--staging`, default
  `emulators\dosbox\staging0.83.0`) with the option's game config,
  options.conf, gbc.conf or ase.conf and gbc_staging.conf (webserver on, port
  8086; `[mt32] romdir = .\mt32`, because the GBC configs name the ROMs the
  DOSBox ECE way), and run `start "" /b cmd /c
  .\emulators\dosbox\gbc_staging_page.bat <page> <folder>`: it waits for the
  API (`curl --retry-connrefused`) and opens
  `<page>.html?gamedata=eXoDOS/<folder>&gbcdata=util/GBC` (ASE: asedata +
  ase3data; Ultimapper: data). The folder comes from the option's config
  (mount + cd: ultima5/upgrade, unlimadv/MODS). exception.bat.orig keeps the
  old launcher.
- Staging serves `<config dir>\webserver` first, then the first existing of
  `<working dir>\webserver`, `<working dir>\resources\webserver` and
  `resources\webserver` next to dosbox.exe (webserver.cpp, support.cpp; the
  same in 0.83.0). The patch puts the pages and relative links `util`,
  `eXoDOS` (junctions without Developer Mode) into the Staging folder's
  `resources\webserver`, next to Staging's own index.html. A `webserver`
  folder in the eXo folder would hide it; one with only our files is removed.
- `--revert` finds the Staging folders from the switched launchers.
- Verified: scratch trees from the real launchers (85 checks), and the user's
  eXo with `--staging emulators\dosbox\staging` (0.84): Curse of the Azure
  Bonds and Ultima V started from their launchers, pages with their data.

## Order (breadth first)

1. Core of each page: connect, find the game, main view (GBC: HUD + automap;
   ASE: map; Ultimapper: HUD + map).
2. Then the remaining features, page by page, in the checklists below.

## GBC checklist (GBC.txt + forms)

Core
- [x] Search: all 12 games' IDs/offsets/record sizes embedded (from the
      patched Game.dat headers); detects the game by itself (2026-10-05)
- [x] Characters: list via next pointers (fields by GBC's names from
      Game.dat's field table, generated); effects in chain order with
      durations, "N levels drained" first; HP bar in GBC's 5 colours, XP
      meter from Experience.dat (max cur .. min next, able-to-train orange)
- [x] HUD icons (Head/Body.bmp, recoloured; Icon.bmp games; NPC
      <NAME>_1.bmp; Death_1.bmp) - PoR matches GBC pixel for pixel
- [x] HUD look and GBC's hover menu (two rows of buttons)
- [x] Automap with GBC's exact geometry (walls, doors, archways, dotted
      lines, special walls, notes, events, party triangle) from its code
- [x] Tested on PoR, CotAB, SotSB, CoK, CtD, MC (saves in the test tree);
      PoD found by itself with its party in the HUD (only its demo was
      reachable: the title menu starts the demo, area names unchecked);
      DKoK, DQoK, TotSF and FRUA have eXo saves but are untested, GttSF has
      none. Dark Queen's bigger maps are drawn from Game.dat's arrays
      (rendering checked).
Features
- [x] Map notes (3-char ID + text), right click: notes / event numbers / none
- [x] Ctrl+click teleport (verified in game), Ctrl+right click set event
- [x] World map view (W): World.bmp / World_<GEO>.bmp, titles (T), party at
      the outdoor x,y, Ctrl+click teleport; scales PoR 24x30, Krynn 8x8 (both
      checked against the images), others estimated; no automatic switch (the
      world-map mode byte is unknown without a world-map game state)
- [x] GBC_Audio: music by situation from a picked Music folder (untested
      with real files)
- [x] Quick menu (Ctrl + key left of 1), fix stats (equals the game's values)
- [x] Combat view as GBC draws it (snapped grid, box sizes by entry code,
      colours, HP drop flash, red X), statistics tooltip with GBC's lines,
      click = editor in cheat mode
- [x] Explore / unexplore map, clear explored, save map as PNG
- [x] Encamp-fix, store/restore spells and race hack/restore by party slot
      as GBC does them; FIX DRAIN exactly as GBC's code (undrained record
      per slot through the pending rules, else highest levels)
- [x] Level up as GBC's code (one class per step, dice + con bonus, thief
      and wisdom adjustments, spell pick, dual-class return), FIX STATS as
      GBC's; XP tables
- [x] Character editor (fields from GBC's format docs; spells from
      Game.dat's tables incl. the Dark Queen/FRUA bitmap, memorized list
      rebuilt GBC's way; items write the 17 DAX bytes; effects), GBC's
      paladin/ranger/monk conversions, ability originals follow
- [x] Settings: icons, XP meter, effects, auto ID, fix drain, fix stats,
      auto-ammo (amount, max plus) - auto ID / auto-ammo untested in game
- [x] Quickfight turned off outside combat on every read (GBC has no
      setting for it); PoR paladin/ranger fighter level in combat only
- [x] Journals (entries), passwords, random names, PDFs, monster manual
- [x] Saved games list with location, backup save (zip)
- [x] Debug mode, weaken enemies (Ctrl+W: debug mode + combat; HP 1, flags
      and magic resistance 0), debug dump with items (GBC's format), cheat
      mode ("cheat" once; editor in combat, item/effect changes, teleports)
- [x] 2026-10-06: every GBC.exe code path compared with its Ghidra
      decompilation (re\gbc\decomp, gitignored) and the page fixed to match;
      notes\gbc.md lists the facts. Checked against a mock of Staging's API
      with PoR's eXo party (scratchpad mockapi.py); a live game not yet.
      FRUA's map done 2026-10-06 (the design's geo file found in memory,
      design from START.DAT or the settings; notes\gbc.md "FRUA's map").
- [x] "No GBC data" chip (click = choose the folder) while GBC's folder is
      missing: without it the HUD shows initials instead of the icons

## ASE checklist (ASE.txt, ASE3.txt + forms)

EOB 1/2
- [x] Search by structure (no save file): character records + coords at a
      fixed distance (EOB1 243-byte records, coords char0+648; EOB2 345,
      coords char0-783A), game wall tables by their preset signature
- [x] Map: ASE's own categories from its Blocks.dat (wall index x level),
      or the game's wall tables (ScummVM automap rules); rubble, doors,
      button doors, plates, stairs, buttons, niches... matches the original
      on EOB1 level 1 and EOB2 level 4
- [x] Items/monsters/hints/notes layers (ASE defaults: only buttons on),
      tooltips, explored tracking (party cell, neighbours, 3 ahead)
- [x] EOB2 monsters are just "Monster" in ASE too; the grey cell is an
      illusionary wall block (grey until illusions are shown) - 2026-10-05
- [x] Popup: add note (A), peek (Z), explore (X), unexplore, teleport (T),
      copy explored from slot 1-6 (EOB 2 only), size, show buttons/illusionary/
      monsters/items/hints/notes, identify all items (traced), item usability
      tweaks (traced: types' byte 5 = 3F, byte 6 = 0; 57 / 64 types), rule book,
      clue book, character editor, backup save, export map, debug mode, dump
      monsters/items (ASE's file formats), weaken (byte 0E = 1) and petrify
      (byte 16 |= 20) monsters (EOB 2 only, traced), quit
- [x] Hints (clue book, 1-based coordinates, green cells like ASE) and the
      tooltip in ASE's format and colours; title adds the cell (+ wall bytes in
      debug mode); item names with plusses like ASE
- [x] Character editor: stats (same values as ASE for EOB 1 and 2), spells,
      inventory (set item)
EOB 3 (ASE3)
- [x] Search map data + party location by structure, no save needed (the
      save's location as ASE3's fallback; chooser among candidates, picked by
      itself when only one changes) - same addresses as ASE3 (2026-10-05)
- [x] Map like ASE3 (explored open cells, walls where they meet wall
      cells; matches its window wall for wall), title, explore = party cell
      + 4 neighbours, ASE3's Explored_nn.dat taken over (column order)
- [x] Saved games list with level info, preview map (full or explored)
- [x] Party location in save (level, x, y) + apply to save (File System
      Access API, else download)
- [x] Character editor, in memory and in a saved game: stats, spells,
      equipment in ASE3's slot order with Items.txt names
- [x] Teleport writes x, y (checked against a mock of the API, scratchpad
      mockase.py: EOB 3 from the eXo save and ASE3's level map, a synthetic
      EOB 1 level with a door, button, plate, stairs, item and monster; 2026-10-06)
- [x] 2026-10-06: the earlier rewrite of ase.html (ASE's cell model, item
      names, explored working set per save slot, SavePeek) exercised against
      that mock for both games: finding, map, tooltips, editor (EOB 3 records
      from memory), saved games dialog, teleport. Not yet run with a live game.

## Ultimapper 5 checklist (Ultimapper_5.txt + forms)

- [x] Search (C runtime string), base (2026-10-05)
- [x] HUD: HP, MP, status, XP, class, level, attributes, equipment, clock
      (matches the original's values on the test save)
- [x] Map: world (zoom view, titles), towns (live floor from DS:6618);
      party location; units drawn from the save's unit table
- [x] Map: underworld, dungeons, combat view (all compared with the
      original's window), NPC names incl. merchants, world and underworld
      titles (the original's lists), small-scale colours, party frame, zoom
      lens (2026-10-05)
- [x] Exploration from the 11x11 view; per area type explored toggles,
      explore/unexplore area, unexplore all; gem use (untested)
- [x] Teleport = the original's writes (x, y, 2F5/2F6 chunk origin, 2x2
      chunks to DS:6618); forward time = hour + copy (2D9, 2DA)
- [x] Spell list with mixing (traced), inventory list - the original's layouts
- [x] Auto level up (traced)
- [x] Quickfight: keys via the BIOS keyboard buffer (the game reads them),
      insta-aiming (crosshair at save 2F3/2F4, checked), interval; melee by
      direction, moving towards the nearest monster
- [x] Debug: teleport, editor (the original's fields), forward time 1 h, exit
      combat (traced: 2FD = 1 + Esc), dump TLK (same output as the original),
      dump memory, debug log
- [x] Save map as image, backup saved game, manuals
- [x] 2026-10-06: every code path compared with Ultimapper_5.exe's Ghidra
      decompilation (re\u5\decomp, gitignored) and the page rewritten to match:
      exploration rules, HUD as a canvas with its layout, the maps' exact
      geometry and colours (exe tables via gen_web_tables.py --ultimapper),
      combat flags and colours, quickfight step for step, auto level-up, the
      messages (character generation, not playing, dead); notes\ultimapper5.md
      lists the facts. Checked against a mock of the API (scratchpad mocku5.py),
      not against the game. The original's Arrow bitmaps are not used.

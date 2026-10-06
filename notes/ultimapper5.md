# Ultima V in memory (for ultimapper5.html)

Found by tracing the original Ultimapper 5 (dbxapi32 trace=1) and from the
Ultima5Redux project's documentation of the game's files.

## Finding the game

The data segment is an image of DATA.OVL. Its "MS Run-Time Library - Copyright
(c) 1988, Microsoft Corp" string is at DS:0018, so DS = hit - 0x18 (the
original reads the first 90 KB in 30 KB pieces). Under Staging 0.84 with eXo's
config: DS = 0x1158 (linear 0x11580).

## What the original polls (25 times a second)

| DS offset | size | contents |
|---|---|---|
| 55B6 | 4192 | the SAVED.GAM image, live (the game works on it) |
| AB12 | 352 | the 11x11 view window, rows of 32 bytes, FF = not visible |
| 6618 | 1024 | the current 32x32 map: a small map's floor, or the 2x2 overworld chunks |

Exploration: a cell counts as explored once the view window shows it. Row r,
column c of the view is map cell (x - 5 + c, y - 5 + r).

## SAVED.GAM image (offsets in the image)

| offset | size | |
|---|---|---|
| 002 | 16 x 32 | character records |
| 202 | 2 | food; 204 gold (2); 206 keys; 207 gems; 208 torches; 209 grapple; 20A carpets; 20B skull keys |
| 20D.. | | Lord British's artifacts, shards, spyglass, plans, sextant, watch, badge, box |
| 21A | 48 | equipment counts (helms, shields, armour, weapons, rings, amulets) |
| 24A | 48 | spells; 27A scrolls (8); 282 potions (8); 2AA reagents (8) |
| 28A/292/29A/2A2 | 8 each | moonstones x, y, buried flag, z |
| 2B5 | 1 | party size |
| 2CE | 2 | year; 2D7 month; 2D8 day; 2D9 hour (2DA a copy); 2DB minute |
| 2D5 | 1 | active character (FF none) |
| 2E2 | 1 | karma; 2E5 turns |
| 2ED | 1 | location (0 Britannia/Underworld, 1-32 small maps, 33-40 dungeons) |
| 2EF | 1 | z: floor (FF = basement), 0/FF on location 0 = Britannia/Underworld |
| 2F0, 2F1 | 1 | x, y |
| 5B4, 634 | 80 each | NPC dead / met bitmaps |
| 6B4 | 32 x 8 | map units: tile-0x100, tile2-0x100, x, y, floor, 3 more; unit 0 = party |
| 9B8 | 512 | NPC states; FF8 NPC sprites |

Character record (32 bytes): name (9), gender (0B/0C), class (A/B/F/M),
status (G/P/C/S/D...), str, dex, int, MP, HP (2), max HP (2), XP (2), level,
months at inn, ?, helm, armour, weapon, shield, ring, amulet (item 0-2F or FF),
party (00 in the party, FF not joined, else at an inn). Party = records with
byte 1F = 00, in record order.

## Game files

- TILES.16: LZW (4-byte length, 9-12-bit codes, 100 reset, 101 end) -> 512
  tiles of 16x16, 4 bits per pixel, high nibble first, EGA palette.
- BRIT.DAT: 16x16 chunks of 16x16 tiles in row order; DATA.OVL 3886 (256
  bytes) marks all-water chunks with FF (tile 1), the rest are read in order.
  UNDER.DAT: all 256 chunks.
- TOWNE/DWELLING/CASTLE/KEEP.DAT: 32x32 maps, floors per location in order
  (Ultima5Redux SmallMapReferences); Yew, Castle Britannia, Castle Blackthorn
  and Serpent's Hold start with a basement (z = -1).
- DUNGEON.DAT: 8 dungeons x 8 levels x 8x8 cells; high nibble = type (0
  corridor, 1-3 ladders, 4 chest, 5 fountain, 6 trap, 7 open chest, 8 field,
  B/C wall, D secret door, E door, F room + number).
- DATA.OVL: location x/y at 1E9A/1EC2 (40 each, location 1 first); place names
  at A4D (35, no Sutek/Sin'Vraal/Grendel huts and castles).
- *.NPC: 8 locations x 0x240: 32 schedules (0x200), 32 types, 32 dialog numbers.

## Combat (location FF)

| DS / save | |
|---|---|
| DS:AD24 | 11x11 combat map, rows of 32 bytes (the view at AB12 has 00 where units stand) |
| DS:BA24 | 8-byte combatant records, party 0-5, monsters from 6: HP (monsters), ?, flags (80 party, 40 monster), ?, ?, turn counter, x, y |
| save 6B4 | the unit table holds the combatants: party first, then monsters |
| save 2F8 | whose turn it is (unit index); save 2F0/2F1 = that unit's x, y |
| save 2F2..2F4 | aiming: 2F2 = 1 while the crosshair is up, 2F3/2F4 its x, y (the game sets them to the attacker on A) |
| save 2FD | 1 = Esc at the combat prompt escapes ("Exit combat" writes it, then Esc) |

The original's combat view: 11 cells across the window, a 0.71-cell square per
combatant with its HP, party #22aa22, monsters #bb2222, the one whose turn it
is #5555ff, 2 px border in half the colour. Attack ranges: DATA.OVL 1674 per
item (0 melee; dagger 3, sling 4, oil 4, spear 5, axe 4, morning star 2, bow 7,
crossbow 8, halberd 2, magic bow and axe 15). Insta-aim = write 2F3/2F4 after A,
then Enter (checked: "Attack-Aim! Giant Rat killed!").

## Talk scripts

During a conversation the game has the NPC's TLK script at DS:B22E; the
original reads 1000 bytes there, finds the entry in the TLK files and dumps it
("Could not find a proper TLK-entry!" otherwise). Format (Ultima5Redux): lines
end with 00; A0-A1, A5-DA, E1-FA are characters + 80; words from DATA.OVL's
list at 104C (0x24E bytes, index map with gaps: 1-7 -1, 9-27 -2, 29-49 -3,
51-64 -4, 66 -5, 68-69 -6, 71 -7, 76-128 -11); 81-8F commands (avatar, end,
pause, join party, gold, change, or, ask name, increase karma, decrease karma,
call guards, if knows name / else, new line, rune, wait for key); 91-9B
labels; 90 + label starts a label definition; 90 9F ends. First lines: name,
description, greeting, job, bye; then keyword / answer lines. Dialog numbers
81-88 are merchants (Weapon dealer, Barkeeper, Horse seller, Ship seller, Magic
seller, Guildmaster, Healer, Innkeeper), shown as their names on the map.

## Other traced writes

- Auto level up: level + 1, HP = max HP = level x 30, one of STR/DEX/INT + 1;
  log "<name> reached experience level N. Increased INT."
- Mixing a spell (click in the spell list): spell count + 1, each reagent - 1.

## The map window

- Large maps at a few pixels per tile: one colour per tile from a table (towns
  red, roads brown, shores dark green, tile A4 white...), not tile averages.
- Party there: a white cell in a 35 px light grey frame with darker corners.
- Titles (white, black shadow, pushed apart when they overlap) only where
  explored. World: locations without Britain + the Britannies, Ararat, Doom;
  plus shrines, Codex, Waterfall to UW. Underworld: Ararat, the dungeons with
  Doom, plus Battlefield, Lava pit and the three shards (Ultimapper's tables).
- Zoom view (left click): an 11x11 lens at 32 px of the map as it is (also
  unexplored parts) around the mouse, in the half away from the mouse.
- NPC names: white on a black box one cell tall above the NPC.
- Defaults: world and towns explored, underworld and dungeons not, world
  titles on, underworld titles off, NPC names on.

## From Ultimapper 5's decompilation (Ghidra 12.1.4, re\u5\decomp, 2026-10-06)

The page follows UM5.c, UM5_Draw.c, UM5_Game.c and UM5_Quickfight.c; the exe's tables
(tile colours, combat walkability, equip preferences, HUD item names, bar colours) come
from tools/gen_web_tables.py --ultimapper (the U5_TABLES block).  Verified against a
mock of the API (scratchpad mocku5.py: DATA.OVL + SAVED.GAM images, scenarios for every
area), not against the game.

- Read timer 100 ms.  Character generation = save 6B4/6B6 zero, loc 13 at 15,15, z 0 and
  no chunk origin seen yet -> the "CHARACTER GENERATION / VIRTUE STAT BONUSES" text.
  Loc 40/42 -> the "character name does not match" text.  Dead = every party record
  (1F = 0) at 0 HP, or loc 17/FF with unit 1 = tile 74 at 5,2 -> "You have died!",
  quickfight off, caption "Ultimapper 5".  Log "Location changed to %d (z = %d)." (z is
  the raw byte).  Peer explore on a decrease of 207 (gems), 271 (In Quas Wis mixed) or
  27E (its scroll): large maps = the 2x2 chunks (origin trunc((v-5)/16)*16, clamped
  0..E0), elsewhere the whole floor.
- Exploration: large maps mark the 11x11 around the party (no view check, no wrap); small
  maps mark the view's cells != FF only when the view agrees with the map at 6618, no
  wrap; dungeons the 3x3; nothing is marked while the area's "explored" setting is on.
  Units in small maps are drawn only on cells in view this tick (anywhere with Towns
  explored); the party sprite (tile 1C) only with Party location.  (The original also
  marks the view's top row on a mismatch - a bug, not copied.)
- Large maps: always the 1-pixel-per-tile colour image stretched; titles Verdana
  clamp(W/65, 8, 16) pt, white over a black shadow (+2,+2), centred on Round(x*cell) with
  the bottom at Round(y*cell); shifts 5:(0,-2) 16:(3,2) 23:(0,-3) 26:(3,0) 28:(-8,0)
  37:(0,3), Compassion (-7,+1); the world skips 2, 19-21, 25, 40, the underworld shows 25,
  33-40 and 5 extras.  Party: white cell + #CCCCCC 2-px frame from -5 to +6 cells.
  Debug: black 16-cell grid + yellow frame of the chunks at 2F5/2F6.  Lens: (W/2)/32
  tiles made odd, 32 px a tile, grey frame, white 32/34 centre frame, in the half away
  from the mouse; a left click toggles it (loc 0).  Mouse cell = Round(px / (W/256)).
- Small maps: 512-px tile image stretched; NPC label white in a black box at
  (Round(x*cell+8), Round(y*cell)), font clamp(W/60, 8, 16) pt; mouse cell = px div
  ceil(W/32), two yellow frames outside the cell.  Unit names: save 9B8 (32 x 16), byte C
  = unit index -> byte A = dialogue number (81-88 merchants).
- Dungeons: the level from the save (3B4 + z*64), cell >> 4: 1/2/3 ladders 200/201, 4 and
  7 chest 257, 5 fountain 216, 11-13 wall 78, 14-15 door 184, rest #333333; the party is
  an arrow the way it faces (save 105D; the original has Arrow_N.bmp for this, not used);
  128 px at a whole scale 1-4 (W div 128), centred, #666666 frame.
- Combat: tiles from AD24 plus the unit table's objects (tiles 1-13 -> 100+t, unwalkable;
  1E -> 11E; 1F -> 11F); walkability by tile (WALKABLE); units from BA24 (HP of monsters,
  present, flags, party record / tile, -, -, x, y); flags 08 asleep ("Z"), 10 invisible
  (debug only), 80 and 01: one = friendly (#22AA22), both = charmed (#AA22AA, HUD box
  #660066), neither = hostile (#BB2222); the active unit (2F8) #5555FF; squares inset
  Round(cell*0.125)+1 with frames at half brightness, HP text Verdana Round(cell*0.2) pt;
  cell = Round(W/176*16); white 2-px aim frame at 2F3/2F4 while 2F2 = 1; "Q" in yellow
  with a black shadow (+3) at (W - cell/2 - width, cell/4) while quickfight runs.  "Not a
  fight" = unit 0 tile 6C at 5,6 or party at 233,233: tiles only, no quickfight.  Mouse:
  three yellow frames, cell = px div (W div 11).
- HUD (canvas, 11 units high, unit u = Round(W/50)): columns Round((W-6u+Round(u/2)-5u)/6)
  wide, separators #444444; from the bottom: HP bar at H-1.75u (u high, #191919, five
  colours by Trunc(4*hp/max), "hp / max" or "D E A D"), XP bar 0.75u above (0.2u high),
  MP (#CCCCCC, right) 1.25u above on the amulet row, ring..helm rows u apart (items
  #999999, empty slots' names #333333, 0.4u pt), class+level and STR/DEX/INT right-aligned
  (#999999; the stats from the helm row + 1.25u), name box 1.25u above the helm row
  (#006600, P #660000, S #666600, D #1A1A1A, charmed #660066; text #EEEEEE 0.5u pt).
  Side panel at 6(col+u): clock in a 4.5u x u box at 0.75u, then Keys / Skull keys /
  Torches / Gems at 2.5, 1.25, 1.75 font heights.  Left click there = spells, right =
  inventory.
- Quickfight: hands = record +1B/+1C(+1D); 11 13 1A 1C 24 need aiming, 19 22 26 have a
  range without; range = DATA.OVL 1684 + item - 10.  Adjacent target (8 neighbours, least
  HP, not friendly): equip EQUIP_PREF when there is no / a ranged weapon, else A, or a
  crosshair step / Enter (insta-aim writes 2F3/2F4).  Else the spiral (rings 1-11 clockwise
  from the top left) and ring distances over walkable cells: shoot the first unit with
  Round(euclidean) <= range; aiming without a target -> Space; else walk towards the first
  unit a path leads to (greedy by falling distance over up/right/down/left) via the cell
  next to us; else equip a ranged weapon (24, 1C, 1A, 11); else a step towards the nearest
  within 20 (longer axis first); else Space.  No hostiles and not aiming: re-equip the
  party and stop ("No hostile creatures found! Stopped quickfight.").  Log texts as the
  original's.
- Auto level-up: records 0-15 in the party, level < 8, xp >= [0,100,200,400,800,1600,
  3200,6400][level]: level+1, HP = max = level*30, one stat < 30 +1.  Forward time: only
  2D9 and 2DA := (h+1) mod 24.  Exit combat: 2FD = 1, 500 ms, Esc.  Teleport (debug):
  world writes 2F0/2F1, 2F5/2F6 and the 4 chunks to 6618; small maps not onto a unit;
  combat moves the active party member (6B4 and BA24) onto a walkable cell.
- Spell list in SAVED.GAM order; CAN MIX = the scarcest needed reagent (0 at 99); known
  #AAAAAA (selected #CCCCCC on #222266), unknown #444444 (#888888), have #228822, missing
  #882222, dashes #444444; no mixing while hostiles are about.
- Not copied: the name check against the SAVED.GAM file (no file access), writing
  Explored.UM5 when the game saves (the page saves continuously; the backup zip holds
  Explored.UM5 in the original's layout), the DOSBox-foreground requirement, docking.

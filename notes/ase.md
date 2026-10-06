# Eye of the Beholder 1/2 in memory (for ase.html)

From tracing the original ASE (dbxapi32 trace=1), its search log, and
ScummVM's EOB engine (saveload_eob.cpp importOriginalSaveFile, automap_eob.cpp).
Addresses are linear, Staging 0.84 with eXo's configs.

| | EOB 1 (1.7) | EOB 2 (1.1) |
|---|---|---|
| first character record | 32790 | 3B7E8 |
| record size | 243 (F3) | 345 (159) |
| coordinates | char0 + 648: level u16, block u16, dir u8 | char0 - 783A: level u16, sub u16, block u16, dir u8 |
| map (32x32 cells) | char0 - 3CEC, 9 bytes/cell | char0 - 42A8, 10 bytes/cell |
| cell | walls N E S W, flags u8, first item u16, draw u16 | walls, flags u16, first item u16, draw u16 |
| items (14 bytes) | char0 - 67B0, 500 | char0 - 743E, 600 |
| monsters | char0 - 6AFE, 30 x 28 | char0 - 77DE, 30 x 30 |
| item types (16 bytes) | char0 - 4B90 | char0 - 519A |
| wall tables | shape map, special types, flags: 70 each | 80 each |
| item names | 35-byte slots, "Leather armor" = index 2 | same |

The original polls the character block (2048 bytes), the coordinates and the
map 5 times a second; ASE's teleport writes the block into the coordinates.

Character record (EOB1; EOB2 has 16-bit HP, so later fields move by 2, and
80-byte spell arrays): id, flags (bit 0 active), name[11], STR/EXT/INT/WIS/
DEX/CON/CHA cur+max, HP cur/max, AC, disabled slots, race/sex, class,
alignment, portrait, food, levels[3], XP[3] (u32), 4 bytes, mage spells 5x6,
cleric spells 5x6, available-spell flags u32, inventory 27 x u16, timers,
events, effects...

Item: name unidentified, name identified, flags (40 identified, 80 magic),
icon, type, position in the block (0-3 floor, 8 niche), block u16, next u16,
prev u16, level, value.

Monster: type (global: EOB1 kobold 0, leech 1, ...), unit, block u16, pos,
dir, anim step, shape, mode, stray, attack frame, spell status, HP max u16,
HP cur u16, dest, rand item, fixed item, flags, ...

Wall faces: a block's face on side d is what you see from the neighbour on
that side; a side is a wall if the neighbour's face back is neither passable
(flag 1) nor a door (flag 8). ASE's EOB1/2 Blocks.dat = [wall index (101)]
[level] -> its legend category (1 floor, 2 wall, 3/4 button door closed/open,
5/6 door closed/open, 7 plate, 8 button, 9 rubble, 10 niche, 11/12 stairs,
14 switch, 16 keyhole, 17 illusionary wall, 18 hole, 19 teleporter, 20
portal, 21 eye slot, 22 chain, 23 mounting device, 24 jewel box, 28
pedestal, 29/30 light pad, 31 wall of force, 32 bashable wall).

## What the original's menu items write (traced 2026-10-05)

- Identify all items: bit 40 in byte 2 of every item; the whole table (EOB1
  500 x 14 bytes) written back at once.
- Item usability tweaks: every item type (16 bytes; EOB1 57, EOB2 64 as in
  ITEMTYPE.DAT) byte 5 (allowed classes) = 3F, byte 6 (hands) = 0. Checked
  afterwards; clicking it again only unchecks it (no write).
- Weaken monsters to 1 HP (EOB2 only, greyed out in EOB1): byte 0E (current
  HP) = 1; whole monster table (30 x 30) written back.
- Petrify monsters (EOB2 only): byte 16 |= 20 for monsters with hit points.
- Character editor "Save changes": STR..CHA (cur and max), exceptional STR,
  race, class, alignment, food, HP cur/max, XP 1-3 - not AC or levels.
- Monster HP: byte 0C max, 0E current; tooltips print "(current / max hit
  points)". EOB2 monsters are just "Monster".

## The original's map window details

- Hint files Hints_NN.txt: "#x,y" counted from 1, then the hint id, then the
  text. Shown as bright green (00FF00) cells with a small black number, over
  whatever the cell holds.
- Tooltip (a borderless form, colour 2701640 = #483929, white Consolas 13px):
  empty line, "XX,YY", empty line, then blocks separated by empty lines: the
  cell ("Rubble", "Closed door without an opening button", "Illusionary
  wall"...), "Items:" with "- name" lines (only while items are shown),
  "Monsters:" with "- Kobold (cur / max hit points)" (while monsters are
  shown), "N. hint text". Debug mode adds the raw bytes ("0063. $addr: ..."
  for items, "$addr: ..." for monsters). Plain floor and walls: no tooltip.
- Title while hovering: "(XX,YY)", in debug mode also the cell's four wall
  bytes in hex ("01, 01, 45, 02").
- A block whose four faces are all illusionary walls is drawn grey (BBBBBB)
  until illusionary walls are shown.
- Item names get " +N" / " -N" (value as a signed byte) when the item type's
  extraProperties (bytes 14-15) & 7F is below 4 (weapons, armour, protection
  rings); item 0 is "-", unused items have no name.
- Dumps: Monsters.txt "##   Address      00 .. 1B      XX,YY   Hit points",
  Items.txt with the annotated header, "###   Address    Hex    Item ... Byte
  00..13     Level: XX,YY".

# Eye of the Beholder 3 (AESOP engine, DOS4GW)

From the original ASE3 0.12 (trace, its log, its forms read through Win32
messages) on the eXo copy, Quick Start Party in Burial glen (2026-10-05).

ASE3 polls only two things, 5 times a second: the level map (1024 bytes) and
the party location (4 bytes). It finds them with the newest save: the map by
matching its Maps\NN.dat, the location by searching for the save's x, y,
direction, level ("has to be exactly the same as in the save game").

- Level map: 32 x 32 bytes, row by row; FF open, every wall cell holds
  (x + y) & 1 - all 14 maps follow this, so the page finds the map by that
  structure alone. Two copies were in memory (1E13AA, 21532B); the live one is
  an AESOP heap block (8-byte header, 4 zero bytes then a pointer) and is the
  one ASE3 used.
- Location: x, y, direction (0 N .. 3 W), level; preceded by the party's 7
  member slots (object numbers u16, used ones first, FFFF after). That
  pattern plus "the party stands on an open cell of a map in memory" gives
  exactly one match (1DA9CB).
- Saves: SAVEGAME\SAVEGAME.DIR = 12 names (CRLF, unused "____"); line n is
  ITEMS_nn.BIN (n from 01); ITEMS_00 is the game's own. Location at 252.
  ASE3 lists "%2.2d  %-26.26s  %2.2d: %-22.22s  date".
- ASE3's explored maps: <game>\ASE\Explored_nn.dat, 14 x 1024 bytes 0/1 per
  level, COLUMN by column (x * 32 + y). It marks the party's cell and the 4
  next to it (tested by moving the party through the API).
- Title "%s   [%2.2d,%2.2d]", coordinates from 1.

Character record (same in memory and in ITEMS_nn.BIN; offsets from the name):
-38 27 item slots (u16 object numbers, FFFF empty), 0 name[20], 14 race (16:
Human..Saurial male/female), 15 class, 16 portrait, 19 alignment, 1A-1C
levels, 22 HP (i16), 24 max HP, 28 food, 2A/2E/32 XP (i32, -1 unused), 36
STR, 37 exceptional STR, 38-3C INT WIS DEX CON CHA, 110 + level*10 mage
spells (levels 1-9: 6 6 10 4 3 5 4 2 4), 174 + level*10 cleric spells (1-7:
7 7 7 7 6 4 2); a spell byte is FF (not available) or the memorized count.
Records are 623 bytes apart in memory, 627 in the file (first name at 340);
party member object 20 = record 0. ASE3's in-memory editor reads 444 bytes
from the name (no equipment); its save-file editor shows equipment.

Equipment slot k (memory order) -> ASE3 name: 0-13 Backpack 01-14, 14 Armor,
15 Bracers, 16 Hand 1, 17 Ring 1, 18 Ring 2, 19 Boots, 20 Hand 2, 21-23 Belt
1-3, 24 Medallion, 25 Helmet, 26 Ammunition (found by letting ASE3 set a
different item into each slot of a scratch save). Items.txt: "NNNN  name".

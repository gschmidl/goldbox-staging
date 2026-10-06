# Gold Box games in memory (for gbc.html)

From tracing the original GBC 2.65 (dbxapi32 trace=1) on Pool of Radiance,
GBC's own search log, GBC's Game.dat files and its Resources\Character file
formats, and the coab project (Curse of the Azure Bonds in C#).

## Game.dat (per game, GBC's Games\NN. <game>\)

| offset | |
|---|---|
| 000 | game name (shortstring) |
| 0C9.. | launcher, GOG, config strings |
| 4C0 | start exe, "game.ovr" |
| 5B4.. | save file patterns (CHRDAT%s%d.SAV, SAVGAM%s.DAT, ...) |
| 608 | character record size (PoR 11D) |
| 690, 694 | ? (PoR 2C, 24) |
| 698 | selected character (far pointer) |
| 69C | first character (far pointer) |
| 6A0 | GEO number (byte) |
| 6A4 | area number (byte) |
| 6A8 | area number again? |
| 6AC | current map (far pointer, 4 x 256 bytes) |
| 6B0 | indoor x, y, direction (0-7, 0 north) |
| 6B4 | outdoor x, y |
| 6B8, 6C0 | ? |
| 6BC | mode? (byte) |
| 6C4 | party size (byte) |
| 6C8, 6CC | where the 1st and 2nd ID patterns are |
| 6D0, 7D0 | the two IDs as hex strings (shortstrings) |
| 9740 | area records, 10168 bytes each: name (string[63]), width, height, GEO, area, ? (int32), then N/E walls, S/W walls, events, doors (2501 bytes each) |
| after the areas | Adventurer's Journal texts, random name syllables |

All values above 6C8 are offsets from the program base: base = where the
1st ID is found - [6C8]; the 2nd ID must then be at base + [6CC].

## In memory (PoR, Staging 0.84, base 4F0)

The original polls the first-character pointer, each character record
(285 bytes), the map pointer, x/y/dir, GEO/area and a few mode bytes,
4 times a second; it reads the 1 KB map when the area changes and each
character's effects (9-byte nodes: type, minutes u16, data, flag, next far
pointer). Far pointers are stored offset, segment.

Map (coab GeoBlock): byte[000+y*16+x] = N wall type (high nibble), E (low);
byte[100+..] = S, W; byte[200+..] = event/flags; byte[300+..] = doors, 2
bits per side (N bits 0-1, E 2-3, S 4-5, W 6-7).

Effects.txt: line n (1-based) names effect type n, "+" good, "-" bad.

## More of Game.dat (2026-10-05)

- Area records hold up to 50 areas (0x9740 + 50 x 10168 = 0x85930); after
  the name: width, height, GEO, area, ? (int32 each), the four map arrays
  (2501 bytes each, rows of `width`, equal to the live map), then 16 int32
  wall-type drawing modes and 16 bytes (5 triples, probably linked GEOs).
- Wall modes (first worked out by experiment, then read in GBC's code,
  FUN_000811b8/FUN_00081b20, 2026-10-06): the 16 int32 after the arrays map
  a wall type to a drawing mode: 0 and 1 nothing, 2 a dotted 1-px line, 3
  two cs/5 archway stubs, 7 a wall, 8 a wall that becomes a door (9) when
  either door bit of that side is set, 9 a door. A mode 8 side puts mode 8
  on the neighbour's facing side. The 15 bytes after the modes are five
  special walls [type, door mask, mode] (type -1 ends them): a side whose
  type matches and whose door bits cover the mask takes that mode. Cells
  whose event byte has bit 7 set are drawn a shade darker. Walls are 3 px
  across the edge (1 px past the corners); a door is a 1-px frame cs/4 in
  from the corners and cs/7 deep inside the cell, filled #CCCCCC, joined
  with the neighbour's door and run 4 px outward at the map's edge.
- 0x85930: world map titles: count, ?, ?, then 44-byte entries x, y, map,
  shortstring[32].
- Text section (from "monster\r\n"): name lists (races, classes,
  alignments, genders, statuses, saves, thief skills, spells), <items> (256
  item name parts), <journal N> ... </journal>, random name syllables
  <male_start> <male_end> <female_start> <female_end> <middle>.
- Header: 0x5B4.. save file patterns (CHRDAT%s%d.SAV ..., SAVGAM%s.DAT);
  SAVGAM offsets of GEO 0x610, area 0x62C, x 0x634, y 0x638, dir 0x63C; item
  record size 0x60C, item data offset 0x650 (next-item far pointer at 2A;
  the Dark Queen of Krynn and FRUA keep 63-byte records with the pointer at
  0, as GBC reads them), item data fields 0x658.. (base 0, name 1-3, bonus
  4, save 5, readied 6, unidentified 7, cursed 8, weight 9, amount 11, value
  12, properties 14; GBC's auto-identify zeroes the byte at 0x66C = offset 7).

## What the original GBC writes (traced, PoR)

- ENCAMP - FIX: per member hp := hp max, status := 0, enabled := 1.
- STORE SPELLS: reads the memorized spells field; RESTORE SPELLS writes it
  back (21 bytes in PoR; a list of spell numbers; GBC's editor rebuilds it
  from the start in class, level, number order, see below).
- RACE HACK: non-humans race := human (PoR 7); RESTORE RACES writes the old
  races back.
- Teleport (Ctrl+click): x, y at o[8]; the game shows the new place.

## Combat (PoR)

The monsters follow the party in the character list (hostile = 1); o[9]
(the outdoor x,y otherwise) holds 4-byte entries x, y, list number (from 1),
? ending at the first empty one; o[2] points at the combatant acting. GBC's
combat view: 20 x 20 cells, red/green squares with hit points, the actor
grey. The mode byte o[11] stays 1 in town and in combat.

## Icons

Head.bmp/Body.bmp: 24x24 cells, row = icon size - 1, column = head/body
number (0-based); the head's non-background (55 55 55) pixels over the body;
EGA colours 1 2 3 4 6 7 of the sheets take the low nibbles of the six icon
colour bytes (body, arm, leg, hair, shield, weapon), 9 10 11 12 14 15 the high
nibbles (coab's CombatIcon). Matches GBC's HUD pixel for pixel.

## From GBC 2.65's decompilation (Ghidra 12.1.4, re\gbc\decomp, 2026-10-06)

Every code path of GBC.exe was compared with the page and the page changed
to match; the units are re\gbc\decomp\GBC_*.c (gitignored), the names in
re\gbc\strings.txt, the forms in re\gbc\forms. Facts the page now relies on:

- Fields are numbered from 1 in GBC's order (strings.txt line 233+; the page's
  GBC_NAMES): 1 next_character_address ... 24 race, 26 class, 30/31 flags,
  41-47 scores current, 49 hp max, 50 hp current, 52 highest hps, 53 status,
  54 enabled, 55-62 saves, 63 experience, 64 highest experience, 67 able to
  train, 68-76 levels, 77-85 former levels, 86/87 level highest 1/2, 89-97
  highest levels, 98/99 drained levels/hps, 100-102 knight/god/robe, 103-110
  thief skills, 121/122 ac base/current, 124/125 thac0, 126/127 attacks,
  136-141 current rolls/dice/modifier, 143 quickfight, 144 movement base,
  146 item limits, 147 number of items, 150 hostile, 173 magic resistance,
  174-180 cleric, 181-189 mage, 190-196 druid spells per day, 198 known
  spells (16-byte bitmap), 199 memorized spells, 200-499 known-spell bytes
  (cleric_1_01 ...), 500-799 their bitmap variants (cleric_1_01_bit).
- Game.dat: the field table at 8B8 + id * 18 (int32 offset, byte length, int32
  text list start and count, bytes 10-12 class/level/number for spells) is
  what GBC uses (the format texts match it except Death Knights' spell block
  fields and Treasures' movement current, which lies past the record and so
  is never read); 610 the size of the block Death Knights keeps behind the
  spells address pointer (220 bytes; field offsets from 216 on are in it);
  68C the effect record size (9, FRUA 10; the next pointer in the last 4);
  53C0/5C30/64A0 + ((class * 9 + level) * 15 + n) * 4 the known field id,
  the bitmap number and the memorized number of a spell; 6CFC + value * 20
  the reverse map of a memorized value (class, level, number, id, bit); area
  record + 2768 the wall modes, + 27A8 the special walls; 85938 the journal
  count, 8593C + 44 * i the world titles (x, y, map, name; the map is the
  Pools of Darkness world number from o[6]).
- Far pointers: segment * 16 + offset (the page) = GBC's value - its base - 20.
- Every read: Pool of Radiance paladins/rangers get level_fighter :=
  level_highest_1 in combat, 0 outside; quickfight 1 -> 0 outside combat (no
  setting); drained = field 98 (255 -> 0) or, in the games with highest
  levels, the sum of highest - level over the classes; the last undrained
  record of each party slot is kept for FIX DRAIN; a hit point drop in
  combat flashes (2 ticks) the icon frame (#550000) and the battlefield box
  (#FF0000 / #880000).
- Effects: the chain order (not sorted), each "name (duration)" when the low
  duration byte is set (FRUA: bytes 2-3), "- N levels drained" first; names
  containing held / helpless / asleep flag the character for the combat X.
- Pending writes (FUN_00098684 / FUN_0009e690 / FUN_0009c680): an operation
  collects field values and writes them together; a value passes when
  higher than the current one and than what is already pending, for saves
  1-5 when lower (the Dark Queen's zero saves take anything), item limits
  always; cleric spells 6/7 need wisdom 17/18, mage spells 5-9 intelligence
  10/12/14/16/18; -99 means leave it; equal values are not written.
- FIX DRAIN: restore from the slot's undrained record fields [49, 124, 125,
  55-59, 86, 63, 68-76, 174-192] (174-191 not when 0), then 98 and 99 := 0;
  without it, from highest_level_* (level_highest_1 := max), highest
  experience and highest hps, which are then zeroed; then FIX STATS.
- Experience: Data\Experience.dat, 30 tables of 31-byte strings class, god,
  knight, robe and 41 int32 ([level] = XP); the table name "cleric_mishakal"
  is also the Levels.txt section name and the max-levels key; per character
  the most XP a current level needed (max cur) and the least a next level
  needs (min next) give the XP meter (xp - maxcur) / (minnext - maxcur), its
  colours #666666 / #CC9900 able to train / #CC0000 drained; Secret of the
  Silver Blades' paladin level 15 needs 2459233.
- Level up (FUN_0009fcc8 / FUN_0009f188 / FUN_000b00a0): one class per step,
  the one with the least next XP the character has, not past the max level;
  hp_add dice + constitution bonus [1,2,3,4,5,5,6,6,6,7,7] for 15-25 (over 2
  only for fighter/paladin/ranger), divided by the number of classes; hp max
  and current := max + gain, rolled += gain; thief skills + dexterity row
  (9-25) + race row; cleric spells 1-4 + wisdom bonus (13: 1; 14: 2; 15: 2,1;
  16: 2,2; 17: 2,2,1; 18+: 2,2,1,1); mages and rangers pick one unknown
  spell of a level with slots; a dual-classed character regains the former
  class's line (and its level 1 item limits) on reaching its level + 1, no
  hit points until then; then level_<class> and level_highest_1 := level,
  ac/thac0 current += base change, able_to_train := 0.
- FIX STATS (FUN_000a0408): dual-classed members' spells per day zeroed, then
  per class (and the former class once level highest 1 > 2) the Levels.txt
  line's [121, 124, 126, 144, 55-59, 174-192] through the pending rules.
- Editor: Convert to paladin/ranger (single-class level 1 fighter): levels
  68-76 := 0, class, level 1, paladin saves 12 13 14 15 15, item limits 40;
  monk (level 1 thief): item limits 0, hp max/current + 2; FIX STATS on.
  A changed ability also sets its original. Item changes write the 17 DAX
  bytes only. Effect changes write the record less its pointer. Cheat mode
  ("cheat" typed once, saved) gates the editor in combat, item and effect
  changes and teleports.
- Items: name parts 1, 2, 3 in order from <items>, " (amount)" when > 1,
  Secret of the Silver Blades base type 73 "Bundle of N Scrolls (DON'T
  EDIT)"; auto-identify writes 0, or for Krynn scrolls (type 39) 0x20/0x10
  by the third name part ('w'/'x' in Champions and Death Knights, 88/98 ->
  10, 89/97 -> 20 in the Dark Queen); auto-ammo base types per game
  [73,28,9] [73,28,9] [30,12,5] [30,12,5] [30,5] [30,5] [30,12,5] [73,28,9]
  [30,12,5] [30,12,5] - -, max plus per game 0 0 1 2 0 1 2 0 1 1 (Configuration.txt).
- Map: explored = the party's cell when facing 0/2/4/6; 10-px border, cells
  cs-1 at +1 (#AA8C46, #A2843E flagged), notes orange #F2843E boxes inset
  cs/7 with Verdana cs/3 pt white over black; events Consolas 8 black (top
  bit masked except Dark Queen/FRUA); party triangle inset cs/5 (#00AA00,
  #005500 edge 1 px, 2 from cs 32), facing 0/2/4 else west; mouse cell 2-px
  white frame; notes only in the notes view; GBC's note ID suggestion =
  highest number + 1 or count + 1. FRUA's map comes from the design's
  geoNNN.dat files found in memory (not implemented; FRUA has no o[7]).
- Combat view (FUN_000887e4): N = the spread snapped to 20/25/.../50, cell =
  (width - 20) / N, origin the spread's centre - N/2 + 1; boxes w x h cells
  by the entry's size code [1x1, 1x2, 2x1, 2x2, 3x2] for enabled combatants;
  grey #999999/#004400 acting, red #CC0000/#550000 hostile (field 150 = 1),
  green #00AA00/#005500 else; red X (pen 2) when held/helpless/asleep; HP in
  Arial Narrow 0.32 cell pt, white over black; grid #8A722A on #A2843E.
  A click on an enabled combatant opens the editor (cheat mode).
- Statistics window: "k. name (x,y)", HP bar, Scores (str with " (xx)"
  exceptional, 100 -> 0), Saves, Magic resistance, AC/THAC0 = 60 - current,
  "n attacks per round (RdD+M)", flag names (format list, GBC's defaults,
  "?" skipped), effects.
- World map: the image stretched into the window less 10 px in o[0] x o[1]
  cells; titles Arial Narrow width/70 pt at cell x + cw/2, y - ch/2 (one-cell
  worlds: percentages of the width), white over two black shadows, on grey
  #808080 in PoR, Curse, Pools of Darkness, Champions, Death Knights; the
  party a white cell with a black frame. Gateway: GEO 21-24 in quarter-width
  squares across the top, 25-28 below shifted 1.25 squares right; Treasures:
  GEO 51-57 at fixed fractions of the width (0.25/0.27 etc.); the party a
  white triangle in a 16th of a quarter square. Clicks use Round().
- HUD menu: upper row MAP .. QUIT, lower JOURNALS .. SEARCH WIZARD (LEVEL UP
  needs someone able to train; EDITOR disabled in combat without cheat mode;
  spells/races/level up not in the Buck Rogers games); SETTINGS and
  JOURNALS are pages in the same rows (journal ranges of 10, then the
  numbers; MANUAL, JOURNAL, CLUEBOOK, PASSWORDS).
- Random names: start + end syllable, female names a middle one in 21 of
  100, capitalised; 10 rows of 5 male then female.
- Backup save: SAVGAM<slot>*, CHRDAT<slot>*, VAULT<slot>*, Silver Blades'
  VAULT.DAT, Gateway's VAULT.<slot>.

Verified with a mock of Staging's API (scratchpad mockapi.py: Pool of
Radiance's eXo saved party, an area from Game.dat, a staged combat): HUD,
map, combat view, statistics, world map, editor, HUD menu pages, level-up
plans. Not yet run against a live game after these changes.

## FRUA's map (2026-10-06, from GBC_Map.c FUN_00084aa4 / FUN_00080e2c)

GBC has no Game.dat areas for Unlimited Adventures. It reads the design's
geoNNN.dat (NNN = the game's GEO 2 byte, o[5]) from the design folder the
user picks in its Design_ComboBox (the page: the folder START.DAT names - the
shell's last choice - or the "FRUA design..." setting):

- header: 1A height, 1B width (maps are up to 24 x 24, 576 cells; the HEIRS
  design has 38 x 15 overland maps and 20 x 28 keeps), 8E the map's name (16
  chars), 142 the cells (w x h x 6 bytes: N E S W wall bytes, event number,
  one more), EC2 an "ENCR" chunk whose 2000 data bytes start at ECA; the file
  must be at least 169A bytes.
- GBC searches the game's first megabyte for the wall block and then for the
  encounter block (" - Map wall data found at $%x." / " - Map event data
  found at $%x."; "MAP %d DOES NOT MATCH MEMORY!" after 10 failures) and reads
  the walls from memory; the page re-reads them every tick.
- a wall byte with a type in its low nibble is a wall side: drawing mode 8
  when its top three bits are set (E0), mode 9 (door) otherwise; mode 8 is
  put on the neighbour's facing side too (as for the other games); no
  special walls, no door bits, no "flagged" (80) cells; event numbers are
  the 5th byte, shown unmasked.
- the explored data is keyed by the GEO number (GBC: a dynamic area record
  per map name, FUN_00080cf8); the title and the saved games list use the
  geo file's name (GBC: BytesToStr(file, 8E, 16)); FRUA's saves are in the
  design folder's SAVE\ (SAVGAM<L>.CSV, VAULT<L>.DAT).
- checked against a mock of the API (scratchpad mockfrua.py: the HEIRS design,
  its maps 10 and 5 placed in memory), not against the game.

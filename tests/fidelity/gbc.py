"""Gold Box Companion 2.65 against gbc.html, with the twelve Gold Box games.

Each game keeps its data at fixed offsets from its program's base (GBC's
Game.dat: the two ID patterns, the first character's far pointer, the GEO and
area numbers, the map's far pointer, x, y and direction, the party size);
the characters are a chain of records (the game's own format, the same as in
its CHRDATAn saved characters), each with far pointers to its effects. The
test builds that memory from the eXo saved characters where there are some
(the record fields of another game's otherwise, by GBC's field names), an
area of the game's Game.dat as the live map, and combat states of its own."""
import hashlib
import json
import math
import re
import shutil
import struct
import time
import zipfile
from ctypes import wintypes
from pathlib import Path

import harness
import original

MEM = 1 << 20
BASE = 0x10000           # the game program's base
REC_AT = 0x70000         # the character records, 0x400 apart
FX_AT = 0x78000          # their effects
MAP_AT = 0x7C000         # the live map (4 x 256 bytes)
EXT_AT = 0x7E000         # Death Knights of Krynn's spell blocks
ITEM_AT = 0x60000        # the members' items, 0x800 apart
FRUA_WALLS_AT = 0x80000  # FRUA: the GEO file's walls, 6 bytes a cell
FRUA_EVENTS_AT = 0x82000  # and its 2000 bytes of encounter data
# the fields of the item tables' bytes in an item: where Game.dat says they are, their length
ITEM_FIELDS = {'base': (0x658, 1), 'name': (0x65C, 1), 'bonus': (0x660, 1), 'save': (0x664, 1), 'readied': (0x668, 1),
               'unid': (0x66C, 1), 'cursed': (0x670, 1), 'weight': (0x674, 2), 'amount': (0x678, 1), 'value': (0x67C, 2),
               'special': (0x680, 1)}
# the base types of arrows, bolts and darts (GBC's table, as the page has it)
AMMO = {1: (73, 28, 9), 2: (73, 28, 9), 3: (30, 12, 5), 4: (30, 12, 5), 5: (30, 5), 6: (30, 5), 7: (30, 12, 5), 8: (73, 28, 9),
        9: (30, 12, 5), 10: (30, 12, 5)}
FOLDERS = {1: 'poolrad', 2: 'curse', 3: 'secsilbl', 4: 'pooldark', 5: 'ckrynn', 6: 'dkkrynn', 7: 'drkqueen', 8: 'gatesf',
           9: 'treassav', 10: 'unlimadv', 11: 'brcdoom', 12: 'brmatrix'}
PAGE = (harness.REPO / 'web' / 'gbc.html').read_text('utf-8')
GAME_INFO = json.loads(re.search(r'const GAME_INFO = (.*?);\n', PAGE).group(1))
FIELDS = json.loads(re.search(r'const FIELDS = (.*?);\n', PAGE, re.S).group(1))
VALUES = json.loads(re.search(r'const VALUES = (.*?);\n', PAGE).group(1))
# GBC's field names, numbered from 1
GBC_NAMES = ''.join(re.findall(r"'([^']*)'", re.search(r'const GBC_NAMES = \((.*?)\)\.split', PAGE, re.S).group(1))).split(' ')


def farptr(addr):
    return struct.pack('<HH', addr & 15, addr >> 4)


def put_field(rec, f, name, value):
    if name not in f:
        return
    off, n = f[name]
    if off + n > len(rec):
        return
    if isinstance(value, (bytes, bytearray)):
        rec[off:off + n] = bytes(value[:n]).ljust(n, b'\0')
    else:
        rec[off:off + n] = (value & ((1 << 8 * n) - 1)).to_bytes(n, 'little')


def gamedat_name(gamedat, at, slot='A', n=0):
    """A saved game file name from Game.dat's patterns (16-byte Pascal strings: 5B5 the
    characters, 5C5 their items, 5D5 Death Knights' spell blocks, 5E5 the effects, 5F5 the
    saved game; CHRDAT%s%d.SAV ...) for a slot and character number; '' where it has none."""
    k = gamedat[at]
    return gamedat[at + 1:at + 1 + k].decode('latin-1').replace('%s', slot).replace('%S', slot).replace('%d', str(n)) if k else ''


def find_file(folder, name):
    """name (any case) where GBC looks for saved games: in folder's SAVE folder when it has one
    (only there then: the Dark Queen of Krynn's eXo folder has an older saved game A beside
    it), else in folder."""
    if not name:
        return None
    d = next((p for p in folder.iterdir() if p.is_dir() and p.name.lower() == 'save'), folder)
    return next((q for q in d.iterdir() if q.is_file() and q.name.upper() == name.upper()), None)


def saved_records(folder, gamedat, rec, ext, slot='A'):
    """Saved game A's party as Game.dat names its files - [(record, spell block, effects,
    items)], the items as the game keeps them in memory (records of Game.dat 60C bytes; the
    Dark Queen of Krynn's and FRUA's 63 bytes with the item tables' bytes at 650). The Dark
    Queen of Krynn and FRUA keep the characters in the saved game itself: from Game.dat 620
    on, each its record, its items (the item tables' 60C bytes each, as many as the record's
    item count) and its effects (614 bytes each, chained by their last four bytes), as many
    characters as the byte at 618 says."""
    item, dax = (struct.unpack_from('<i', gamedat, a)[0] for a in (0x60C, 0x650))
    if not gamedat[0x5B5]:
        f = find_file(folder, gamedat_name(gamedat, 0x5F5, slot))
        if not f:
            return []
        d = f.read_bytes()
        count_at, fxn, at = (struct.unpack_from('<i', gamedat, a)[0] for a in (0x618, 0x614, 0x620))
        fields = FIELDS[str(gamedat[0])]
        n_items, fx_ptr = fields['number_of_items'][0], fields['effects_address'][0]
        out = []
        for _ in range(d[count_at] if 0 <= count_at < len(d) else 0):
            r = bytearray(d[at:at + rec])
            at += rec
            items = []
            for _ in range(r[n_items]):
                full = bytearray(63)
                full[dax:dax + item] = d[at:at + item]
                items.append(full)
                at += item
            effects = b''
            more = any(r[fx_ptr:fx_ptr + 4])
            while more and at + fxn <= len(d):
                e = d[at:at + fxn]
                effects += e
                at += fxn
                more = any(e[fxn - 4:])
            out.append((r, b'', effects, items))
        return out
    out = []
    for n in range(1, 9):
        p = find_file(folder, gamedat_name(gamedat, 0x5B5, 'A', n))
        if not p or len(p.read_bytes()) < rec:
            continue
        wiz = find_file(folder, gamedat_name(gamedat, 0x5D5, 'A', n))
        fx = find_file(folder, gamedat_name(gamedat, 0x5E5, 'A', n))
        itm = find_file(folder, gamedat_name(gamedat, 0x5C5, 'A', n))
        d = itm.read_bytes() if itm else b''
        out.append((bytearray(p.read_bytes()[:rec]), wiz.read_bytes()[:ext] if wiz and ext else b'',
                    fx.read_bytes() if fx else b'', [bytearray(d[k:k + item]) for k in range(0, len(d) - item + 1, item)]))
    return out


class Run:
    # FRUA plays a design: Heirs to Skull Crag (its saved game B), the only folder of its copied
    DESIGN = {10: ('HEIRS.DSN', 'B')}

    def __init__(self, work, tool_dir, game_dir, fake, browser, out):
        self.work, self.out, self.fake, self.browser = Path(work), Path(out), fake, browser
        name = Path(game_dir).name.lower()
        self.games_root = Path(game_dir).parent
        self.g = next(k for k, v in FOLDERS.items() if v == name)
        self.info, self.f = GAME_INFO[self.g - 1], FIELDS[str(self.g)]
        self.design, self.slot = self.DESIGN.get(self.g, ('', 'A'))
        self.game = self.work / name
        if self.game.exists():
            shutil.rmtree(self.game)

        def skip(d, names):
            top = Path(d) == Path(game_dir)
            return [n for n in names if n.lower().endswith('.pdf') or (Path(d) / n).is_file() and (Path(d) / n).stat().st_size > 4 << 20
                    or self.design and top and (Path(d) / n).is_dir() and n.upper() != self.design]
        shutil.copytree(game_dir, self.game, ignore=skip)
        # where the saved games are: the game's folder (or its SAVE folder), FRUA's design's
        self.saves = self.game / self.design if self.design else self.game
        for p in Path(game_dir).iterdir():
            if p.suffix.lower() == '.pdf':
                (self.game / p.name).write_bytes(b'%PDF-1.0\n')
        self.tool = self.work / 'GBC'
        if not (self.tool / 'GBC.exe').exists() or getattr(Run, 'prepared', None) != str(tool_dir):
            self.patch_log = original.prepare_tool(tool_dir, self.tool, harness.SANDBOX_DLL,
                                                   skip=('DAX-*', 'FRUA_Patches', 'Resources'))
            Run.prepared = str(tool_dir)
        self.gamedat = (self.tool / 'Games' / self.info['dir'] / 'Game.dat').read_bytes()
        self.borrow_saves()
        self.fix_saved_area()
        self.party = self.make_party()
        fake.routes.update({'': str(harness.REPO / 'web'), 'game/': str(self.game), 'gbc/': str(self.tool)})

    def make_party(self):
        """The saved party; one of fewer than two (FRUA's: one) with Curse of the Azure Bonds'
        after it in this game's fields (GBC checks the saved characters' names)."""
        rec, ext = self.info['rec'], self.info['ext']
        recs = saved_records(self.saves, self.gamedat, rec, ext, self.slot)
        if len(recs) >= 2:
            return recs[:6]
        out = list(recs)
        curse = (self.tool / 'Games' / GAME_INFO[1]['dir'] / 'Game.dat').read_bytes()
        for r, *_ in saved_records(self.games_root / FOLDERS[2], curse, GAME_INFO[1]['rec'], 0)[:6 - len(out)]:
            mine = bytearray(rec)
            for name, (off, n) in FIELDS['2'].items():
                if name.endswith('_address') or name not in self.f:
                    continue
                put_field(mine, self.f, name, r[off:off + n] if n > 4 else int.from_bytes(r[off:off + n], 'little'))
            out.append((mine, b'', b'', []))
        return out

    def areas(self):
        """Game.dat's areas: [(name, GEO, area, the map's four arrays of width x height bytes one
        after the other, (width, height))]."""
        gd, found = self.gamedat, []
        for a in range(50):
            oo = 0x9740 + a * 10168
            n = gd[oo]
            if not n or n > 63:
                break
            w, h, geo, area = struct.unpack_from('<4i', gd, oo + 64)
            arrays, k = gd[oo + 84:oo + 84 + 4 * 2501], min(max(w * h, 0), 2501)
            live = b''.join(arrays[j * 2501:j * 2501 + k] for j in range(4))
            found.append((gd[oo + 1:oo + 1 + n].decode('latin-1'), geo, area, live, (w, h)))
        return found

    def area(self, geo, area):
        """The area of that GEO and area number (else the first with walls)."""
        all_ = self.areas()
        return next((a for a in all_ if a[1] == geo and a[2] == area), None) or \
            next((a for a in all_ if sum(a[3][:256]) > 300), ('', geo, area, bytes(1024), (16, 16)))

    def saved_file(self):
        """Saved game A's file (Game.dat's SAVGAM%s.DAT / .PTY / .QSV / .CSV)."""
        return find_file(self.saves, gamedat_name(self.gamedat, 0x5F5, self.slot))

    def borrow_saves(self):
        """Gateway to the Savage Frontier's eXo folder has no saved game, only exported
        characters: the test's copy gets Curse of the Azure Bonds' saved game A, which is in
        the same format (records, items, effects, the position)."""
        if self.g != 8 or self.saved_file():
            return
        src = self.games_root / FOLDERS[2]
        save = next((p for p in self.game.iterdir() if p.is_dir() and p.name.lower() == 'save'), self.game / 'SAVE')
        save.mkdir(exist_ok=True)
        curse = (self.tool / 'Games' / GAME_INFO[1]['dir'] / 'Game.dat').read_bytes()
        names = [gamedat_name(curse, 0x5F5, 'A')] + [gamedat_name(curse, at, 'A', n) for n in range(1, 9)
                                                     for at in (0x5B5, 0x5C5, 0x5E5)]
        for name in names:
            f = find_file(src, name)
            if f:
                shutil.copyfile(f, save / f.name.upper())

    def saved_offsets(self):
        """Where saved game A keeps GEO, area, x, y, direction (Game.dat 628-63C; a GEO at
        -1 is 1, as GBC takes it)."""
        return [struct.unpack_from('<i', self.gamedat, a)[0] for a in (0x628, 0x62C, 0x634, 0x638, 0x63C)]

    def saved_position(self):
        """GEO, area, x, y, direction of saved game A (SAVGAMA.DAT)."""
        offs, f = self.saved_offsets(), self.saved_file()
        if not f:
            return [1, 1, 5, 7, 2]
        d = f.read_bytes()
        out = [d[k] if 0 <= k < len(d) else 0 for k in offs]
        if offs[0] < 0:
            out[0] = 1
        return out

    def fix_saved_area(self):
        """GBC checks the area in memory against saved game A's: one outside Game.dat's areas
        (the wilderness, a town's menu) is moved, in the test's copy, into the first area
        of its GEO with walls (any GEO's when that has none)."""
        f, (sg, sa) = self.saved_file(), self.saved_position()[:2]
        areas = self.areas()
        if not f or not areas or any(a[1] == sg and a[2] == sa for a in areas):
            return
        walled = [a for a in areas if sum(a[3][:256]) > 300] or areas
        pick = next((a for a in walled if a[1] == sg), walled[0])
        d, offs = bytearray(f.read_bytes()), self.saved_offsets()
        for k, v in ((offs[0], pick[1]), (offs[1], pick[2])):
            if 0 <= k < len(d):
                d[k] = v & 255
        f.write_bytes(bytes(d))

    def state(self, **kw):
        return State(self, **kw)


class State:
    """A Gold Box game in memory: its IDs, the party, the area, the position."""

    def __init__(self, run, members=None, x=None, y=None, d=None, geo=None, area=None, mode=1, hp=None, fields=None,
                 effects=None, combat=None, out=None, item_fields=None, extra_items=None, geo3=None):
        """members: how many of the saved party (GBC checks all the saved game's names); the
        place: saved game A's unless given (GBC checks the GEO against it); fields: {member:
        {GBC field name: value}} changed in the records; effects: {member: [(type,
        duration)]} instead of the saved ones; combat: {'monsters': [(name, hit points,
        maximum)], 'places': [(list number, x, y, size code)], 'selected': list number} -
        the monsters follow the party in the chain (copies of its first record), the party's
        combat pointers are set, the places are the battlefield list; item_fields: {member:
        {item number: {ITEM_FIELDS name: value}}} changed in the items; extra_items: {member:
        n} copies of the member's last item added; geo3: the byte at Game.dat's sixth offset
        (Pools of Darkness' world) instead of the area number."""
        sg, sa, sx, sy, sd = run.saved_position()
        self.run, self.mode = run, mode
        self.x, self.y, self.d = (sx if x is None else x), (sy if y is None else y), (sd if d is None else d)
        self.members = len(run.party) if members is None else members
        self.name, self.geo, self.area_no, self.map, self.map_size = run.area(sg if geo is None else geo,
                                                                               sa if area is None else area)
        self.hp = hp or {}
        self.fields = fields or {}
        self.effects = effects
        self.combat = combat
        self.out = out   # the outdoor (world map) x, y
        self.item_fields = item_fields or {}
        self.extra_items = extra_items or {}
        self.geo3 = geo3

    def items_of(self, i, items):
        """Member i's items as this state has them."""
        items = [bytearray(x) for x in items]
        if items and self.extra_items.get(i):
            items += [bytearray(items[-1]) for _ in range(self.extra_items[i])]
        gd, dax = self.run.gamedat, struct.unpack_from('<i', self.run.gamedat, 0x650)[0]
        for k, changes in self.item_fields.get(i, {}).items():
            if k < len(items):
                for name, value in changes.items():
                    o = dax + struct.unpack_from('<i', gd, ITEM_FIELDS[name][0])[0]
                    for b in range(ITEM_FIELDS[name][1]):
                        items[k][o + b] = value >> 8 * b & 255
        return items

    def image(self):
        r, info, f = self.run, self.run.info, self.run.f
        o = info['o']
        mem = bytearray(MEM)

        def put(addr, data):
            mem[addr:addr + len(data)] = data

        for k, key in ((14, 'id1'), (15, 'id2')):
            put(BASE + o[k], bytes.fromhex(info[key]))
        party = r.party[:self.members]
        records = list(party)
        cb = self.combat
        for name, hp, hp_max in (cb or {}).get('monsters', []):
            rec = bytearray(party[0][0])
            nb = name.encode('latin-1')
            put_field(rec, f, 'name_length', len(nb))
            put_field(rec, f, 'name', nb)
            put_field(rec, f, 'hit_points_current', hp)
            put_field(rec, f, 'hit_points_maximum', hp_max)
            put_field(rec, f, 'hostile', 1)
            put_field(rec, f, 'enabled', 1)
            records.append((rec, party[0][1], b'', []))
        addrs = [REC_AT + i * 0x400 for i in range(len(records))]
        fx_at = FX_AT
        for i, (rec, ext, fx, items) in enumerate(records):
            rec = bytearray(rec)
            for key in ('next_character_address', 'effects_address', 'items_address', 'combat_address'):
                put_field(rec, f, key, b'\0\0\0\0')
            put_field(rec, f, 'next_character_address', farptr(addrs[i + 1]) if i + 1 < len(records) else b'\0\0\0\0')
            if cb and i < len(party):
                put_field(rec, f, 'combat_address', farptr(0x7F000))
            # the member's items: a chain of records (the far pointer to the next at 2A, in the
            # Dark Queen of Krynn and FRUA at 0), each member's 0x800 bytes from ITEM_AT on
            items = self.items_of(i, items)[:24] if i < len(party) else []
            if items and self.extra_items.get(i):
                put_field(rec, f, 'number_of_items', len(items))
            if items:
                size, nxt, at0 = max(len(x) for x in items), 0 if r.g in (7, 10) else 0x2A, ITEM_AT + i * 0x800
                put_field(rec, f, 'items_address', farptr(at0))
                for j, it in enumerate(items):
                    it = bytearray(it)
                    it[nxt:nxt + 4] = farptr(at0 + (j + 1) * size) if j + 1 < len(items) else b'\0\0\0\0'
                    put(at0 + j * size, it)
            n = info['fx']
            effects = [bytearray(fx[k:k + n]) for k in range(0, len(fx) - n + 1, n)]
            if self.effects is not None:
                effects = []
                for typ, dur in self.effects.get(i, []):
                    e = bytearray(n)
                    e[0] = typ
                    at = 2 if n == 10 else 1   # Unlimited Adventures keeps the duration a byte later
                    e[at:at + 2] = struct.pack('<H', dur)
                    effects.append(e)
            if effects:
                put_field(rec, f, 'effects_address', farptr(fx_at))
                for j, e in enumerate(effects):
                    e[n - 4:n] = farptr(fx_at + n) if j + 1 < len(effects) else b'\0\0\0\0'
                    put(fx_at, e)
                    fx_at += n
            if info['ext']:
                put_field(rec, f, 'spells_address', farptr(EXT_AT + i * 0x100))
                put(EXT_AT + i * 0x100, bytes(ext).ljust(info['ext'], b'\0'))
            if i in self.hp:
                put_field(rec, f, 'hit_points_current', self.hp[i])
            for name, value in self.fields.get(i, {}).items():
                put_field(rec, f, name, value)
            put(addrs[i], rec)
        if addrs:
            put(BASE + o[3], farptr(addrs[0]))
            put(BASE + o[2], farptr(addrs[(cb or {}).get('selected', 1) - 1]))
        if o[13]:
            put(BASE + o[13], bytes([len(party)]))
        if cb and o[9]:
            # the battlefield: x, y, list number, size code (the Dark Queen of Krynn and
            # Unlimited Adventures: x, -, y, -, number, code); an x out of range ends it
            six = r.g in (7, 10)
            at = BASE + o[9]
            for k, x, y, code in cb.get('places', []):
                put(at, bytes([x, 0, y, 0, k, code] if six else [x, y, k, code]))
                at += 6 if six else 4
            put(at, bytes([0xFF] * (6 if six else 4)))
        if o[11]:
            put(BASE + o[11], bytes([self.mode]))
        if o[7]:
            # the map's arrays one after the other; the Dark Queen of Krynn's after its size
            # (height, width: GBC takes the arrays' size from there)
            w, h = self.map_size
            put(MAP_AT, (bytes([h & 255, w & 255]) if r.g == 7 else b'') + self.map)
            put(BASE + o[7], farptr(MAP_AT))
        if r.g == 10:
            # FRUA: GBC finds the map by the design's GEO file (the GEO 2 byte's), its walls
            # and its encounter data, in memory
            name = f'GEO{self.area_no:03d}.DAT'
            geo = next((p for p in (r.game / r.design).iterdir() if p.name.upper() == name), None)
            if geo:
                d = geo.read_bytes()
                put(FRUA_WALLS_AT, d[0x142:0x142 + d[0x1A] * d[0x1B] * 6])
                put(FRUA_EVENTS_AT, d[0xECA:0xECA + 2000])
        if o[4]:
            put(BASE + o[4], bytes([self.geo & 255]))
        if o[5]:
            put(BASE + o[5], bytes([self.area_no & 255]))
        if o[6]:
            put(BASE + o[6], bytes([(self.area_no if self.geo3 is None else self.geo3) & 255]))
        put(BASE + o[8], bytes([self.x, self.y, self.d]))
        if self.out and o[12]:
            # Pool of Radiance and Champions of Krynn keep x, -, y (Pool of Radiance's world map
            # page in the byte at 166DC, 25 for the first); the others x, y
            ox, oy = self.out
            put(BASE + o[12], bytes([ox, 0, oy] if r.g in (1, 5) else [ox, oy]))
            if r.g == 1:
                put(BASE + 0x166DC, bytes([25]))
        return bytes(mem)


class Common(harness.Side):
    def __init__(self, run):
        super().__init__(run, run.fake)
        self.pending = []

    def set(self, st):
        img = st.image()
        self.fake.reset(img, size=MEM)
        self.base = img
        self.cur = st

    def poke(self, st):
        img = st.image()
        self.fake.put(0, img)
        self.base = img
        self.cur = st

    def memory_changes(self):
        mem = self.fake.get(0, len(self.base))
        return [f'{i:X}: {a:02X} -> {b:02X}' for i, (a, b) in enumerate(zip(self.base, mem)) if a != b]

    def answer(self, *answers):
        self.pending += answers


def settings_dat(template, g, folder, title, start, end, design=''):
    """GBC's Data\\Settings.dat (4060 bytes): the game folders (15 x 201), the DOSBox window
    titles (15 x 51), the search ranges (15 + 15 int32), the last addresses found, the
    chosen game, the map's size, the option bytes (auto-identify, fix stats, fix drain,
    HUD on top, auto-ammo: off; the HUD's parts: on), FRUA's design (51 bytes at FA8)."""
    d = bytearray(template.ljust(0xFDC, b'\0')[:0xFDC])
    i = g - 1
    f = folder.encode('mbcs')[:200]
    d[i * 201:(i + 1) * 201] = bytes([len(f)]) + f.ljust(200, b'\0')
    t = title.encode('mbcs')[:50]
    d[0xBC7 + i * 51:0xBC7 + (i + 1) * 51] = bytes([len(t)]) + t.ljust(50, b'\0')
    struct.pack_into('<i', d, 0xEC4 + i * 4, start)
    struct.pack_into('<i', d, 0xF00 + i * 4, end)
    for k in range(15):
        struct.pack_into('<i', d, 0xF3C + k * 4, 0)
    struct.pack_into('<i', d, 0xF88, g)
    # the map docked right of DOSBox at its height, no title hack
    struct.pack_into('<3i', d, 0xF90, 1, 0, 0)
    d[0xF9C:0xFA1] = b'\1' * 5
    d[0xFA1:0xFA8] = bytes(7)
    n = design.encode('mbcs')[:50]
    d[0xFA8:0xFA8 + 51] = bytes([len(n)]) + n.ljust(50, b'\0')
    return bytes(d)


class Original(Common):
    which = 'original'

    def start(self, fit=False):
        r = self.run
        dat = r.tool / 'Data' / 'Settings.dat'
        template = dat.read_bytes() if dat.exists() else b''
        dat.write_bytes(settings_dat(template, r.g, str(r.game) + '\\', self.fake.title, 0x1000000, 0x1000000 + MEM, r.design))
        # the explored maps start empty (FRUA's are per design: <design>_Explored.dat, one
        # shipped with GBC for Heirs to Skull Crag)
        for name in ('Explored.dat', f'{r.design}_Explored.dat'):
            explored = r.tool / 'Games' / r.info['dir'] / name
            if explored.exists():
                explored.unlink()
        self.t = original.Tool(r.tool / 'GBC.exe', [], self.fake, r.work)
        self.main = self.t.find('TMain_Form', timeout=15)
        if not self.main:
            raise RuntimeError('GBC did not open its window')
        self.t.main = self.main
        self.t.place(self.main, -2540, 20)
        time.sleep(1.0)
        # the saved game the party comes from (GBC looks for its characters), then the search
        self.t.click_button(self.t.control('TButton', h=self.main, text=r.slot))
        time.sleep(1.0)
        self.t.click_button(self.t.control('TButton', h=self.main, text='Search'))
        self.hud = self.t.find('THUD_Form', timeout=30)
        if not self.hud:
            memo = self.t.control('TMemo', h=self.main)
            raise RuntimeError('GBC did not find the game: ' + (original.window_text(memo)[-600:] if memo else ''))
        self.map = self.t.find('TMap_Form', timeout=10)
        # GBC sizes its map window after showing it: its size once it stays
        last, end = None, time.monotonic() + 10
        while self.map and time.monotonic() < end:
            now = original.rect(self.map, True)
            if now == last:
                break
            last = now
            time.sleep(0.5)
        self.t.main = self.hud
        # the page's HUD is as wide as the page, its map window the size of GBC's; DOSBox's
        # window (GBC's quick menu and journal viewer sit in it) the page for those
        r.hud_width = original.rect(self.hud, True)[2]
        x0, y0, x1, y1 = original.rect(self.fake.hwnd)
        r.dos_size = (x1 - x0, y1 - y0)
        r.map_size = original.rect(self.map, True)[3] if self.map else 0
        self.settle(1.5)

    def settle(self, minimum=0.8, limit=6.0):
        time.sleep(minimum)
        end = time.monotonic() + limit
        last = None
        while time.monotonic() < end:
            snap = self.t.capture(self.hud)
            key = snap.tobytes() if snap else b''
            if key == last:
                return
            last = key
            time.sleep(0.3)

    def map_window(self):
        """GBC's map window: it shows a while after the HUD, now and then later than start
        waits."""
        if not self.map or not original.user32.IsWindowVisible(self.map):
            self.map = self.t.find('TMap_Form', timeout=5) or self.map
        return self.map

    def view(self, name):
        if name == 'hud':
            return self.t.capture_texts(self.hud)
        if name == 'map':
            return self.t.capture_texts(self.map_window()) if self.map_window() else None
        if name == 'stats':
            h = self.t.find('TStatistics_Form', timeout=1.5)
            return self.t.capture_texts(h) if h else None
        raise KeyError(name)

    def title(self):
        return original.window_text(self.map_window()) if self.map_window() else ''

    def map_mouse(self, x, y, what='move', mods=()):
        """The mouse at pixel x, y of the map window."""
        self.t.mouse(self.map_window(), x, y, what, mods)
        time.sleep(0.4)

    def map_key(self, name, mods=()):
        """A key (a letter) pressed in the map window."""
        self.t.key(self.map_window(), ord(name.upper()), name.lower(), mods)
        time.sleep(0.4)

    def hud_size(self):
        return original.rect(self.hud, True)[2:]

    def hud_hover(self, slot=None):
        """The mouse over the HUD (GBC shows its menu): over a button's middle, or its top
        middle. GBC looks for the mouse in its timer, and for the button on mouse moves."""
        x, y = hud_point(*self.hud_size(), slot)
        self.t.mouse(self.hud, x, y)
        time.sleep(0.4)
        self.t.mouse(self.hud, x, y)
        time.sleep(0.4)

    def hud_click(self, slot):
        self.hud_hover(slot)
        x, y = hud_point(*self.hud_size(), slot)
        self.t.mouse(self.hud, x, y, 'left')
        time.sleep(0.6)

    def hud_leave(self):
        """The mouse away from the HUD (to the map's corner)."""
        self.map_mouse(1, 1)
        time.sleep(0.3)

    # ---- the editor ------------------------------------------------------------------
    def editor(self):
        """GBC's editor from the HUD menu (EDITOR); its controls by name."""
        self.hud_click(MENU['editor'])
        self.hud_leave()
        self.ed = self.t.find('TEditor_Form', timeout=10)
        if not self.ed:
            raise RuntimeError('GBC did not open its editor')
        time.sleep(1.0)
        named = self.t.form_controls(self.ed, EDITOR_CONTROLS)
        self.edg = {k: h for k, h in named.items() if k.endswith('_GroupBox')}
        self.edc = {k: h for k, h in named.items() if not k.endswith('_GroupBox')}

    def editor_values(self):
        """Each control's text (or entries, checks), and whether it is enabled."""
        return self.t.control_values(self.edc)

    def editor_close(self):
        """The editor's window closed (its title bar's X)."""
        original.user32.PostMessageW(self.ed, original.WM_CLOSE, 0, 0)
        for _ in range(30):
            if not original.user32.IsWindowVisible(self.ed):
                break
            time.sleep(0.1)
        time.sleep(0.5)

    def editor_view(self, name):
        """One of the editor's pictures (the form paints them)."""
        x, y, w, h = EDITOR_PAINT[name]
        img = self.t.capture(self.ed)
        return img.crop((x, y, x + w, y + h)) if img else None

    def editor_pick(self, name, i):
        """A list's or combo box's entry chosen as a click chooses it; a list view's row selected."""
        h = self.edc[name]
        if original.class_name(h) == 'TListView':
            self.t.listview_select(h, i)
        else:
            self.t.select(h, i)
        time.sleep(0.8)

    def editor_set(self, name, text):
        self.t.set_text(self.edc[name], str(text))
        time.sleep(0.1)

    def editor_check(self, name, on):
        h = self.edc[name]
        if (original.user32.SendMessageW(h, original.BM_GETCHECK, 0, 0) == 1) != on:
            self.t.click_button(h)
        time.sleep(0.4)

    def editor_click(self, name):
        self.t.click_button(self.edc[name])
        time.sleep(1.2)

    def editor_paint_click(self, name, x, y):
        """A click into one of the editor's pictures (the colour squares)."""
        px, py = EDITOR_PAINT[name][:2]
        g = self.edg['Icon_GroupBox']
        gx, gy = 528, 592
        self.t.mouse(g, px - gx + x, py - gy + y, 'left')
        time.sleep(0.6)

    # ---- the quick menu and the journal viewer -------------------------------------------
    def game_window(self):
        pass

    def quick(self):
        """GBC's quick menu: its hotkey's message to the main window, with the id GBC registered it
        under (at 437514)."""
        hk = struct.unpack('<I', self.t.read_memory(0x437514, 4))[0]
        original.user32.PostMessageW(self.main, 0x0312, hk, 0)
        time.sleep(0.8)

    def quick_values(self):
        h = self.t.find('TQuick_Form', timeout=0.5)
        lb = self.t.control('TListBox', h=h) if h else None
        if not lb:
            return None
        return {'items': self.t.list_items(lb), 'index': original.user32.SendMessageW(lb, original.LB_GETCURSEL, 0, 0)}

    def quick_run(self, i):
        """An entry double-clicked."""
        h = self.t.find('TQuick_Form', timeout=1)
        self.t.select(self.t.control('TListBox', h=h), i, double=True)
        time.sleep(1.2)

    def viewer(self):
        h = self.t.find('TViewer_Form', timeout=2)
        return self.t.capture_texts(h) if h else None

    def viewer_key(self, vk):
        h = self.t.find('TViewer_Form', timeout=1)
        if h:
            self.t.key(h, vk)
        time.sleep(0.6)

    # ---- the level up window -------------------------------------------------------------
    def leveler_values(self):
        """The level up window's name and level panels, the changes, the spells to pick from,
        whether Level up is enabled; None without the window."""
        h = self.t.find('TLeveler_Form', timeout=1.5)
        if not h:
            return None
        out = {'spells': []}
        for cls, hw, text, r in self.t.controls(h):
            p = wintypes.POINT(r[0], r[1])
            original.user32.ScreenToClient(h, original.ctypes.byref(p))
            if cls == 'TPanel':
                out['name' if p.y < 100 else 'level'] = text
            elif cls == 'TMemo':
                out['memo'] = text
            elif cls == 'TListBox':
                out['spells'] = self.t.list_items(hw)
            elif cls == 'TButton' and text.replace('&', '') == 'Level up':
                out['levelUp'] = bool(original.user32.IsWindowEnabled(hw))
        return out

    def leveler_pick(self, i):
        h = self.t.find('TLeveler_Form', timeout=1.5)
        if h:
            self.t.select(self.t.control('TListBox', h=h), i)
        time.sleep(0.5)

    def leveler_click(self, what):
        h = self.t.find('TLeveler_Form', timeout=1.5)
        b = self.t.control('TButton', h=h, text=what) if h else None
        if b:
            self.t.click_button(b)
        time.sleep(1.5)

    # ---- files GBC writes ----------------------------------------------------------------
    def files_since(self):
        """The time to tell the files written from now on by (save_map, backup)."""
        self.since = time.time() - 1

    def saved_map(self):
        """The newest PNG in GBC's Screenshots folder written since files_since: name, picture."""
        from PIL import Image
        d = self.run.tool / 'Screenshots'
        new = sorted((p for p in d.glob('*.png') if p.stat().st_mtime >= self.since), key=lambda p: p.stat().st_mtime) if d.exists() else []
        if not new:
            return None, None
        img = Image.open(new[-1]).convert('RGB')
        img.load()
        return new[-1].name, img

    def backup_files(self, wait=4.0):
        """The folders BACKUP SAVE made under SAVE STORAGE since files_since, with their files:
        [(folder, [(name, size, md5)])]."""
        end = time.monotonic() + wait
        while True:
            new = [p for p in self.run.game.rglob('*') if p.is_dir() and p.parent.name.upper() == 'SAVE STORAGE'
                   and p.stat().st_ctime >= self.since]
            if new or time.monotonic() > end:
                break
            time.sleep(0.3)
        time.sleep(0.5)   # the copies done
        return sorted((stamped(p.name), sorted((f.name.upper(), f.stat().st_size, hashlib.md5(f.read_bytes()).hexdigest())
                                               for f in p.iterdir() if f.is_file())) for p in new)

    def dialogs(self, wait=2.0):
        """What the dialogs shown since the last call said (message dialogs: their text;
        input boxes: their caption and prompt); answered with the given answers."""
        out = []
        own = {self.main, self.hud, self.map}
        end = time.monotonic() + (wait if self.pending else 0.2)
        while time.monotonic() < end:
            h = next((w for w in self.t.windows() if original.class_name(w) in ('TMessageForm', 'TForm') and w not in own), None)
            if not h:
                time.sleep(0.1)
                continue
            self.t.capture(h)   # painted (into the capture, which the log follows)
            time.sleep(0.2)
            want = '%08x' % h
            texts = [] if original.class_name(h) == 'TMessageForm' else [original.window_text(h)]
            for line in self.t.log():
                p = line.split(' ', 2)
                if len(p) == 3 and p[1] in ('text', 'drawtext'):
                    head, text = p[2].split('|', 1)
                    if head.split(' ')[3].lower().rjust(8, '0') == want and original.unescape(text) not in texts:
                        texts.append(original.unescape(text))
            out.append(' '.join(' '.join(texts).split()))
            ans = self.pending.pop(0) if self.pending else None
            controls = self.t.controls(h)
            buttons = [c for c in controls if c[0] == 'TButton']
            edit = next((c for c in controls if c[0] == 'TEdit'), None)
            if edit and ans not in (None, 'OK', 'Cancel'):
                self.t.set_text(edit[1], ans)
                time.sleep(0.2)
                ans = 'OK'
            pick = next((c for c in buttons if c[2].replace('&', '') == ans), buttons[0] if buttons else None)
            if pick:
                self.t.click_button(pick[1])
            for _ in range(30):
                if not original.user32.IsWindow(h) or not original.user32.IsWindowVisible(h):
                    break
                time.sleep(0.1)
            end = time.monotonic() + (wait if self.pending else 0.3)
        return out

    def finish(self):
        if hasattr(self, 't'):
            self.t.close()


def hud_point(w, h, slot=None):
    """The middle of GBC's HUD menu button (slot 1-8 the lower row, 9-16 the upper; 8 a row,
    (w - 54) / 8 wide, 20 high, 6 apart, the lower row 32 above the bottom), or the HUD's
    top middle."""
    if slot is None:
        return w // 2, 2
    bw = (w - 54 if w >= 54 else w - 47) >> 3
    x0 = int((w - bw * 8 - 54) / 2)
    col, row = (slot - 1) % 8, (slot - 1) // 8
    return x0 + 6 + (bw + 6) * col + bw // 2, h - 32 - 26 * row + 10


def hud_rect(w, h, slot):
    """GBC's HUD menu button's rectangle (left, top, right, bottom; exclusive)."""
    bw = (w - 54 if w >= 54 else w - 47) >> 3
    x, y = hud_point(w, h, slot)
    return x - bw // 2, y - 10, x - bw // 2 + bw + 1, y + 11


# the slots of GBC's HUD menu buttons
MENU = dict(journals=1, encamp=2, store=3, restore=4, race=5, races=6, level=7, wizard=8,
            map=9, explore=10, unexplore=11, editor=12, save_map=13, backup=14, settings=15, quit=16)
SETTINGS = dict(dock=1, decrease=2, increase=3, restore_map=4, hud_top=5, fix_drain=6, auto_ammo=7, reload_levels=8,
                icons=9, xp=10, effects=11, title_hack=12, dump=13, auto_id=14, fix_stats=15, edit_levels=16)

# GBC's editor's controls that are windows, by class and place in the form's client area (its form)
EDITOR_CONTROLS = {
    ('TGroupBox', 160, 8): 'Stats_GroupBox', ('TGroupBox', 528, 8): 'Spells_GroupBox', ('TGroupBox', 864, 8): 'Inventory_GroupBox',
    ('TComboBox', 224, 32): 'Race_ComboBox', ('TEdit', 416, 32): 'Experience_Edit', ('TEdit', 584, 32): 'C1_Edit',
    ('TEdit', 608, 32): 'C2_Edit', ('TEdit', 632, 32): 'C3_Edit', ('TEdit', 656, 32): 'C4_Edit',
    ('TEdit', 680, 32): 'C5_Edit', ('TEdit', 704, 32): 'C6_Edit', ('TEdit', 728, 32): 'C7_Edit',
    ('TListBox', 880, 32): 'Items_ListBox', ('TComboBox', 1088, 32): 'ItemName1_ComboBox', ('TComboBox', 224, 56): 'Class_ComboBox',
    ('TEdit', 584, 56): 'M1_Edit', ('TEdit', 608, 56): 'M2_Edit', ('TEdit', 632, 56): 'M3_Edit',
    ('TEdit', 656, 56): 'M4_Edit', ('TEdit', 680, 56): 'M5_Edit', ('TEdit', 704, 56): 'M6_Edit',
    ('TEdit', 728, 56): 'M7_Edit', ('TEdit', 752, 56): 'M8_Edit', ('TEdit', 776, 56): 'M9_Edit',
    ('TComboBox', 1088, 56): 'ItemName2_ComboBox', ('TEdit', 464, 64): 'NPC_Edit', ('TComboBox', 224, 80): 'Gender_ComboBox',
    ('TEdit', 584, 80): 'D1_Edit', ('TEdit', 608, 80): 'D2_Edit', ('TEdit', 632, 80): 'D3_Edit',
    ('TComboBox', 1088, 80): 'ItemName3_ComboBox', ('TEdit', 464, 88): 'Hostile_Edit', ('TEdit', 224, 104): 'Age_Edit',
    ('TEdit', 1088, 104): 'ItemUnidentified_Edit', ('TEdit', 584, 112): 'SpellsLeft1_Edit', ('TEdit', 608, 112): 'SpellsLeft2_Edit',
    ('TEdit', 632, 112): 'SpellsLeft3_Edit', ('TEdit', 656, 112): 'SpellsLeft4_Edit', ('TEdit', 680, 112): 'SpellsLeft5_Edit',
    ('TEdit', 704, 112): 'SpellsLeft6_Edit', ('TEdit', 728, 112): 'SpellsLeft7_Edit', ('TEdit', 752, 112): 'SpellsLeft8_Edit',
    ('TEdit', 776, 112): 'SpellsLeft9_Edit', ('TEdit', 464, 120): 'MagicResistance_Edit', ('TComboBox', 224, 128): 'Alignment_ComboBox',
    ('TEdit', 1088, 128): 'ItemType_Edit', ('TComboBox', 544, 144): 'Spells_ComboBox', ('TButton', 664, 144): 'LearnSpells_Button',
    ('TButton', 736, 144): 'ClearMemorized_Button', ('TButton', 784, 144): 'SpellDecrease_Button', ('TButton', 808, 144): 'SpellIncrease_Button',
    ('TComboBox', 224, 152): 'God_ComboBox', ('TEdit', 456, 152): 'Jewelry_Edit', ('TEdit', 1088, 152): 'ItemBonus_Edit',
    ('TPanel', 8, 168): 'AC_Panel', ('TPanel', 48, 168): 'THAC0_Panel', ('TPanel', 88, 168): 'Damage_Panel',
    ('TComboBox', 224, 176): 'Knight_ComboBox', ('TEdit', 456, 176): 'Gems_Edit', ('TListView', 544, 176): 'Spells_ListView',
    ('TEdit', 1088, 176): 'ItemSave_Edit', ('TComboBox', 224, 200): 'Robe_ComboBox', ('TEdit', 456, 200): 'Coins_Edit',
    ('TEdit', 1088, 200): 'ItemCursed_Edit', ('TPanel', 8, 216): 'Class1_Panel', ('TPanel', 112, 216): 'Level1_Panel',
    ('TEdit', 1088, 224): 'ItemAmount_Edit', ('TEdit', 224, 232): 'Ability1_Edit', ('TEdit', 352, 232): 'AC_Edit',
    ('TPanel', 8, 248): 'Class2_Panel', ('TPanel', 112, 248): 'Level2_Panel', ('TEdit', 1088, 248): 'ItemWeight_Edit',
    ('TEdit', 224, 256): 'Ability2_Edit', ('TEdit', 352, 256): 'THAC0_Edit', ('TEdit', 1088, 272): 'ItemValue_Edit',
    ('TPanel', 8, 280): 'Class3_Panel', ('TPanel', 112, 280): 'Level3_Panel', ('TEdit', 224, 280): 'Ability3_Edit',
    ('TEdit', 352, 280): 'Attacks1_Edit', ('TEdit', 1088, 296): 'ItemProperties1_Edit', ('TEdit', 224, 304): 'Ability4_Edit',
    ('TEdit', 352, 304): 'Attacks2_Edit', ('TListBox', 8, 320): 'Characters_Listbox', ('TEdit', 1088, 320): 'ItemProperties2_Edit',
    ('TEdit', 224, 328): 'Ability5_Edit', ('TEdit', 352, 328): 'Rolls1_Edit', ('TEdit', 408, 328): 'Dice1_Edit',
    ('TEdit', 464, 328): 'Modifier1_Edit', ('TButton', 880, 344): 'ApplyItemChange_Button', ('TEdit', 1088, 344): 'ItemProperties3_Edit',
    ('TEdit', 224, 352): 'Ability6_Edit', ('TEdit', 352, 352): 'Rolls2_Edit', ('TEdit', 408, 352): 'Dice2_Edit',
    ('TEdit', 464, 352): 'Modifier2_Edit', ('TEdit', 224, 376): 'Ability7_Edit', ('TEdit', 352, 376): 'Movement_Edit',
    ('TGroupBox', 864, 392): 'Effects_GroupBox', ('TEdit', 224, 408): 'CurrentHP_Edit', ('TEdit', 288, 408): 'MaximumHP_Edit',
    ('TListBox', 880, 416): 'Effects_ListBox', ('TComboBox', 224, 432): 'Status_ComboBox', ('TCheckBox', 336, 436): 'Enabled_CheckBox',
    ('TEdit', 224, 464): 'Save1_Edit', ('TEdit', 256, 464): 'Save2_Edit', ('TEdit', 288, 464): 'Save3_Edit',
    ('TEdit', 320, 464): 'Save4_Edit', ('TEdit', 352, 464): 'Save5_Edit', ('TEdit', 384, 464): 'Save6_Edit',
    ('TEdit', 416, 464): 'Save7_Edit', ('TEdit', 448, 464): 'Save8_Edit', ('TButton', 8, 488): 'Refresh_Button',
    ('TEdit', 224, 496): 'Thief1_Edit', ('TEdit', 256, 496): 'Thief2_Edit', ('TEdit', 288, 496): 'Thief3_Edit',
    ('TEdit', 320, 496): 'Thief4_Edit', ('TEdit', 352, 496): 'Thief5_Edit', ('TEdit', 384, 496): 'Thief6_Edit',
    ('TEdit', 416, 496): 'Thief7_Edit', ('TEdit', 448, 496): 'Thief8_Edit', ('TButton', 8, 520): 'Apply_Button',
    ('TCheckBox', 232, 528): 'FighterItems_CheckBox', ('TCheckBox', 304, 528): 'ClericItems_CheckBox', ('TCheckBox', 376, 528): 'MageItems_CheckBox',
    ('TCheckBox', 448, 528): 'ThiefItems_CheckBox', ('TCheckBox', 232, 548): 'PaladinItems_CheckBox', ('TCheckBox', 304, 548): 'KnightItems_CheckBox',
    ('TCheckBox', 376, 548): 'RangerItems_CheckBox', ('TButton', 8, 568): 'XPTables_Button', ('TCheckListBox', 176, 576): 'Flags1_CheckListBox',
    ('TCheckListBox', 336, 576): 'Flags2_CheckListBox', ('TGroupBox', 528, 592): 'Icon_GroupBox', ('TButton', 744, 610): 'ResetColors_Button',
    ('TButton', 8, 616): 'ConvertToPaladin_Button', ('TComboBox', 544, 616): 'Head_ComboBox', ('TCheckBox', 672, 618): 'Large_CheckBox',
    ('TComboBox', 880, 632): 'Effect_ComboBox', ('TComboBox', 544, 640): 'Body_ComboBox', ('TButton', 8, 648): 'ConvertToRanger_Button',
    ('TComboBox', 544, 664): 'Color_ComboBox', ('TEdit', 880, 664): 'Byte1_Edit', ('TEdit', 912, 664): 'Byte2_Edit',
    ('TEdit', 944, 664): 'Byte3_Edit', ('TEdit', 976, 664): 'Byte4_Edit', ('TEdit', 1008, 664): 'Byte5_Edit',
    ('TButton', 1072, 664): 'ApplyEffectChange_Button', ('TButton', 8, 680): 'ConvertToMonk_Button',
}
# the editor's pictures (TPaintBoxes: the form paints them), in its client area
EDITOR_PAINT = {'Icon_PaintBox': (16, 16, 120, 120), 'Colors_PaintBox': (672, 646, 160, 40)}


PAGE_SETUP = '''(() => {
  for (const k of Object.keys(localStorage)) localStorage.removeItem(k);
  localStorage.setItem('gbc.settings', JSON.stringify(%s));
  return new Promise(res => { const q = indexedDB.deleteDatabase('gbc'); q.onsuccess = q.onerror = q.onblocked = () => res(1); });
})()'''


class Page(Common):
    which = 'page'

    def start(self, fit=False):
        """fit: the map window at the page's size (GBC's default size, its DOSBox's height),
        the page as high as needs for that to be the original's; else that size set."""
        r = self.run
        b = self.b = r.browser
        # the original's HUD is as wide as DOSBox's window, the page's as the page
        w, size = getattr(r, 'hud_width', 640) or 640, getattr(r, 'map_size', 0) or 377
        b.viewport(w, 760)
        b.goto(f'http://127.0.0.1:{self.fake.port}/{self.fake.BLANK}')
        v = dict(icons=True, xpMeter=True, effects=True, mapMarks='notes', hud=True, mapSize=0 if fit else size,
                 autoId=False, fixDrain=False, fixStats=False, autoAmmo=False, cheat=False, debug=False, fruaDesign=r.design)
        b.js(PAGE_SETUP % json.dumps(v))
        b.dialogs.clear()
        b.goto(f'http://127.0.0.1:{self.fake.port}/gbc.html?gbcdata=gbc/&gamedata=game/')
        b.wait('Game.g >= 0 && Game.party.length > 0', 60)
        if fit:
            time.sleep(1.0)
            chrome = b.js("innerHeight - document.querySelector('#mapwrap').clientHeight")
            b.viewport(w, chrome + size)
        self.settle(1.5)

    def settle(self, minimum=0.8, limit=6.0):
        time.sleep(minimum)
        try:
            t0 = self.b.js('Game.ticks || 0')
            self.b.wait(f'(Game.ticks || 0) >= {t0 + 3}', limit)
        except (TimeoutError, RuntimeError):
            pass

    def view(self, name):
        if name == 'hud':
            img = self.b.canvas('#hud')
            # the settings buttons the page can't have (docking the map, the HUD on top,
            # DOSBox's title bar) are there, disabled
            if img and self.b.js('Hud.mode') == 2:
                img.info['ignore'] = [hud_rect(*img.size, k) for k in (SETTINGS['dock'], SETTINGS['hud_top'], SETTINGS['title_hack'])]
            return img
        if name == 'map':
            return self.b.canvas('#map')
        if name == 'stats':
            shown = self.b.js("(c => !!c && c.style.display !== 'none')(document.querySelector('#stats'))")
            return self.b.canvas('#stats') if shown else None
        raise KeyError(name)

    def title(self):
        return self.b.js("document.querySelector('#title').textContent")

    def map_mouse(self, x, y, what='move', mods=()):
        ox, oy = self.b.js("(r => [r.left, r.top])(document.querySelector('#map').getBoundingClientRect())")
        self.answer_next()
        self.b.mouse(ox + x, oy + y, what, mods)
        time.sleep(0.4)

    def map_key(self, name, mods=()):
        self.answer_next()
        self.b.key(name.lower(), f'Key{name.upper()}', ord(name.upper()), text=name.lower() if not mods else None, mods=mods)
        time.sleep(0.4)

    def hud_box(self):
        return self.b.js("(r => [r.left, r.top, r.width, r.height])(document.querySelector('#hud').getBoundingClientRect())")

    def hud_hover(self, slot=None):
        left, top, w, h = self.hud_box()
        x, y = hud_point(int(w), int(h), slot)
        for _ in range(2):
            self.b.mouse(left + x, top + y)
            time.sleep(0.4)

    def hud_click(self, slot):
        self.hud_hover(slot)
        left, top, w, h = self.hud_box()
        x, y = hud_point(int(w), int(h), slot)
        self.answer_next()
        self.b.mouse(left + x, top + y, 'left')
        time.sleep(0.6)

    def hud_leave(self):
        self.map_mouse(1, 1)
        time.sleep(0.3)

    # ---- the editor (its controls by GBC's names) --------------------------------------
    def editor(self):
        self.hud_click(MENU['editor'])
        self.hud_leave()
        self.b.wait('!!Editor.rec && !Editor.busy', 20)

    def editor_values(self):
        return self.b.js('Editor.values()')

    def editor_close(self):
        self.b.js("document.querySelector('#editor header button').click(); 1")
        time.sleep(0.5)

    def editor_view(self, name):
        return self.b.canvas(f'#ed_{name}')

    def editor_wait(self):
        time.sleep(0.3)
        self.b.wait('!Editor.busy', 20)

    def editor_pick(self, name, i):
        self.answer_next()
        self.b.js(f'Editor.pick({json.dumps(name)}, {int(i)})')
        self.editor_wait()

    def editor_set(self, name, text):
        self.b.js(f'Editor.set({json.dumps(name)}, {json.dumps(str(text))})')

    def editor_check(self, name, on):
        self.b.js(f'Editor.pick({json.dumps(name)}, {1 if on else 0})')
        self.editor_wait()

    def editor_click(self, name):
        self.answer_next()
        self.b.js(f'Editor.pick({json.dumps(name)})')
        self.editor_wait()

    def editor_paint_click(self, name, x, y):
        self.answer_next()
        self.b.js(f'Editor.colorClick({int(x)}, {int(y)})')
        self.editor_wait()

    # ---- the quick menu and the journal viewer (the page as large as DOSBox's window) ----
    def game_window(self):
        self.b.viewport(*self.run.dos_size)
        time.sleep(0.5)

    def quick(self):
        self.b.js('QuickMenu.open()')
        time.sleep(0.3)

    def quick_values(self):
        return self.b.js('QuickMenu.values()')

    def quick_run(self, i):
        self.answer_next()
        self.b.js(f'(QuickMenu.pick({int(i)}), QuickMenu.run({int(i)}))')
        time.sleep(0.6)

    def viewer(self):
        return self.b.canvas('#viewer') if self.b.js("!!document.querySelector('#viewer')") else None

    def viewer_key(self, vk):
        key = {0x1B: 'Escape', 0x0D: 'Enter', 0x20: ' '}[vk]
        self.b.js(f"document.querySelector('#viewer')?.dispatchEvent(new KeyboardEvent('keydown', {{key: {json.dumps(key)}}}))")
        time.sleep(0.3)

    # ---- the level up window -------------------------------------------------------------
    def leveler_values(self):
        return self.b.js('Leveler.values()')

    def leveler_pick(self, i):
        self.b.js(f'Leveler.pickSpell({int(i)})')

    def leveler_click(self, what):
        self.answer_next()
        self.b.js(f'Leveler.press({json.dumps(what)})')
        time.sleep(0.8)

    # ---- files the page gives (downloads) -------------------------------------------------
    def files_since(self):
        for p in self.b.downloads.iterdir():
            p.unlink()

    def saved_map(self):
        from PIL import Image
        for _ in range(30):
            new = [p for p in self.b.downloads.glob('*.png')]
            if new:
                img = Image.open(new[0]).convert('RGB')
                img.load()
                return new[0].name, img
            time.sleep(0.2)
        return None, None

    def backup_files(self, wait=4.0):
        """The backup zips downloaded since files_since (named as GBC's folders) with their files."""
        end = time.monotonic() + wait
        while True:
            got = list(self.b.downloads.glob('*.zip'))
            if got or time.monotonic() > end:
                break
            time.sleep(0.3)
        time.sleep(0.3)
        out = []
        for p in got:
            with zipfile.ZipFile(p) as z:
                out.append((stamped(p.stem), sorted((i.filename.upper(), i.file_size, hashlib.md5(z.read(i)).hexdigest())
                                                    for i in z.infolist())))
        return sorted(out)

    def answer_next(self):
        self.b.dialog_answers[:] = [False if a in ('No', 'Cancel') else True if a in ('Yes', 'OK') else a for a in self.pending]

    def dialogs(self, wait=2.0):
        time.sleep(0.3 if not self.pending else 0.6)
        out = [' '.join((m or '').split()) for t, m in self.b.dialogs]
        self.b.dialogs.clear()
        self.pending.clear()
        self.b.dialog_answers.clear()
        return out

    def finish(self):
        try:
            self.b.viewport(1400, 1000)
            # off the page: it would go on reading (and writing) the next session's game
            self.b.goto(f'http://127.0.0.1:{self.run.fake.port}/{self.run.fake.BLANK}')
        except Exception:
            pass


# ---- the sessions -------------------------------------------------------------------

def see(s, *views):
    for v in views or ('map', 'hud'):
        s.observe(v, s.view(v))


def search_map(s):
    """The game found (saved game A's party and place); then the party moves and turns.
    The area's name GBC shows over the map on arriving has gone by the first look."""
    r = s.run
    st = r.state()
    s.set(st)
    s.start()
    time.sleep(3.0)
    s.map_mouse(5, 5)          # in the border: GBC counts it to the first cell
    see(s)
    s.map_mouse(1, 1)          # left of the map: no cell
    for dx, dy in ((1, 0), (0, 1)):
        s.poke(r.state(x=(st.x + dx) & 15, y=(st.y + dy) & 15))
        s.settle()
    see(s, 'map')
    for d in (0, 2, 4, 6):
        s.poke(r.state(x=(st.x + 1) & 15, y=(st.y + 1) & 15, d=d))
        s.settle(0.5)
        see(s, 'map')


def stamped(name):
    """A name with a time in it (yyyy-mm-dd hh-nn) as that pattern."""
    return re.sub(r'\d{4}-\d\d-\d\d \d\d-\d\d', 'yyyy-mm-dd hh-nn', name)


def begin(s, **kw):
    """The game found on the state; the area's name over the map gone."""
    s.set(s.run.state(**kw))
    s.start()
    time.sleep(3.0)


def cell(s, x, y):
    """The middle of map cell x, y in GBC's map window (a 16 x 16 area)."""
    size = s.run.map_size
    cs = (size - 20) // 16
    o = (size - (cs * 16 + 20)) // 2
    return o + 10 + x * cs + cs // 2, o + 10 + y * cs + cs // 2


def explore_all(s):
    s.hud_click(MENU['explore'])
    s.hud_leave()
    s.settle()


def hud_menu(s):
    """GBC's menu in the HUD: there with the mouse over the HUD, the button under the mouse
    lit; the settings page, the journals page and a range of entries; gone with the mouse."""
    begin(s)
    s.hud_hover()
    see(s, 'hud')
    s.hud_hover(MENU['map'])
    see(s, 'hud')
    s.hud_click(MENU['settings'])
    see(s, 'hud')
    s.hud_leave()
    see(s, 'hud')
    s.hud_click(MENU['journals'])
    see(s, 'hud')
    s.hud_click(9)
    see(s, 'hud')
    s.hud_leave()
    see(s, 'hud')


def explore(s):
    """EXPLORE MAP and UNEXPLORE MAP from the HUD's menu."""
    begin(s)
    explore_all(s)
    see(s, 'map')
    s.hud_click(MENU['unexplore'])
    s.hud_leave()
    s.settle()
    see(s, 'map')


def map_marks(s):
    """Right clicks on the map: the events view, nothing, the notes view again, each said over
    the map for a while; the explored map's event numbers."""
    begin(s)
    explore_all(s)
    for _ in range(3):
        s.map_mouse(*cell(s, 4, 4), 'right')
        see(s, 'map')
        time.sleep(3.5)
        see(s, 'map')


def notes(s):
    """A note placed with a click (GBC's two input boxes), its description at the top while the
    mouse is on it; changed; removed with an empty ID."""
    begin(s)
    explore_all(s)
    s.answer('A1', 'The gate')
    s.map_mouse(*cell(s, 3, 4), 'left')
    s.observe('dialogs', s.dialogs())
    s.map_mouse(*cell(s, 3, 5))
    s.map_mouse(*cell(s, 3, 4))
    see(s, 'map')
    # (the mouse then off the map: how long GBC keeps framing a cell depends on its timer)
    s.answer('Cancel', 'Old gate')
    s.map_mouse(*cell(s, 3, 4), 'left')
    s.observe('dialogs', s.dialogs())
    s.map_mouse(1, 1)
    see(s, 'map')
    s.answer('')
    s.map_mouse(*cell(s, 3, 4), 'left')
    s.observe('dialogs', s.dialogs())
    s.map_mouse(1, 1)
    see(s, 'map')


def teleport(s):
    """Ctrl+click on the map: the cheat mode asked for once, the party put there."""
    begin(s)
    s.answer('cheat')
    s.map_mouse(*cell(s, 5, 6), 'left', ('ctrl',))
    s.observe('dialogs', s.dialogs())
    s.settle()
    s.observe('writes', s.memory_changes())
    s.map_mouse(*cell(s, 9, 2), 'left', ('ctrl',))
    s.observe('dialogs', s.dialogs())
    s.settle()
    s.observe('writes', s.memory_changes())


def event_number(s):
    """Ctrl+right click on the map: GBC's "Add event" box; decimal, $hex and nonsense."""
    begin(s)
    for text, (x, y) in (('7', (2, 3)), ('$1F', (3, 3)), ('xyz', (4, 3)), ('', (5, 3))):
        s.answer(text if text else 'OK')
        s.map_mouse(*cell(s, x, y), 'right', ('ctrl',))
        s.observe('dialogs', s.dialogs())
        s.settle()
    s.observe('writes', s.memory_changes())


def hud_settings(s):
    """The settings page's ICONS, XP-METER and EFFECTS turned off and on again."""
    begin(s)
    for k in ('icons', 'xp', 'effects'):
        s.hud_click(MENU['settings'])
        s.hud_click(SETTINGS[k])
        s.hud_leave()
        s.settle()
        see(s, 'hud')
        s.hud_click(MENU['settings'])
        s.hud_click(SETTINGS[k])
        s.hud_leave()
        s.settle()
        see(s, 'hud')


def menu_action(s, slot, page=None):
    """A button of the HUD's menu (on the settings page with page='settings'), the mouse away after."""
    if page == 'settings':
        s.hud_click(MENU['settings'])
    s.hud_click(slot)
    s.hud_leave()
    s.settle()


def memory_actions(s):
    """ENCAMP - FIX (hit points to the maximum, status okay, enabled), RACE HACK and RESTORE
    RACES, STORE SPELLS and RESTORE SPELLS, as the memory shows them."""
    r = s.run
    hurt = {0: {'hit_points_current': 1, 'status': 3}, 1: {'enabled': 0, 'hit_points_current': 0}}
    begin(s, fields=hurt)
    menu_action(s, MENU['encamp'])
    s.observe('encamp', s.memory_changes())
    s.poke(r.state())
    menu_action(s, MENU['race'])
    s.observe('race hack', s.memory_changes())
    s.poke(r.state(fields={k: {'race': 7} for k in range(len(r.party))}))
    menu_action(s, MENU['races'])
    s.observe('restore races', s.memory_changes())
    s.poke(r.state())
    menu_action(s, MENU['store'])
    s.poke(r.state(fields={k: {'memorized_spells': bytes(64)} for k in range(len(r.party))}))
    s.settle()
    menu_action(s, MENU['restore'])
    s.observe('restore spells', s.memory_changes())


def effects(s):
    """Effects on the HUD: their lines above the icons (good green, bad red, the others grey,
    durations in brackets, an unknown type as $xx), the HUD as much taller; then fewer."""
    begin(s, effects={0: [(1, 10), (2, 0)], 2: [(5, 300), (200, 1)], 3: [(3, 0)]})
    s.settle(2.0)
    see(s, 'hud')
    s.poke(s.run.state(effects={1: [(4, 2)]}))
    s.settle(2.0)
    see(s, 'hud')
    s.poke(s.run.state(effects={}))
    s.settle(2.0)
    see(s, 'hud')


COMBAT = dict(monsters=[('ORC', 5, 6), ('GOBLIN', 3, 4), ('HOBGOBLIN', 7, 7)],
              places=[(1, 10, 8, 1), (2, 11, 8, 1), (3, 12, 9, 1), (4, 10, 10, 1), (5, 11, 10, 1), (6, 12, 10, 1),
                      (7, 14, 6, 1), (8, 16, 7, 2), (9, 18, 9, 4)], selected=2)


def combat(s):
    """A combat: the battlefield in the map window (the party, the monsters in their sizes, the
    one acting), the HUD; then a monster loses hit points, a member dies (the HUD plays the
    death frames), the next one acts."""
    r = s.run
    begin(s, combat=COMBAT)
    s.settle(1.0)
    see(s)
    s.poke(r.state(combat=dict(COMBAT, monsters=[('ORC', 2, 6), ('GOBLIN', 3, 4), ('HOBGOBLIN', 7, 7)])))
    time.sleep(3.0)    # the box's red flash over
    see(s, 'map')
    s.poke(r.state(combat=dict(COMBAT, selected=3), fields={4: {'enabled': 0, 'hit_points_current': 0}}))
    time.sleep(3.0)    # the death frames over
    see(s)


def combatant_at(s, k):
    """The middle of combatant k's box in GBC's combat view (COMBAT's places)."""
    size = s.run.map_size
    xs, ys = [p[1] for p in COMBAT['places']], [p[2] for p in COMBAT['places']]
    n = max(max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    n = next(v for v in (20, 25, 30, 35, 40, 45, 50) if n < v or v == 50)
    ox = (max(xs) - min(xs)) // 2 + min(xs) - n // 2 + 1
    oy = (max(ys) - min(ys)) // 2 + min(ys) - n // 2 + 1
    cs = (size - 20) // n
    m = (size - cs * n - 20) // 2
    _, x, y, _ = next(p for p in COMBAT['places'] if p[0] == k)
    return m + (x - ox) * cs + 11 + cs // 2, m + (y - oy) * cs + 11 + cs // 2


def effect_types(r):
    """The game's effect numbers by name (GBC's Effects.txt: line n names effect n, '+ ' or '- '
    before the name)."""
    p = r.tool / 'Games' / r.info['dir'] / 'Effects.txt'
    lines = p.read_text('latin-1').splitlines() if p.exists() else []
    return {re.sub(r'^[+-] ?', '', t).strip(): k + 1 for k, t in enumerate(lines)}


def combat_held(s):
    """The combat view's red X over the held, asleep and helpless (by their effects): three
    members, the big monster."""
    t = effect_types(s.run)
    held, asleep, helpless = t.get('held'), t.get('asleep'), t.get('helpless')
    fx = {k: [(v, 10)] for k, v in ((0, held), (1, asleep), (2, helpless), (len(s.run.party) + 2, held)) if v}
    begin(s, combat=COMBAT, effects=fx)
    s.settle(1.0)
    see(s, 'map')


def stats(s):
    """GBC's statistics window over a combatant: a member, a monster; gone off the boxes."""
    begin(s, combat=COMBAT, effects={0: [(1, 10), (2, 0)]})
    s.settle(1.0)
    for k in (1, 7):
        s.map_mouse(*combatant_at(s, k))
        s.map_mouse(*combatant_at(s, k))
        time.sleep(0.5)
        see(s, 'stats')
    s.map_mouse(1, 1)
    time.sleep(0.5)
    s.observe('stats shown', s.view('stats') is not None)


def world(s):
    """Out of the areas (the mode byte): GBC's world map with its titles and the party's square;
    the party moves; T hides the titles; back into the area. Pools of Darkness has its world
    maps in its worlds only: the Realms."""
    r = s.run
    w = {'geo3': 0x19} if r.g == 4 else {}
    begin(s, mode=0, out=(10, 12), **w)
    s.settle(1.0)
    see(s, 'map')
    s.poke(r.state(mode=0, out=(30, 5), **w))
    s.settle(1.0)
    see(s, 'map')
    s.map_key('T')
    s.settle(1.0)
    see(s, 'map')
    s.map_key('T')
    s.poke(r.state())
    s.settle(1.0)
    time.sleep(3.0)
    s.map_mouse(1, 1)
    see(s, 'map')


def map_sizes(s):
    """The settings page's INCREASE MAP (24 pixels), DECREASE MAP (only above 400) and RESTORE
    MAP (DOSBox's height; here the page's)."""
    r = s.run
    s.set(r.state())
    s.start(fit=True)
    time.sleep(3.0)
    for k in ('decrease', 'increase', 'increase', 'decrease', 'restore_map'):
        s.hud_click(MENU['settings'])
        s.hud_click(SETTINGS[k])
        s.hud_leave()
        s.settle()
        time.sleep(3.0)    # the mouse cell forgotten
        see(s, 'map')


# ---- the editor ------------------------------------------------------------------------

# the controls whose entries are long and the same for everybody: compared once
LONG_LISTS = {'ItemName1_ComboBox', 'ItemName2_ComboBox', 'ItemName3_ComboBox', 'Effect_ComboBox', 'Race_ComboBox',
              'Class_ComboBox', 'Status_ComboBox', 'Head_ComboBox', 'Body_ComboBox'}
ITEM_CONTROLS = ['ItemName1_ComboBox', 'ItemName2_ComboBox', 'ItemName3_ComboBox'] + \
    [f'Item{n}_Edit' for n in ('Unidentified', 'Type', 'Bonus', 'Save', 'Cursed', 'Amount', 'Weight', 'Value',
                               'Properties1', 'Properties2', 'Properties3')]
EFFECT_CONTROLS = ['Effects_ListBox', 'Effect_ComboBox'] + [f'Byte{k}_Edit' for k in range(1, 6)]
SPELL_CONTROLS = ['Spells_ListView', 'Spells_ComboBox'] + [f'SpellsLeft{k}_Edit' for k in range(1, 10)]


def editor_look(s, tag, names=None, lists=False):
    """The editor's controls (or those named) as observations; the long lists with lists."""
    vals = s.editor_values()
    for k in sorted(names or vals):
        v = vals.get(k)
        if v and not lists and k in LONG_LISTS:
            v = {kk: vv for kk, vv in v.items() if kk != 'items'}
        s.observe(f'{tag} {k}', v)


def editor_view(s):
    """GBC's editor (EDITOR in the HUD menu) on every member: the fields, spell list, items
    and effects as its controls show them, and the member's picture."""
    begin(s, effects={0: [(1, 10), (2, 0)], 1: [(5, 300), (200, 1)]})
    s.editor()
    for i in range(len(s.run.party)):
        s.editor_pick('Characters_Listbox', i)
        editor_look(s, f'member {i}', lists=i == 0)
        s.observe(f'member {i} icon', s.editor_view('Icon_PaintBox'))


def editor_reopen(s):
    """The editor closed and opened again: its list of characters and the one it shows."""
    begin(s)
    s.editor()
    s.editor_pick('Characters_Listbox', 1)
    s.editor_close()
    s.editor()
    time.sleep(1.0)
    editor_look(s, 'again', ['Characters_Listbox', 'Age_Edit', 'Experience_Edit'], lists=True)


def editor_spells(s):
    """The editor's spell lists of every class for every member; then on the first member +
    and - on the first spells (learnt, memorized, forgotten), Learn all and Clear (Yes), and
    Apply changes (cheat mode asked for) as the memory takes it."""
    begin(s)
    s.editor()
    for i in range(len(s.run.party)):
        s.editor_pick('Characters_Listbox', i)
        for c in range(4):
            s.editor_pick('Spells_ComboBox', c)
            editor_look(s, f'member {i} class {c}', SPELL_CONTROLS)
    s.editor_pick('Characters_Listbox', 0)
    for c in (1, 0):
        s.editor_pick('Spells_ComboBox', c)
        for row, steps in ((0, '++-'), (1, '-+'), (2, '--')):
            s.editor_pick('Spells_ListView', row)
            for st in steps:
                s.editor_click('SpellIncrease_Button' if st == '+' else 'SpellDecrease_Button')
            editor_look(s, f'class {c} row {row}', SPELL_CONTROLS)
    s.editor_click('LearnSpells_Button')
    editor_look(s, 'learnt', SPELL_CONTROLS)
    s.answer('Yes')
    s.editor_click('ClearMemorized_Button')
    s.observe('clear', s.dialogs())
    editor_look(s, 'cleared', SPELL_CONTROLS)
    s.editor_pick('Spells_ListView', 0)
    s.editor_click('SpellIncrease_Button')
    s.answer('cheat')
    s.editor_click('Apply_Button')
    s.observe('apply', s.dialogs())
    s.observe('spells written', s.memory_changes())
    editor_look(s, 'after', SPELL_CONTROLS)


def editor_changes(s):
    """The editor's Apply changes (cheat mode asked for): numbers, lists and checks of the first
    member changed, a text that is no number among them, as the memory takes them; then again
    with nothing changed."""
    begin(s)
    s.editor()
    s.editor_pick('Characters_Listbox', 0)
    for name, v in (('Age_Edit', 33), ('Ability1_Edit', 17), ('Ability2_Edit', 'x'), ('Experience_Edit', 12345),
                    ('CurrentHP_Edit', 5), ('MaximumHP_Edit', 40), ('AC_Edit', 3), ('THAC0_Edit', 12), ('Save1_Edit', 9),
                    ('Save6_Edit', 4), ('Thief1_Edit', 50), ('Coins_Edit', 777), ('Gems_Edit', 3), ('Jewelry_Edit', '$1F'),
                    ('Movement_Edit', 9), ('Attacks1_Edit', 3), ('Rolls1_Edit', 2), ('Dice1_Edit', 6), ('Modifier1_Edit', -1),
                    ('Hostile_Edit', 0), ('NPC_Edit', 1), ('MagicResistance_Edit', 5), ('C1_Edit', 2), ('M1_Edit', 1)):
        s.editor_set(name, v)
    s.editor_pick('Alignment_ComboBox', 4)
    s.editor_pick('Gender_ComboBox', 1)
    s.editor_pick('Status_ComboBox', 3)
    s.editor_check('Enabled_CheckBox', False)
    s.editor_check('FighterItems_CheckBox', True)
    s.editor_check('MageItems_CheckBox', False)
    s.answer('cheat')
    s.editor_click('Apply_Button')
    s.observe('apply', s.dialogs())
    s.observe('written', s.memory_changes())
    editor_look(s, 'after')
    s.editor_click('Apply_Button')
    s.observe('apply again', s.dialogs())
    s.observe('written again', s.memory_changes())


def editor_items(s):
    """The editor's inventory: the first member with items, three of them in the controls;
    one changed with Apply item changes (cheat mode asked for) as the memory takes it."""
    begin(s)
    s.editor()
    items = []
    for i in range(len(s.run.party)):
        s.editor_pick('Characters_Listbox', i)
        items = s.editor_values()['Items_ListBox']['items']
        s.observe(f'member {i} items', items)
        if items:
            break
    if not items:
        return
    for k in range(min(3, len(items))):
        s.editor_pick('Items_ListBox', k)
        editor_look(s, f'item {k}', ITEM_CONTROLS)
    s.editor_pick('Items_ListBox', 0)
    s.editor_pick('ItemName1_ComboBox', 3)
    for name, v in (('ItemBonus_Edit', 2), ('ItemAmount_Edit', 5), ('ItemWeight_Edit', 300), ('ItemValue_Edit', 70000),
                    ('ItemCursed_Edit', 1), ('ItemProperties1_Edit', 7)):
        s.editor_set(name, v)
    s.answer('cheat')
    s.editor_click('ApplyItemChange_Button')
    s.observe('apply', s.dialogs())
    s.observe('item written', s.memory_changes())
    editor_look(s, 'after', ITEM_CONTROLS + ['Items_ListBox'])


def editor_effects(s):
    """The editor's effects: two members' lists, an effect in the controls, changed with Apply
    effect changes (cheat mode asked for) as the memory takes it."""
    begin(s, effects={0: [(1, 10), (2, 0)], 1: [(5, 300), (200, 1)]})
    s.editor()
    for i in (0, 1):
        s.editor_pick('Characters_Listbox', i)
        for k in range(2):
            s.editor_pick('Effects_ListBox', k)
            editor_look(s, f'member {i} effect {k}', EFFECT_CONTROLS)
    s.editor_pick('Effects_ListBox', 1)
    s.editor_pick('Effect_ComboBox', 7)
    s.editor_set('Byte1_Edit', 20)
    s.editor_set('Byte3_Edit', 'x')
    s.answer('cheat')
    s.editor_click('ApplyEffectChange_Button')
    s.observe('apply', s.dialogs())
    s.observe('effect written', s.memory_changes())
    editor_look(s, 'after', EFFECT_CONTROLS)


def editor_icon(s):
    """The editor's icon controls: head and body picked, Large, a colour square clicked, Reset
    colors - the picture and the squares each time; Apply changes as the memory takes it."""
    begin(s)
    s.editor()
    s.editor_pick('Characters_Listbox', 0)
    looks = ['Head_ComboBox', 'Body_ComboBox', 'Large_CheckBox', 'Color_ComboBox']

    def look(tag):
        editor_look(s, tag, looks)
        s.observe(f'{tag} icon', s.editor_view('Icon_PaintBox'))
        s.observe(f'{tag} colours', s.editor_view('Colors_PaintBox'))
    look('start')
    if not s.editor_values()['Head_ComboBox']['enabled']:
        s.editor_pick('Body_ComboBox', 3)
        look('icon 3')
    else:
        s.editor_pick('Head_ComboBox', 2)
        s.editor_pick('Body_ComboBox', 5)
        look('head 2 body 5')
        s.editor_check('Large_CheckBox', True)
        look('large')
        s.editor_pick('Color_ComboBox', 1)
        s.editor_paint_click('Colors_PaintBox', 65, 25)
        look('colour')
        s.editor_click('ResetColors_Button')
        look('reset')
        s.editor_paint_click('Colors_PaintBox', 5, 5)
    s.answer('cheat')
    s.editor_click('Apply_Button')
    s.observe('apply', s.dialogs())
    s.observe('icon written', s.memory_changes())


def editor_convert(s):
    """The editor's conversions (Pool of Radiance): a member not a level 1 fighter (GBC says
    so), one made a level 1 fighter converted to a paladin (Yes), as the memory takes it."""
    r = s.run
    cls = VALUES.get(str(r.g), {}).get('cls', [])
    levels = {name: 0 for name in GBC_NAMES[0x43:0x4c]}    # GBC's fields 44-4C: the levels
    begin(s, fields={0: dict(levels, **{'class': cls.index('fighter') if 'fighter' in cls else 2, 'level_fighter': 1})})
    s.editor()
    editor_look(s, 'buttons', ['ConvertToPaladin_Button', 'ConvertToRanger_Button', 'ConvertToMonk_Button'])
    if not s.editor_values()['ConvertToPaladin_Button']['enabled']:
        return
    s.editor_pick('Characters_Listbox', 1)
    s.answer('Yes', 'OK')
    s.editor_click('ConvertToRanger_Button')
    s.observe('not a fighter', s.dialogs())
    s.editor_pick('Characters_Listbox', 0)
    s.answer('Yes')
    s.editor_click('ConvertToPaladin_Button')
    s.observe('converted', s.dialogs())
    s.observe('paladin written', s.memory_changes())
    editor_look(s, 'after', ['Class_ComboBox', 'Class1_Panel', 'Level1_Panel', 'Save1_Edit', 'PaladinItems_CheckBox'])


def quick_menu(s):
    """GBC's quick menu (its hotkey): the entries, the first picked; ENCAMP - FIX from it (as the
    memory takes it); JOURNAL ENTRY (the number asked for, the entry in the journal viewer,
    which Escape closes); CLOSE. Then the HUD's journals page: a range, an entry in the viewer,
    closed by the next click in the HUD."""
    begin(s, fields={0: {'hit_points_current': 1, 'status': 3}})
    s.game_window()
    s.quick()
    s.observe('menu', s.quick_values())
    s.quick_run(2)
    s.observe('after encamp', s.quick_values())
    s.observe('encamp', s.memory_changes())
    s.quick()
    s.answer('1')
    s.quick_run(7)
    s.observe('journal asked', s.dialogs())
    s.observe('viewer', s.viewer())
    s.viewer_key(0x1B)
    s.observe('viewer closed', s.viewer() is None)
    s.quick()
    s.quick_run(0)
    s.observe('closed', s.quick_values())
    s.hud_click(MENU['journals'])
    s.hud_click(9)
    s.hud_click(10)
    s.hud_leave()
    s.observe('journal 2', s.viewer())
    s.hud_hover()
    s.hud_click(MENU['journals'])
    s.hud_leave()
    s.observe('viewer after a HUD click', s.viewer() is None)


def level_up(s):
    """GBC's LEVEL UP (HUD menu) with the first two members given plenty of experience: the level
    up window (name, class and level, the changes, the spells to pick from); Level up (the first
    spell picked where there are some) as the memory takes it; the next member; Skip; Exit."""
    begin(s, fields={0: {'experience': 3000000}, 1: {'experience': 3000000}})
    s.hud_click(MENU['level'])
    s.hud_leave()
    v = s.leveler_values()
    s.observe('first', v)
    if not v:
        return
    if v['spells']:
        s.leveler_pick(0)
        s.observe('picked', s.leveler_values())
    s.answer('Yes')
    s.leveler_click('Level up')
    s.observe('dialogs', s.dialogs())
    s.observe('written', s.memory_changes())
    s.observe('next', s.leveler_values())
    s.leveler_click('Skip')
    s.observe('after skip', s.leveler_values())
    s.leveler_click('Exit')
    s.observe('closed', s.leveler_values())


def auto_items(s):
    """The settings page's AUTO ID (the first member's unidentified first item identified once
    the number of items changes) and AUTO-AMMO (its second item made arrows, 5 of them, topped
    up), as the memory takes them."""
    r = s.run
    if r.g not in AMMO:
        return
    unid = {0: {0: {'unid': 1}}}
    begin(s, item_fields=unid)
    s.hud_click(MENU['settings'])
    s.hud_click(SETTINGS['auto_id'])
    s.hud_leave()
    s.settle(2.0)
    s.observe('auto id on, no new items', s.memory_changes())
    s.poke(r.state(item_fields=unid, extra_items={0: 1}))
    s.settle(3.0)
    s.observe('auto id', s.memory_changes())
    s.hud_click(MENU['settings'])
    s.hud_click(SETTINGS['auto_id'])
    s.hud_click(SETTINGS['auto_ammo'])
    s.hud_leave()
    s.poke(r.state(item_fields={0: {1: {'base': AMMO[r.g][0], 'amount': 5, 'bonus': 0}}}))
    s.settle(4.0)
    s.observe('auto ammo', s.memory_changes())


def save_map(s):
    """SAVE MAP (HUD menu) with the area explored: the map as a PNG named after the game and the
    area (GBC's in its Screenshots folder, the page's a download)."""
    begin(s)
    explore_all(s)
    time.sleep(3.0)    # the mouse cell forgotten
    s.files_since()
    s.answer('OK')
    s.hud_click(MENU['save_map'])
    s.hud_leave()
    s.dialogs()
    name, img = s.saved_map()
    s.observe('file', name)
    s.observe('map', img)


def backup(s):
    """BACKUP SAVE (HUD menu): the description asked for (the newest saved game's slot in the
    caption); that slot's files copied into a folder of SAVE STORAGE named by the time and the
    description without the characters a file name can't have and double spaces (the page:
    a zip of that name)."""
    begin(s)
    s.files_since()
    s.answer('my: backup  one?', 'OK')
    s.hud_click(MENU['backup'])
    s.hud_leave()
    # GBC's last message has the folder's path, the page's the zip's name: both as the name
    said = [re.sub(r'to folder: .*\\SAVE STORAGE\\(.*)\\$', r'to: \1', re.sub(r'to: (.*)\.zip$', r'to: \1', t)) for t in s.dialogs()]
    s.observe('asked', [stamped(t) for t in said])
    s.observe('files', s.backup_files())


SESSIONS = {
    'search_map': search_map,
    'combat': combat,
    'stats': stats,
    'world': world,
    'map_sizes': map_sizes,
    'memory_actions': memory_actions,
    'effects': effects,
    'hud_menu': hud_menu,
    'explore': explore,
    'map_marks': map_marks,
    'notes': notes,
    'teleport': teleport,
    'event_number': event_number,
    'hud_settings': hud_settings,
    'editor_view': editor_view,
    'editor_reopen': editor_reopen,
    'editor_spells': editor_spells,
    'editor_changes': editor_changes,
    'editor_items': editor_items,
    'editor_effects': editor_effects,
    'editor_icon': editor_icon,
    'editor_convert': editor_convert,
    'quick_menu': quick_menu,
    'level_up': level_up,
    'save_map': save_map,
    'backup': backup,
    'combat_held': combat_held,
    'auto_items': auto_items,
}

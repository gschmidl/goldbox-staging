"""Ultimapper 5 (Release 4) against ultimapper5.html.

The game's memory is built from the Ultima V files (DATA.OVL at the data
segment, the saved game at DS:55B6, the view at DS:AB12, the map buffer at
DS:6618, the combat map and combatants at DS:AD24 / DS:BA24), as the game has
them while it runs. The original's copy gets a Tiles.bmp drawn from the
game's own TILES.16, as the page draws them (the original ships a recoloured
set), so the pictures can be compared pixel for pixel; the dungeon party
arrow (the original's bitmaps, the page's own drawing) is left out."""
import hashlib
import io
import math
import os
import re
import shutil
import struct
import time
import zipfile
from pathlib import Path

from PIL import Image

import harness
import original

DS = 0x11580
SAVE, VIEW, MAPBUF, CMAP, CUNITS = 0x55B6, 0xAB12, 0x6618, 0xAD24, 0xBA24
EGA = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170), (170, 85, 0),
       (170, 170, 170), (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255), (255, 85, 85),
       (255, 85, 255), (255, 255, 85), (255, 255, 255)]
# small-map files: locations, floors each, locations with a basement (as the page's SMALL_FILES)
SMALL_FILES = [
    ('TOWNE.DAT', [1, 2, 3, 4, 5, 6, 7, 8], [2, 2, 2, 2, 2, 2, 2, 2], [4]),
    ('DWELLING.DAT', [9, 10, 11, 12, 13, 14, 15, 16], [3, 3, 3, 3, 1, 1, 1, 1], []),
    ('CASTLE.DAT', [17, 18, 19, 20, 21, 22, 23, 24], [5, 5, 1, 1, 1, 1, 1, 1], [17, 18]),
    ('KEEP.DAT', [25, 26, 27, 28, 29, 30, 31, 32], [2, 2, 1, 1, 1, 3, 3, 3], [32]),
]
SMALL = {}
for _file, _locs, _floors, _base in SMALL_FILES:
    _first = 0
    for _loc, _n in zip(_locs, _floors):
        SMALL[_loc] = (_file, _first, _n, -1 if _loc in _base else 0)
        _first += _n
BDA_KEYS = {0x01: 'Esc', 0x1C: 'Enter', 0x48: 'Up', 0x50: 'Down', 0x4B: 'Left', 0x4D: 'Right', 0x1E: 'A', 0x39: 'Space'}
VK_KEYS = {0x1B: 'Esc', 0x0D: 'Enter', 0x26: 'Up', 0x28: 'Down', 0x25: 'Left', 0x27: 'Right', 0x41: 'A', 0x20: 'Space'}
# the list window's keys: virtual key codes, and the page's key and code for each
LIST_KEYS = {'up': 0x26, 'down': 0x28, 'home': 0x24, 'end': 0x23, 'pgdn': 0x22, 'pgup': 0x21, 'enter': 0x0D,
             'tab': 0x09, 'r': 0x52, 'esc': 0x1B, 'num8': 0x68, 'num2': 0x62}
PAGE_LIST_KEYS = {'up': ('ArrowUp', 'ArrowUp'), 'down': ('ArrowDown', 'ArrowDown'), 'home': ('Home', 'Home'),
                  'end': ('End', 'End'), 'pgdn': ('PageDown', 'PageDown'), 'pgup': ('PageUp', 'PageUp'),
                  'enter': ('Enter', 'Enter'), 'tab': ('Tab', 'Tab'), 'r': ('r', 'KeyR'), 'esc': ('Escape', 'Escape'),
                  'num8': ('8', 'Numpad8'), 'num2': ('2', 'Numpad2')}


def lzw(src):
    """Ultima V's LZW (the page's lzw())."""
    size = struct.unpack_from('<I', src)[0]
    out = bytearray()
    bits = int.from_bytes(src, 'little')
    nbits = len(src) * 8
    bit, width, nxt, prev = 32, 9, 0x102, None
    d = {}
    while len(out) < size:
        if bit + width > nbits:
            break
        c = (bits >> bit) & ((1 << width) - 1)
        bit += width
        if c == 0x101:
            break
        if c == 0x100:
            width, nxt, d, prev = 9, 0x102, {}, None
            continue
        if c < 0x100:
            s = bytes([c])
        elif c in d:
            s = d[c]
        elif c == nxt and prev is not None:
            s = prev + prev[:1]
        else:
            raise ValueError(f'bad LZW code {c}')
        out += s
        if prev is not None and nxt < 4096:
            d[nxt] = prev + s[:1]
            nxt += 1
            if nxt >= (1 << width) and width < 12:
                width += 1
        prev = s
    return bytes(out[:size])


def tiles_image(game_dir):
    """The 512 tiles of TILES.16 in EGA colours, 32 a row (the page's atlas)."""
    raw = lzw(find_file(game_dir, 'TILES.16').read_bytes())
    img = Image.new('RGB', (512, 256))
    px = img.load()
    for t in range(512):
        tx, ty = (t % 32) * 16, (t >> 5) * 16
        for y in range(16):
            for x in range(16):
                b = raw[t * 128 + y * 8 + (x >> 1)]
                px[tx + x, ty + y] = EGA[b & 15 if x & 1 else b >> 4]
    return img


def find_file(folder, name):
    for f in Path(folder).iterdir():
        if f.name.lower() == name.lower():
            return f
    return None


class Files:
    """The Ultima V files the states are built from."""

    def __init__(self, game_dir):
        self.dir = Path(game_dir)
        rd = lambda n: find_file(self.dir, n).read_bytes()
        self.ovl = rd('DATA.OVL')
        self.init = rd('INIT.GAM') if find_file(self.dir, 'INIT.GAM') else rd('SAVED.GAM')
        self.small = {n: rd(n) for n in ('TOWNE.DAT', 'DWELLING.DAT', 'CASTLE.DAT', 'KEEP.DAT')}
        self.dungeon = rd('DUNGEON.DAT')
        self.world = self._large(rd('BRIT.DAT'), False)
        self.under = self._large(rd('UNDER.DAT'), True)

    def _large(self, src, underworld):
        m = bytearray(65536)
        serial = 0
        for ch in range(256):
            water = not underworld and self.ovl[0x3886 + ch] == 0xFF
            cx, cy = (ch & 15) * 16, (ch >> 4) * 16
            for y in range(16):
                for x in range(16):
                    if water:
                        m[(cy + y) * 256 + cx + x] = 1
                    else:
                        m[(cy + y) * 256 + cx + x] = src[serial]
                        serial += 1
        return bytes(m)

    def floor(self, loc, z):
        f, first, n, low = SMALL[loc]
        i = first + (z - low)
        return self.small[f][i * 1024:(i + 1) * 1024]

    def loc_xy(self, loc):
        return self.ovl[0x1E9A + loc - 1], self.ovl[0x1EC2 + loc - 1]


def chunk_origin(v):
    return max(0, min(0xE0, int((v - 5) / 16) * 16))


# A party: name, class letter, status letter, STR DEX INT, MP, HP, max HP, XP, level, equipment (6 slots)
PARTY = [
    ('Avatar', 'A', 'G', 20, 22, 18, 9, 70, 90, 350, 3, [0xFF, 0x0D, 0x1E, 0x05, 0xFF, 0xFF]),
    ('Shamino', 'F', 'G', 20, 22, 16, 0, 5, 60, 620, 2, [0x00, 0x0B, 0x17, 0x04, 0xFF, 0xFF]),
    ('Iolo', 'B', 'G', 19, 21, 17, 8, 90, 90, 790, 3, [0x00, 0x0A, 0x14, 0x17, 0xFF, 0xFF]),
    ('Mariah', 'M', 'G', 12, 18, 24, 20, 41, 60, 280, 2, [0xFF, 0x09, 0x10, 0xFF, 0x2B, 0xFF]),
    ('Geoffrey', 'F', 'G', 22, 16, 12, 0, 99, 120, 1650, 4, [0x02, 0x0E, 0x1F, 0x05, 0xFF, 0x2D]),
    ('Jaana', 'D', 'G', 14, 17, 21, 15, 30, 70, 400, 3, [0x01, 0x0C, 0x18, 0xFF, 0x2C, 0xFF]),
]


class State:
    """One moment of the game in memory."""

    def __init__(self, files, members=3):
        self.f = files
        self.save = bytearray(files.init[:4192].ljust(4192, b'\0'))
        self.view = bytearray(352)
        self.mapbuf = bytearray(1024)
        self.cmap = bytearray(352)
        self.cunits = bytearray(256)
        self.talk = b''
        for i in range(32):
            self.save[0x6B4 + i * 8:0x6B4 + i * 8 + 8] = bytes(8)
        self.party(members)
        self.save[0x2D9], self.save[0x2DA], self.save[0x2DB] = 14, 14, 7
        self.save[0x206], self.save[0x207], self.save[0x208], self.save[0x20B] = 3, 2, 5, 1
        self.save[0x2AA:0x2B2] = bytes([4, 0, 3, 2, 1, 0, 6, 1])
        self.save[0x24A + 4] = 2

    def member(self, k, name, cls, status, st, dx, it, mp, hp, maxhp, xp, level, eq):
        o = 2 + k * 32
        r = bytearray(32)
        r[0:len(name)] = name.encode()
        r[9] = 0x0B
        r[0x0A], r[0x0B] = ord(cls), ord(status)
        r[0x0C], r[0x0D], r[0x0E], r[0x0F] = st, dx, it, mp
        struct.pack_into('<HHH', r, 0x10, hp, maxhp, xp)
        r[0x16] = level
        r[0x19:0x1F] = bytes(eq)
        r[0x1F] = 0
        self.save[o:o + 32] = r
        return self

    def party(self, n, members=None):
        for k in range(16):
            self.save[2 + k * 32 + 0x1F] = 0xFF
        for k, m in enumerate((members or PARTY)[:n]):
            self.member(k, *m)
        self.save[0x2B5] = n
        return self

    def set(self, k, **fields):
        """Changes fields of party member k: status, hp, maxhp, xp, level, mp, st, dx, it, eq, name, cls."""
        o = 2 + k * 32
        for f, v in fields.items():
            if f in ('hp', 'maxhp', 'xp'):
                struct.pack_into('<H', self.save, o + {'hp': 0x10, 'maxhp': 0x12, 'xp': 0x14}[f], v)
            elif f == 'eq':
                self.save[o + 0x19:o + 0x1F] = bytes(v)
            elif f == 'name':
                self.save[o:o + 9] = v.encode().ljust(9, b'\0')
            elif f in ('status', 'cls'):
                self.save[o + {'status': 0x0B, 'cls': 0x0A}[f]] = ord(v)
            else:
                self.save[o + {'level': 0x16, 'mp': 0x0F, 'st': 0x0C, 'dx': 0x0D, 'it': 0x0E, 'party': 0x1F}[f]] = v
        return self

    def unit(self, i, tile, x, y, z=0, tile2=None):
        o = 0x6B4 + i * 8
        self.save[o:o + 5] = bytes([tile, tile if tile2 is None else tile2, x, y, z & 0xFF])
        return self

    def npc(self, k, unit, dialogue):
        o = 0x9B8 + k * 16
        self.save[o + 0xC], self.save[o + 0xA] = unit, dialogue
        return self

    def where(self, loc, z, x, y):
        s = self.save
        s[0x2ED], s[0x2EF], s[0x2F0], s[0x2F1] = loc, z & 0xFF, x, y
        return self

    def world(self, x, y, under=False):
        """On the large map; the game's 2x2 chunks in the map buffer."""
        self.where(0, -1 if under else 0, x, y)
        m = self.f.under if under else self.f.world
        ox, oy = chunk_origin(x), chunk_origin(y)
        self.save[0x2F5], self.save[0x2F6] = ox, oy
        k = 0
        for bx, by in ((ox, oy), (ox + 16, oy), (ox, oy + 16), (ox + 16, oy + 16)):
            for yy in range(by, by + 16):
                for xx in range(bx, bx + 16):
                    self.mapbuf[k] = m[(yy % 256) * 256 + xx % 256]
                    k += 1
        for r in range(11):
            for c in range(11):
                self.view[r * 32 + c] = m[((y - 5 + r) % 256) * 256 + (x - 5 + c) % 256]
        self.unit(0, 0x1C, x, y, 0)
        return self

    def town(self, loc, z, x, y, view=True):
        """In a small map: the floor in the map buffer, the view around the
        party (FF outside the map)."""
        self.where(loc, z, x, y)
        self.mapbuf[:] = self.f.floor(loc, z)
        for r in range(11):
            for c in range(11):
                mx, my = x - 5 + c, y - 5 + r
                inside = 0 <= mx < 32 and 0 <= my < 32
                self.view[r * 32 + c] = self.mapbuf[my * 32 + mx] if inside and view else 0xFF
        self.unit(0, 0x1C, x, y, z)
        return self

    def dungeon(self, loc, z, x, y, facing=0):
        self.where(loc, z, x, y)
        o = (loc - 33) * 8 * 64
        self.save[0x3B4:0x3B4 + 512] = self.f.dungeon[o:o + 512]
        self.save[0x105D] = facing
        self.unit(0, 0x1C, x, y, z)
        return self

    def combat(self, grid=None, units=(), active=0, aim=None, over=False):
        """A fight: the 11x11 map (a function of x, y giving the tile), the
        party on the left, units = (tile, hp, flags, x, y) of the others; as in the game,
        the save's unit table has each combatant's place too (the original's quickfight
        finds the member whose turn it is there)."""
        self.where(0xFF, 0, 0, 0)
        self.save[0x2F8] = active
        for r in range(11):
            for c in range(11):
                self.cmap[r * 32 + c] = grid(c, r) if grid else (4 if (r + c) % 7 else 0x4C)
        n = self.save[0x2B5]
        for i in range(n):
            x, y = 3 + (i % 3) * 2, 9 - i // 3
            self.cunits[i * 8:i * 8 + 8] = bytes([0, 1, 0x80, i, 0, 0, x, y])
            self.save[0x6B4 + i * 8 + 2:0x6B4 + i * 8 + 4] = bytes([x, y])
        for k, (tile, hp, fl, x, y) in enumerate(units):
            i = 6 + k
            self.cunits[i * 8:i * 8 + 8] = bytes([hp, 1, fl, tile, 0, 0, x, y])
            self.save[0x6B4 + i * 8 + 2:0x6B4 + i * 8 + 4] = bytes([x, y])
        if aim:
            self.save[0x2F2], self.save[0x2F3], self.save[0x2F4] = 1, aim[0], aim[1]
        if over:
            self.unit(0, 0x6C, 5, 6, 0)
        return self

    def image(self, size=1 << 20):
        mem = bytearray(size)
        mem[DS:DS + len(self.f.ovl)] = self.f.ovl
        mem[DS + SAVE:DS + SAVE + 4192] = self.save
        mem[DS + VIEW:DS + VIEW + 352] = self.view
        mem[DS + MAPBUF:DS + MAPBUF + 1024] = self.mapbuf
        mem[DS + CMAP:DS + CMAP + 352] = self.cmap
        mem[DS + CUNITS:DS + CUNITS + 256] = self.cunits
        mem[DS + TALK:DS + TALK + len(self.talk)] = self.talk
        mem[0x41A:0x41E] = bytes([0x1E, 0, 0x1E, 0])   # the BIOS keyboard buffer, empty
        return bytes(mem)


# the original's settings (Data\Settings.txt) and the page's names for them
SETTINGS = {
    'world_explored': ('worldExplored', 1), 'underworld_explored': ('underworldExplored', 0),
    'towns_explored': ('townsExplored', 1), 'dungeons_explored': ('dungeonsExplored', 0),
    'peer_explore': ('peerExplore', 1), 'world_titles': ('worldTitles', 1),
    'underworld_titles': ('underworldTitles', 0), 'npc_names': ('npcNames', 1),
    'auto_level_up': ('autoLevelUp', 0), 'quickfight_interval': ('qfInterval', 400),
    'quickfight_insta_aim': ('qfAim', 1), 'debug_mode': ('debug', 0), 'debug_log': ('debugLog', 0),
}
TALK = 0xB22E   # DS: the talk buffer (the NPC's script while talking)


def log_lines(text):
    """The log's lines (a memo's text ends with its last line's CRLF), each one's time as hh:nn:ss."""
    lines = text.replace('\r\n', '\n').split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return [re.sub(r'^\d\d:\d\d:\d\d(:  )', r'hh:nn:ss\1', l) for l in lines]


def files_digest(items):
    """[(name, size, md5)] of (name, bytes) items, by name."""
    return sorted([n, len(b), hashlib.md5(b).hexdigest()] for n, b in items)


class Run:
    """What the sessions of one test run share."""

    def __init__(self, work, tool_dir, game_dir, fake, browser, out):
        self.work = Path(work)
        self.out = Path(out)
        self.fake = fake
        self.browser = browser
        self.game = self.work / 'ultima5'
        if self.game.exists():
            shutil.rmtree(self.game)
        self.game.mkdir(parents=True)
        for f in Path(game_dir).iterdir():
            if f.is_file():
                if f.suffix.lower() == '.pdf':
                    (self.game / f.name).write_bytes(b'%PDF-1.0\n')
                elif f.stat().st_size < 4 << 20:
                    shutil.copyfile(f, self.game / f.name)
        self.saved_gam = find_file(self.game, 'SAVED.GAM') or self.game / 'SAVED.GAM'
        self.files = Files(self.game)
        self.tool = self.work / 'Ultimapper5'
        self.patch_log = original.prepare_tool(tool_dir, self.tool, harness.SANDBOX_DLL)
        tiles_image(self.game).save(self.tool / 'Data' / 'Tiles.bmp')
        fake.routes.update({'': str(harness.REPO / 'web'), 'game/': str(self.game)})
        self.hud_w = fake.rect[2]   # the original's HUD is as wide as the DOSBox window

    def state(self, **kw):
        return State(self.files, **kw)


class Common(harness.Side):
    map_size = 512

    def __init__(self, run):
        super().__init__(run, run.fake)
        self.settings = {k: v[1] for k, v in SETTINGS.items()}
        self.base = None
        self.pending = []

    def answer(self, *answers):
        """What the next dialogs are answered with (a text for an input box, OK, Cancel)."""
        self.pending += answers

    def consume_keys(self, seconds):
        """As the game would: the BIOS keyboard buffer's keys taken as they come, for a while."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            b = self.fake.get(0x41A, 4)
            if b[0:2] != b[2:4]:
                self.fake.put(0x41A, b[2:4])
            time.sleep(0.05)

    def set(self, st, saved=True):
        """The game's state in memory (and its saved game on disk)."""
        img = st.image()
        self.fake.reset(img)
        self.base = img
        if saved:
            self.run.saved_gam.write_bytes(bytes(st.save))
        self.cur = st

    def poke(self, st):
        """Changes the game's state while the tool runs (no saved game)."""
        img = st.image()
        self.fake.put(0, img)
        self.base = img
        self.cur = st

    def memory_changes(self, ignore_bios=True):
        """[(offset, old, new)] of the bytes changed since the last set()."""
        mem = self.fake.get(0, len(self.base))
        out = []
        for i, (a, b) in enumerate(zip(self.base, mem)):
            if a == b or (ignore_bios and 0x41A <= i < 0x43E):
                continue
            where = f'save+{i - DS - SAVE:X}' if DS + SAVE <= i < DS + SAVE + 4192 else f'DS+{i - DS:X}' \
                if DS <= i < DS + 0x10000 else f'{i:X}'
            out.append(f'{where}: {a:02X} -> {b:02X}')
        return out

    def explored_file(self):
        p = find_file(self.run.game, 'Explored.UM5')
        return p.read_bytes() if p else b''

    def save_game(self):
        """As if the player saved: SAVED.GAM changes and gets newer; both keep
        their explored maps within their 5-second check."""
        p = self.run.saved_gam
        data = bytearray(p.read_bytes())
        data[0xF00] ^= 1
        p.write_bytes(bytes(data))
        t = time.time() + 5
        os.utime(p, (t, t))
        time.sleep(6.5)

    def keys_from_bios(self):
        """The keys put into the BIOS keyboard buffer, in order."""
        keys = []
        for _, off, data, _ in list(self.fake.writes):
            if 0x41E <= off < 0x43E and len(data) == 2:
                keys.append(BDA_KEYS.get(data[1], f'scan {data[1]:02X}'))
        return keys


class Original(Common):
    which = 'original'

    def start(self, explored=None, wait=True, **settings):
        self.settings.update(settings)
        p = find_file(self.run.game, 'Explored.UM5')
        if p:
            p.unlink()
        if explored is not None:
            (self.run.game / 'Explored.UM5').write_bytes(explored)
        lines = [f'game_folder = {self.run.game}\\', f'window_title = {self.fake.title}',
                 f'map_size = {self.map_size}', 'docking = 0', 'hide_title_bar = 0', 'cloud_saves = 0']
        lines += [f'{k} = {int(v)}' for k, v in self.settings.items()]
        (self.run.tool / 'Data' / 'Settings.txt').write_text('\r\n'.join(lines) + '\r\n', 'latin-1')
        self.t = original.Tool(self.run.tool / 'Ultimapper_5.exe', [], self.fake, self.run.work)
        self.t.main = self.t.find('TMap_Form', timeout=15)
        if not self.t.main:
            raise RuntimeError('Ultimapper did not open its window')
        self.t.place(self.t.main, -2540 + 660, 60)
        if wait:
            self.settle(1.5)

    def hud_window(self):
        return self.t.find('THUD_Form', timeout=0.5)

    def settle(self, minimum=0.8, limit=8.0):
        time.sleep(minimum)
        end = time.monotonic() + limit
        last = None
        while time.monotonic() < end:
            snap = self.t.capture(self.t.main)
            key = snap.tobytes() if snap else b''
            if key == last:
                return
            last = key
            time.sleep(0.35)

    def view(self, name):
        h = {'map': lambda: self.t.main, 'hud': self.hud_window,
             'lists': lambda: self.t.find('TInventory_Form', timeout=1)}[name]()
        if not h:
            return None
        return self.t.capture_texts(h)

    def title(self):
        return original.window_text(self.t.main)

    def menu(self, *path):
        items = self.t.popup(self.t.main)
        it = original.Tool.find_item(items or [], list(path))
        if not it:
            raise RuntimeError(f'no menu item {path}')
        if not it[2]:
            return 'disabled'
        self.t.command(it[1])
        time.sleep(0.4)
        return 'ok'

    def menu_tree(self):
        def walk(items):
            return [['-' if c == '-' else c.replace('&', '').split('\t')[0], en, ch, walk(sub) if sub else None]
                    for c, _, en, ch, sub in items]
        return comparable_menu(walk(self.t.popup(self.t.main) or []))

    def click(self, x, y, button='left', mods=()):
        self.t.mouse(self.t.main, x, y, button, mods)
        time.sleep(0.3)

    # ---- the editor ------------------------------------------------------------------
    def editor(self):
        """Ultimapper's editor (its menu's Debug, Editor); its controls by name."""
        self.menu('Debug', 'Editor')
        self.ed = self.t.find('TEditor_Form', timeout=10)
        if not self.ed:
            raise RuntimeError('Ultimapper did not open its editor')
        time.sleep(0.8)
        self.edc = {k: h for k, h in self.t.form_controls(self.ed, EDITOR_CONTROLS).items() if not k.endswith('_GroupBox')}

    def editor_values(self):
        return self.t.control_values(self.edc)

    def editor_pick(self, name, i):
        self.t.select(self.edc[name], i)
        time.sleep(0.6)

    def editor_set(self, name, text):
        self.t.set_text(self.edc[name], str(text))
        time.sleep(0.1)

    def editor_check(self, name, on):
        h = self.edc[name]
        if (original.user32.SendMessageW(h, original.BM_GETCHECK, 0, 0) == 1) != on:
            self.t.click_button(h)
        time.sleep(0.3)

    def editor_click(self, name):
        self.t.click_button(self.edc[name])
        time.sleep(1.0)

    # ---- the spell list / inventory window ------------------------------------------------
    def lists_window(self):
        return self.t.find('TInventory_Form', timeout=3)

    def lists(self, *path):
        """The list window from the menu; its client size and frame kept for the page."""
        self.menu(*path)
        time.sleep(0.8)
        self.lists_geom(self.lists_window())

    def lists_geom(self, h):
        if h and not getattr(self, 'lists_seen', False):   # its first size in the session
            c, w = original.rect(h, client=True), original.rect(h)
            cw, ch = c[2] - c[0], c[3] - c[1]
            self.run.lists_geom = (cw, ch, w[2] - w[0] - cw, w[3] - w[1] - ch)
            self.lists_seen = True

    def hud_click(self, fx, fy, what='left'):
        """A click on the HUD at fractions of its client size; the list window it shows kept
        as lists() keeps it."""
        h = self.hud_window()
        c = original.rect(h, client=True)
        self.t.mouse(h, int(fx * (c[2] - c[0])), int(fy * (c[3] - c[1])), what)
        time.sleep(0.8)
        self.lists_geom(self.t.find('TInventory_Form', timeout=1))

    def lists_aside(self):
        """The list window moved off the HUD (as one would to click the HUD)."""
        self.t.place(self.lists_window(), original.LEFT[0] + 20, original.LEFT[1] + 700)
        time.sleep(0.3)

    def lists_client(self):
        h = self.t.find('TInventory_Form', timeout=1)   # shown ones only
        if not h:
            return None
        c = original.rect(h, client=True)
        return [c[2] - c[0], c[3] - c[1]]

    def lists_caption(self):
        h = self.t.find('TInventory_Form', timeout=1)
        return original.window_text(h) if h else None

    def lists_mouse(self, x, y, what='move'):
        self.t.mouse(self.lists_window(), x, y, what)
        time.sleep(0.5)

    def lists_key(self, name):
        self.t.key(self.lists_window(), LIST_KEYS[name])
        time.sleep(0.5)

    def dosbox_foreground(self):
        """DOSBox the foreground window (what the tool's GetForegroundWindow gets): its
        quickfight sends keys only then."""
        self.t.shared.foreground = self.fake.hwnd
        self.t.shared.write()

    def save_map(self):
        """Save map as bitmap: the name its save dialog offers, the picture saved."""
        from PIL import Image
        target = self.run.work / 'u5map.bmp'
        if target.exists():
            target.unlink()
        self.t.shared.write(file_answer=str(target))
        n0 = len(self.t.log())
        self.menu('Save map as bitmap')
        time.sleep(1.5)
        name = next((line.split('|', 1)[1] for line in self.t.log()[n0:] if line.split(' ')[1:2] == ['savefile']), None)
        return name, Image.open(target).convert('RGB') if target.exists() else None

    # ---- the log, dialogs, files written ---------------------------------------------------
    def log_text(self):
        """The log window's lines (its memo's, shown or not; none while nothing made its window)."""
        h = self.t.find('TLog_Form', visible=False, timeout=2)
        memo = next((c[1] for c in self.t.controls(h) if c[0] == 'TMemo'), None) if h else None
        return log_lines(original.window_text(memo)) if memo else []

    def dialogs(self, wait=2.0):
        """The input boxes and messages shown since the last call (caption and texts), each
        answered with the next given answer."""
        out = []
        own = {self.t.main}
        end = time.monotonic() + (wait if self.pending else 0.3)
        while time.monotonic() < end:
            h = next((w for w in self.t.windows() if original.class_name(w) in ('TMessageForm', 'TForm') and w not in own), None)
            if not h:
                time.sleep(0.1)
                continue
            # its caption, and the texts it paints (labels have no windows): through the
            # sandbox's log of a capture
            self.t.capture(h)
            time.sleep(0.2)
            want, texts = '%08x' % h, [original.window_text(h)]
            for line in self.t.log():
                p = line.split(' ', 2)
                if len(p) == 3 and p[1] in ('text', 'drawtext'):
                    head, text = p[2].split('|', 1)
                    if head.split(' ')[3].lower().rjust(8, '0') == want and original.unescape(text) not in texts:
                        texts.append(original.unescape(text))
            out.append(' '.join(' '.join(texts).split()))
            controls = self.t.controls(h)
            ans = self.pending.pop(0) if self.pending else None
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

    def files_since(self):
        """From now on: the files the tool writes into the game folder."""
        self.since = time.time() - 0.05

    def new_files(self, wait=3.0):
        """[(name, size, md5)] of the game folder's files written since files_since (its own
        Explored.UM5 left out), and of the backup folders made since (copies keep their
        files' times)."""
        end = time.monotonic() + wait
        while True:
            got = [(p.name, p.read_bytes()) for p in self.run.tool.glob('*.UM5') if p.stat().st_mtime >= self.since]
            for p in self.run.game.rglob('*'):
                if not p.is_file():
                    continue
                if 'Save backups' in p.parts:
                    if p.parent.stat().st_ctime >= self.since:
                        got.append((p.name, p.read_bytes()))
                elif p.stat().st_mtime >= self.since and p.name.upper() != 'EXPLORED.UM5':
                    got.append((p.name, p.read_bytes()))
            if got or time.monotonic() > end:
                return files_digest(got)
            time.sleep(0.3)

    def backup_folders(self):
        """The names of the folders under Save backups, the time in each as yyyy-mm-dd - hh.nn."""
        d = self.run.game / 'Save backups'
        return sorted(re.sub(r'^\d{4}-\d\d-\d\d - \d\d\.\d\d', 'yyyy-mm-dd - hh.nn', p.name) for p in d.iterdir()) \
            if d.exists() else []

    def move(self, x, y):
        self.t.mouse(self.t.main, x, y, 'move')
        time.sleep(0.3)

    def key(self, vk, char=None, mods=()):
        self.t.key(self.t.main, vk, char, mods)
        time.sleep(0.3)

    def keys_sent(self):
        out = []
        for line in self.t.log():
            p = line.split()
            if len(p) >= 5 and p[1] == 'keybd' and not int(p[4]) & 2:
                out.append(VK_KEYS.get(int(p[2]), f'vk {int(p[2]):02X}'))
        return out

    def finish(self):
        if hasattr(self, 't'):
            self.t.close()
            self.sandbox_log = self.t.log()

    def explored(self):
        """Explored.UM5 as the tool leaves it (after closing)."""
        self.finish()
        return self.explored_file()


# Menu items that are one side's own: the original's window and Windows matters, the
# page's browser matters (README: what a browser can't do)
MENU_OWN = {'Match DOSBox size', 'Switch docking', 'Toggle title bar', 'Change hotkey', 'Global hotkey',
            'Open game folder', 'Settings', 'Fit to window', 'Show HUD', 'Open in its own window', 'Game folder…'}


def comparable_menu(items):
    """A menu tree without MENU_OWN items, separators collapsed as a menu shows them."""
    out = []
    for cap, en, ch, sub in items:
        if cap in MENU_OWN:
            continue
        if cap == '-' and (not out or out[-1][0] == '-'):
            continue
        out.append([cap, en, ch, comparable_menu(sub) if sub else None])
    while out and out[-1][0] == '-':
        out.pop()
    return out


PAGE_SETUP = '''(() => {
  for (const k of Object.keys(localStorage)) localStorage.removeItem(k);
  localStorage.setItem('um5.settings', JSON.stringify(%s));
  return new Promise(res => { const q = indexedDB.deleteDatabase('ultimapper5'); q.onsuccess = q.onerror = q.onblocked = () => res(1); });
})()'''


class Page(Common):
    which = 'page'

    def start(self, explored=None, wait=True, **settings):
        self.settings.update(settings)
        b = self.b = self.run.browser
        v = {SETTINGS[k][0]: (val if k == 'quickfight_interval' else bool(val)) for k, val in self.settings.items()}
        v['size'] = self.map_size
        v['hud'] = True
        b.goto(f'http://127.0.0.1:{self.fake.port}/{self.fake.BLANK}')
        b.js(PAGE_SETUP % harness.json.dumps(v))
        p = find_file(self.run.game, 'Explored.UM5')   # the original's from its run
        if p:
            p.unlink()
        if explored is not None:
            (self.run.game / 'Explored.UM5').write_bytes(explored)
        b.goto(f'http://127.0.0.1:{self.fake.port}/ultimapper5.html?data=game/')
        b.wait('Files.ok()', 20)
        b.js(f"document.querySelector('#mapwrap').style.width = '{self.run.hud_w}px'; 1")
        if wait:
            self.settle(1.5)

    def settle(self, minimum=0.8, limit=8.0):
        b = self.b
        t0 = b.js('Game.tick')
        time.sleep(minimum)
        try:
            b.wait(f'Game.tick >= {t0 + 4}', limit)
        except TimeoutError:
            pass
        b.js("Hud.last = ''; Hud.draw(); 1")

    def view(self, name):
        if name == 'map':
            return self.b.canvas('#map')
        if name == 'hud':
            if self.b.js("document.querySelector('#hud').classList.contains('hidden')"):
                return None
            return self.b.canvas('#hud')
        if name == 'lists':
            return self.b.canvas('#listsCanvas') if self.b.js("!!document.getElementById('listsCanvas')") else None
        raise KeyError(name)

    def title(self):
        return self.b.js("document.querySelector('#title').textContent")

    def menu(self, *path):
        self.answer_next()   # the answers ready before a dialog opens
        r = self.b.js('''(path => {
          let items = Menu.items(), it = null;
          for (const p of path) {
            it = items.find(i => i !== '-' && i.label.replace(/\\u2026$/, '').replace(/ \\(currently \\d+\\)$/, '') === p);
            if (!it) return 'missing';
            items = it.sub || [];
          }
          if (it.disabled) return 'disabled';
          it.act();
          return 'ok';
        })(%s)''' % harness.json.dumps(list(path)))
        if r == 'missing':
            raise RuntimeError(f'no menu item {path}')
        time.sleep(0.4)
        return r

    def menu_tree(self):
        return comparable_menu(self.b.js('''(() => { const walk = items => items.map(i => i === '-' ? ['-', false, false, null]
          : [i.label, !i.disabled, !!i.checked, i.sub ? walk(i.sub) : null]); return walk(Menu.items()); })()'''))

    def canvas_xy(self):
        return self.b.js("(r => [r.left, r.top])(document.querySelector('#map').getBoundingClientRect())")

    def at(self, x, y):
        """Viewport coordinates of the map's pixel (x, y): mouse events come
        in whole pixels and the page maps them with trunc(client - left)."""
        ox, oy = self.canvas_xy()
        return math.ceil(ox + x), math.ceil(oy + y)

    def click(self, x, y, button='left', mods=()):
        self.b.mouse(*self.at(x, y), button, mods)
        time.sleep(0.3)

    # ---- the editor (its controls by the original's names) -----------------------------
    def editor(self):
        self.menu('Debug', 'Editor')
        self.b.wait('!!document.getElementById("editor") && !!Editor.c.Characters_ListBox', 15)

    def editor_values(self):
        return self.b.js('Editor.values()')

    def editor_pick(self, name, i):
        self.b.js(f'Editor.pick({harness.json.dumps(name)}, {int(i)})')
        time.sleep(0.2)

    def editor_set(self, name, text):
        self.b.js(f'Editor.set({harness.json.dumps(name)}, {harness.json.dumps(str(text))})')

    def editor_check(self, name, on):
        self.b.js(f'Editor.pick({harness.json.dumps(name)}, {1 if on else 0})')

    def editor_click(self, name):
        self.b.js(f'Editor.pick({harness.json.dumps(name)})')
        time.sleep(0.6)

    # ---- the spell list / inventory window (the original's size, which it gave) -----------
    def lists(self, *path):
        self.lists_geom()
        self.menu(*path)
        time.sleep(0.6)

    def lists_geom(self):
        g = getattr(self.run, 'lists_geom', None)
        if g and not getattr(self, 'lists_seen', False):   # the original's first size
            self.b.js(f'Lists.size({g[0]}, {g[1]}, [{g[2]}, {g[3]}], true); 1')
            self.lists_seen = True

    def hud_click(self, fx, fy, what='left'):
        self.lists_geom()
        r = self.b.js("(c => (b => [b.left, b.top, c.width, c.height])(c.getBoundingClientRect()))"
                      "(document.querySelector('#hud'))")
        self.b.mouse(r[0] + int(fx * r[2]), r[1] + int(fy * r[3]), what)
        time.sleep(0.6)

    def lists_aside(self):
        """The list window moved off the HUD (below it)."""
        self.b.js("(d => { const r = document.querySelector('#hud').getBoundingClientRect(); "
                  "d.style.left = r.left + 'px'; d.style.top = r.bottom + 10 + 'px'; })(document.getElementById('lists'))")
        time.sleep(0.2)

    def lists_client(self):
        return self.b.js("(() => { const c = document.getElementById('listsCanvas'); return c ? [c.width, c.height] : null; })()")

    def lists_caption(self):
        return self.b.js("(() => { const d = document.getElementById('lists'); return d ? d.querySelector('.t').textContent : null; })()")

    def lists_mouse(self, x, y, what='move'):
        r = self.b.js("(() => { const c = document.getElementById('listsCanvas'); if (!c) return null; "
                      "const b = c.getBoundingClientRect(); return [b.left, b.top]; })()")
        if r:
            self.b.mouse(r[0] + x, r[1] + y, what)
        time.sleep(0.4)

    def lists_key(self, name):
        key, code = PAGE_LIST_KEYS[name]
        self.b.key(key, code, LIST_KEYS[name])
        time.sleep(0.4)

    def dosbox_foreground(self):
        pass   # the page's keys go through the memory, whatever has the focus

    def save_map(self):
        """Save map as bitmap: the file's name, its picture (with the map canvas's text boxes)."""
        from PIL import Image
        self.files_since()
        boxes = self.b.js("window.__fidCanvas ? __fidCanvas('#map').boxes : []")
        self.menu('Save map as bitmap')
        for _ in range(30):
            got = [p for p in self.b.downloads.iterdir() if not p.name.endswith('.crdownload')]
            if got:
                time.sleep(0.2)
                img = Image.open(got[0]).convert('RGB')
                img.load()
                img.info['texts'] = boxes
                return got[0].name, img
            time.sleep(0.2)
        return None, None

    # ---- the log, dialogs, files given (downloads) -------------------------------------------
    def log_text(self):
        return log_lines(''.join(l + '\n' for l in self.b.js('logLines')))   # as a memo's text, each line ended

    def answer_next(self):
        self.b.dialog_answers[:] = [False if a in ('No', 'Cancel') else True if a in ('Yes', 'OK') else a for a in self.pending]

    def dialogs(self, wait=2.0):
        time.sleep(0.3 if not self.pending else 0.6)
        out = [' '.join((m or '').split()) for t, m in self.b.dialogs]
        self.b.dialogs.clear()
        self.pending.clear()
        self.b.dialog_answers.clear()
        return out

    def files_since(self):
        for p in self.b.downloads.iterdir():
            p.unlink()

    def new_files(self, wait=3.0):
        """[(name, size, md5)] of the downloads since files_since (a zip's files instead of it)."""
        end = time.monotonic() + wait
        while True:
            got = [p for p in self.b.downloads.iterdir() if not p.name.endswith('.crdownload')]
            if got or time.monotonic() > end:
                break
            time.sleep(0.3)
        items = []
        for p in got:
            data = p.read_bytes()
            if p.suffix.lower() == '.zip':
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    items += [(n, z.read(n)) for n in z.namelist()]
            else:
                items.append((p.name, data))
        return files_digest(items)

    def backup_folders(self):
        """The backup zips' names as the original's folders (the time as yyyy-mm-dd - hh.nn)."""
        return sorted(re.sub(r'^\d{4}-\d\d-\d\d - \d\d\.\d\d', 'yyyy-mm-dd - hh.nn', p.stem)
                      for p in self.b.downloads.glob('*.zip'))

    def move(self, x, y):
        self.b.mouse(*self.at(x, y), 'move')
        time.sleep(0.3)

    def keys_sent(self):
        return self.keys_from_bios()

    def finish(self):
        # off the page: it would go on reading and writing (quickfight) the next session's game
        if hasattr(self, 'b'):
            self.b.goto(f'http://127.0.0.1:{self.fake.port}/{self.fake.BLANK}')

    def explored(self):
        import base64
        b64 = self.b.js('Explored.file().then(a => { let s = ""; for (const c of a) s += String.fromCharCode(c); return btoa(s); })')
        return base64.b64decode(b64)


# ---- the sessions -------------------------------------------------------------------

def explored_runs(f):
    """Explored.UM5 as readable lines: the explored cells of each map, row by row."""
    if not f:
        return []
    regions = [('world', 0, 256), ('underworld', 0x10000, 256)]
    regions += [(f'place {loc} floor {s - 1}', 0x20000 + (loc - 1) * 0x1400 + s * 0x400, 32)
                for loc in range(1, 33) for s in range(5)]
    regions += [(f'dungeon {loc} level {z}', 0x48000 + (loc - 33) * 0x200 + z * 0x40, 8)
                for loc in range(33, 41) for z in range(8)]
    out = []
    for name, off, n in regions:
        for y in range(n):
            row = f[off + y * n:off + (y + 1) * n]
            runs, x = [], 0
            while x < n:
                if row[x]:
                    a = x
                    while x < n and row[x]:
                        x += 1
                    runs.append(f'{a}-{x - 1}' if x - 1 > a else str(a))
                else:
                    x += 1
            if runs:
                out.append(f'{name} row {y}: {" ".join(runs)}')
    return out


def see_explored(s):
    """The explored maps both keep after the game was saved."""
    s.save_game()
    s.observe('explored', explored_runs(s.explored()))


def see(s, *views, title=True):
    for v in views:
        s.observe(v, s.view(v))
    if title:
        s.observe('title', s.title())


def town(s):
    """Britain: the floor from memory, NPCs with names, the party."""
    st = s.run.state().town(2, 0, 16, 20)
    st.unit(1, 0x30, 18, 20).unit(2, 0x31, 13, 21).npc(0, 1, 1).npc(1, 2, 2)
    s.set(st)
    s.start(towns_explored=1)
    see(s, 'map', 'hud')


def towns(s):
    """Every kind of small map and floor; NPC names on and off."""
    r = s.run
    s.set(r.state().town(17, 0, 15, 26))
    s.start(towns_explored=1)
    for loc, z, x, y in ((17, -1, 15, 20), (17, 1, 15, 15), (17, 3, 12, 12), (18, -1, 10, 10), (18, 2, 14, 14),
                         (9, 0, 10, 10), (12, 2, 16, 16), (13, 0, 15, 15), (16, 0, 15, 15), (19, 0, 20, 8),
                         (25, 1, 10, 20), (30, 2, 5, 5), (32, -1, 16, 16), (4, -1, 8, 8), (8, 1, 30, 1)):
        st = r.state().town(loc, z, x, y)
        st.unit(1, 0x50, min(x + 2, 31), y, z).unit(2, 0x51, x, max(y - 3, 0), z).unit(3, 0x52, 1, 1, z)
        st.npc(0, 1, 3).npc(1, 2, 0x82).npc(2, 3, 5)
        s.poke(st)
        s.settle()
        see(s, 'map')
    s.menu('Map elements', 'NPC names')
    s.settle()
    see(s, 'map')


def towns_unexplored(s):
    """Towns explored off: the view marks the explored cells, units only in view."""
    r = s.run
    st = r.state().town(5, 0, 10, 10)
    st.unit(1, 0x50, 12, 10).unit(2, 0x51, 25, 25).npc(0, 1, 2).npc(1, 2, 3)
    s.set(st)
    s.start(towns_explored=0)
    see(s, 'map')
    for x, y in ((14, 12), (20, 18), (26, 26)):
        st = r.state().town(5, 0, x, y)
        st.unit(1, 0x50, 12, 10).unit(2, 0x51, 25, 25).npc(0, 1, 2).npc(1, 2, 3)
        s.poke(st)
        s.settle()
        see(s, 'map')
    # the view lags behind the map: nothing marked
    st = r.state().town(5, 1, 10, 10)
    st.view[5 * 32 + 5] ^= 0x55
    s.poke(st)
    s.settle()
    see(s, 'map')


def world(s):
    """The world map at several places, titles on, explored everywhere."""
    r = s.run
    s.set(r.state().world(100, 120))
    s.start(world_explored=1, world_titles=1)
    see(s, 'map', 'hud')
    for x, y in ((3, 4), (250, 252), (128, 128), (0, 0), (255, 255), (86, 108)):
        s.poke(r.state().world(x, y))
        s.settle()
        see(s, 'map')


def world_unexplored(s):
    """Exploring the world: what the party sees is marked, titles of explored places only."""
    r = s.run
    s.set(r.state().world(86, 108))
    s.start(world_explored=0, world_titles=1)
    see(s, 'map')
    for x, y in ((92, 108), (98, 112), (104, 118), (2, 3), (253, 254)):
        s.poke(r.state().world(x, y))
        s.settle()
    see(s, 'map')
    s.menu('Map elements', 'World titles')
    s.settle()
    see(s, 'map')
    see_explored(s)


def world_debug(s):
    """Debug mode: the chunk grid and the game's 2x2 chunks."""
    r = s.run
    s.set(r.state().world(100, 120))
    s.start(world_explored=1, debug_mode=1)
    see(s, 'map')
    s.poke(r.state().world(200, 40))
    s.settle()
    see(s, 'map')


def lens(s):
    """A click on the world map turns the zoom lens on and off; it follows the mouse."""
    r = s.run
    s.set(r.state().world(100, 120))
    s.start(world_explored=1)
    s.move(200, 240)
    s.click(200, 240)
    s.settle()
    see(s, 'map')
    for x, y in ((10, 10), (500, 500), (256, 30)):
        s.move(x, y)
        s.settle(0.5)
        see(s, 'map')
    s.click(256, 30)
    s.settle()
    see(s, 'map')


def under(s):
    """The underworld: titles on and off, explored on and off."""
    r = s.run
    s.set(r.state().world(100, 120, under=True))
    s.start(underworld_explored=1, underworld_titles=1)
    see(s, 'map')
    s.poke(r.state().world(30, 200, under=True))
    s.settle()
    see(s, 'map')
    s.menu('Map exploration', 'Underworld explored')
    s.settle()
    see(s, 'map')
    s.menu('Map elements', 'Underworld titles')
    s.settle()
    see(s, 'map')


def hover(s):
    """The cell under the mouse: a frame and the title's second coordinates,
    gone three seconds after the mouse stops."""
    r = s.run
    st = r.state().town(2, 0, 16, 20)
    s.set(st)
    s.start(towns_explored=1)
    s.move(100, 100)
    s.settle(0.5)
    see(s, 'map')
    s.move(300, 400)
    s.settle(0.5)
    see(s, 'map')
    time.sleep(3.5)
    s.settle(0.5)
    see(s, 'map')
    s.poke(r.state().world(100, 120))
    s.settle()
    s.move(256, 256)
    s.settle(0.5)
    s.observe('title', s.title())


def arrow_cell(s, x, y):
    """The party's cell in a dungeon (the arrow is the page's own drawing)."""
    f = max(1, min(4, s.map_size // 128))
    o = (s.map_size - 128 * f) // 2
    return [(o + x * 16 * f, o + y * 16 * f, o + (x + 1) * 16 * f, o + (y + 1) * 16 * f)]


def see_dungeon(s, x, y):
    img = s.view('map')
    if img is not None:
        img.info['ignore'] = arrow_cell(s, x, y)
    s.observe('map', img)
    s.observe('title', s.title())


def dungeons(s):
    """Every dungeon, some levels, the four facings; explored on."""
    r = s.run
    s.set(r.state().dungeon(33, 0, 1, 1))
    s.start(dungeons_explored=1)
    for loc in range(33, 41):
        for z, x, y, f in ((0, 1, 1, 0), (3, 4, 5, 1), (7, 6, 2, 2)):
            s.poke(r.state().dungeon(loc, z, x, y, f))
            s.settle(0.6)
            see_dungeon(s, x, y)


def dungeon_unexplored(s):
    r = s.run
    s.set(r.state().dungeon(35, 1, 2, 2, 3))
    s.start(dungeons_explored=0)
    see_dungeon(s, 2, 2)
    for x, y in ((3, 2), (4, 2), (4, 3), (4, 4)):
        s.poke(r.state().dungeon(35, 1, x, y, 2))
        s.settle(0.6)
    see_dungeon(s, 4, 4)
    s.move(256, 256)
    s.settle(0.5)
    s.observe('title', s.title())
    see_explored(s)


def combat(s):
    """A fight: combatants by flags, the active one, the crosshair, debug mode."""
    r = s.run
    units = [(0x30, 25, 0, 4, 2), (0x31, 12, 8, 7, 3), (0x32, 30, 0x81, 2, 4), (0x33, 9, 0x10, 9, 6),
             (0x34, 40, 0x80, 6, 6), (0x35, 7, 0x01, 8, 8), (0x36, 0, 0, 1, 1), (0x40, 99, 0x18, 10, 10)]
    s.set(r.state().combat(units=units, active=1, aim=(4, 3)))
    s.start()
    see(s, 'map', 'hud')
    s.poke(r.state().combat(units=units, active=7))
    s.settle()
    see(s, 'map')
    s.move(4 * 46 + 10, 2 * 46 + 10)
    s.settle(0.5)
    see(s, 'map')
    time.sleep(3.5)   # the mouse's cell is forgotten three seconds after it last moved
    s.menu('Debug', 'Debug-mode')
    s.settle()
    see(s, 'map')
    s.poke(r.state().combat(units=[], over=True))
    s.settle()
    see(s, 'map')


def messages(s):
    """What shows instead of the map: character creation, not playing, dead."""
    r = s.run
    st = r.state().town(13, 0, 15, 15)
    st.save[0x6B4] = st.save[0x6B6] = 0
    st.save[0x2F5] = st.save[0x2F6] = 0
    s.set(st)
    s.start()
    see(s, 'map', 'hud')
    st = r.state().world(100, 120)
    st.save[0x2ED] = 0x40
    s.poke(st)
    s.settle()
    see(s, 'map')
    st = r.state().world(100, 120)
    for k in range(3):
        st.set(k, hp=0, status='D')
    s.poke(st)
    s.settle()
    see(s, 'map', 'hud')


def name_mismatch(s):
    """The saved game's name differs from the one in memory."""
    st = s.run.state().world(100, 120)
    s.set(st)
    other = s.run.state().world(100, 120)
    other.set(0, name='Lord')
    s.run.saved_gam.write_bytes(bytes(other.save))
    s.start()
    see(s, 'map')


def hud_party(s):
    """The HUD for parties of one to six, every status, bars at their limits."""
    r = s.run
    s.set(r.state(members=1).world(100, 120))
    s.start()
    see(s, 'hud', title=False)
    for n in (2, 4, 6):
        s.poke(r.state(members=n).world(100, 120))
        s.settle()
        see(s, 'hud', title=False)
    st = r.state(members=6).world(100, 120)
    st.set(0, status='P', hp=1, maxhp=90).set(1, status='S', hp=60, maxhp=60, xp=6400, level=8)
    st.set(2, status='D', hp=0).set(3, status='C', hp=30, maxhp=60, xp=799, level=4, mp=99)
    st.set(4, status='R', hp=200, maxhp=240, xp=0, level=1).set(5, status='I', level=0, xp=50)
    st.set(5, eq=[0x03, 0x0F, 0x29, 0x08, 0x2A, 0x2F])
    st.save[0x2D9], st.save[0x2DB] = 0, 59
    st.save[0x206], st.save[0x207], st.save[0x208], st.save[0x20B] = 99, 0, 255, 10
    s.poke(st)
    s.settle()
    see(s, 'hud', title=False)


def menu_states(s):
    """The popup menu: items, checks and what is enabled, in a town and in a fight."""
    r = s.run
    s.set(r.state().town(2, 0, 16, 20))
    s.start(npc_names=0, auto_level_up=1)
    s.observe('menu', s.menu_tree())
    s.poke(r.state().combat(units=[(0x30, 25, 0, 4, 2)]))
    s.settle()
    s.observe('menu', s.menu_tree())


def explore_menu(s):
    """Explore area, unexplore area, unexplore all."""
    r = s.run
    s.set(r.state().town(6, 0, 10, 10))
    s.start(towns_explored=0)
    s.menu('Map exploration', 'Explore area')
    s.settle()
    see(s, 'map')
    s.menu('Map exploration', 'Unexplore area')
    s.settle()
    see(s, 'map')
    s.poke(r.state().world(50, 60))
    s.settle()
    s.menu('Map exploration', 'World explored')
    s.settle()
    s.menu('Map exploration', 'Explore area')
    s.settle()
    see(s, 'map')
    see_explored(s)


def explored_import(s):
    """An Explored.UM5 in the game folder: both start with what it holds."""
    f = bytearray(0x49000)
    for y in range(100, 140):
        f[y * 256 + 80:y * 256 + 130] = b'\1' * 50                       # the world
    for y in range(30, 60):
        f[0x10000 + y * 256 + 20:0x10000 + y * 256 + 90] = b'\1' * 70    # the underworld
    o = 0x20000 + (2 - 1) * 0x1400 + 1 * 0x400                            # Britain, floor 0
    for y in range(5, 25):
        f[o + y * 32 + 3:o + y * 32 + 20] = b'\1' * 17
    o = 0x48000 + (34 - 33) * 0x200 + 2 * 0x40                            # Despise, level 2
    f[o:o + 30] = b'\1' * 30
    r = s.run
    s.set(r.state().world(100, 120))
    s.start(explored=bytes(f), world_explored=0, underworld_explored=0, towns_explored=0, dungeons_explored=0)
    see(s, 'map')
    for st in (r.state().world(40, 40, under=True), r.state().town(2, 0, 16, 20)):
        s.poke(st)
        s.settle()
        see(s, 'map')
    s.poke(r.state().dungeon(34, 2, 1, 1))
    s.settle()
    see_dungeon(s, 1, 1)


def forward_time(s):
    st = s.run.state().world(100, 120)
    st.save[0x2D9] = st.save[0x2DA] = 23
    s.set(st)
    s.start()
    s.menu('Debug', 'Forward time by 1 hour')
    s.settle()
    s.observe('memory', s.memory_changes())
    s.menu('Debug', 'Forward time by 1 hour')
    s.settle()
    s.observe('memory', s.memory_changes())
    see(s, 'hud', title=False)


def teleport(s):
    """Debug mode, Ctrl+click: on the world, in a town, in a dungeon, in a fight."""
    r = s.run
    s.set(r.state().world(100, 120))
    s.start(debug_mode=1)
    s.click(300, 200, mods=('ctrl',))
    s.settle()
    s.observe('memory', s.memory_changes())
    st = r.state().town(2, 0, 16, 20).unit(1, 0x50, 18, 20)
    s.set(st, saved=False)
    s.settle()
    s.click(18 * 16 + 4, 20 * 16 + 4, mods=('ctrl',))   # a unit there: no
    s.click(10 * 16 + 4, 12 * 16 + 4, mods=('ctrl',))
    s.settle()
    s.observe('memory', s.memory_changes())
    s.set(r.state().dungeon(34, 2, 1, 1), saved=False)
    s.settle()
    s.click(256, 256, mods=('ctrl',))
    s.settle()
    s.observe('memory', s.memory_changes())
    s.set(r.state().combat(units=[(0x30, 25, 0, 4, 2)], active=0), saved=False)
    s.settle()
    s.click(5 * 46 + 10, 5 * 46 + 10, mods=('ctrl',))
    s.settle()
    s.observe('memory', s.memory_changes())


def exit_combat(s):
    s.set(s.run.state().combat(units=[(0x30, 25, 0, 4, 2)]))
    s.start()
    s.menu('Debug', 'Exit combat')
    time.sleep(1.5)
    s.observe('memory', s.memory_changes())
    s.observe('keys', s.keys_sent())


def auto_level(s):
    """Auto level up: members with the experience for the next level."""
    st = s.run.state(members=6).world(100, 120)
    st.set(0, xp=400, level=3).set(1, xp=6400, level=7, st=30, dx=30, it=30).set(2, xp=99, level=1)
    st.set(3, xp=800, level=8).set(4, xp=1600, level=5, st=29, dx=30, it=30)
    s.set(st)
    s.start(auto_level_up=1)
    s.settle(1.5)
    changes = s.memory_changes()
    # which of STR / DEX / INT under 30 goes up is chosen at random by both: count them
    stats = {f'save+{2 + k * 32 + o:X}' for k in range(6) for o in (0x0C, 0x0D, 0x0E)}
    s.observe('memory', [c for c in changes if c.split(':')[0] not in stats])
    s.observe('stats raised', sorted(sum(1 for c in changes if c.split(':')[0] in
                                         {f'save+{2 + k * 32 + o:X}' for o in (0x0C, 0x0D, 0x0E)})
                                     for k in range(6)))


# the editor's controls that are windows, by class and place in its client area (its form)
EDITOR_CONTROLS = {
    ('TGroupBox', 16, 8): 'Characters_GroupBox', ('TGroupBox', 528, 8): 'Miscellaneous_GroupBox', ('TListBox', 32, 32): 'Characters_ListBox',
    ('TComboBox', 184, 32): 'Gender_ComboBox', ('TComboBox', 352, 32): 'Helmet_ComboBox', ('TEdit', 600, 32): 'Karma_Edit',
    ('TComboBox', 184, 56): 'Class_ComboBox', ('TComboBox', 352, 56): 'Armor_ComboBox', ('TComboBox', 184, 80): 'Status_ComboBox',
    ('TComboBox', 352, 80): 'Weapon_ComboBox', ('TGroupBox', 528, 88): 'Inventory_GroupBox', ('TComboBox', 352, 104): 'Shield_ComboBox',
    ('TEdit', 184, 112): 'STR_Edit', ('TListBox', 544, 112): 'Items_ListBox', ('TComboBox', 352, 128): 'Ring_ComboBox',
    ('TEdit', 184, 136): 'DEX_Edit', ('TComboBox', 352, 152): 'Amulet_ComboBox', ('TEdit', 184, 160): 'INT_Edit',
    ('TEdit', 352, 184): 'O17_Edit', ('TEdit', 400, 184): 'O18_Edit', ('TEdit', 184, 192): 'CurrentHP_Edit',
    ('TEdit', 232, 192): 'MaximumHP_Edit', ('TEdit', 184, 216): 'MP_Edit', ('TEdit', 184, 248): 'XP_Edit',
    ('TEdit', 184, 272): 'Level_Edit', ('TGroupBox', 16, 328): 'Consumables_GroupBox', ('TGroupBox', 184, 328): 'QuestItems_GroupBox',
    ('TEdit', 96, 352): 'Food_Edit', ('TCheckBox', 200, 352): 'Grapple_CheckBox', ('TCheckBox', 336, 352): 'Amulet_CheckBox',
    ('TEdit', 96, 376): 'Gold_Edit', ('TCheckBox', 200, 376): 'MagicCarpet_CheckBox', ('TCheckBox', 336, 376): 'Crown_CheckBox',
    ('TEdit', 96, 400): 'Torches_Edit', ('TCheckBox', 200, 400): 'Spyglass_CheckBox', ('TCheckBox', 336, 400): 'Sceptre_CheckBox',
    ('TCheckBox', 200, 424): 'HMSCapePlans_CheckBox', ('TCheckBox', 336, 424): 'Cowardice_CheckBox', ('TEdit', 96, 432): 'Keys_Edit',
    ('TButton', 696, 440): 'Decrease_Button', ('TButton', 744, 440): 'Increase_Button', ('TCheckBox', 200, 448): 'Sextant_CheckBox',
    ('TCheckBox', 336, 448): 'Falsehood_CheckBox', ('TEdit', 96, 456): 'SkullKeys_Edit', ('TCheckBox', 200, 472): 'PocketWatch_CheckBox',
    ('TCheckBox', 336, 472): 'Hatred_CheckBox', ('TEdit', 96, 488): 'Gems_Edit', ('TCheckBox', 200, 496): 'BlackBadge_CheckBox',
    ('TCheckBox', 336, 496): 'SandalwoodBox_CheckBox', ('TButton', 664, 504): 'SaveChanges_Button',
}


def editor_view(s):
    """The editor (menu): the first six characters' fields and equipment, the party's
    consumables, quest items, items and karma, as its controls show them."""
    st = s.run.state(members=6).world(100, 120)
    st.save[0x209], st.save[0x20A], st.save[0x20E], st.save[0x2E2] = 0xFF, 2, 0xFF, 63
    st.save[0x24A + 13], st.save[0x282 + 2] = 3, 1
    s.set(st)
    s.start()
    s.editor()
    for i in range(6):
        s.editor_pick('Characters_ListBox', i)
        vals = s.editor_values()
        for k in sorted(vals):
            v = vals[k]
            if i and k in ('Items_ListBox',) + tuple(n for n in vals if n.endswith('_ComboBox')):
                v = {kk: vv for kk, vv in v.items() if kk != 'items'}
            s.observe(f'{i} {k}', v)


def editor_changes(s):
    """Save changes: the second character's numbers, lists and equipment, the consumables, quest
    items, an item's count (+ twice, - once) and karma changed, as the memory takes them."""
    st = s.run.state(members=6).world(100, 120)
    s.set(st)
    s.start()
    s.editor()
    s.editor_pick('Characters_ListBox', 1)
    for name, v in (('STR_Edit', 25), ('DEX_Edit', 'x'), ('CurrentHP_Edit', 80), ('MaximumHP_Edit', 300), ('XP_Edit', 999),
                    ('Level_Edit', 5), ('MP_Edit', 7), ('Food_Edit', 500), ('Gold_Edit', 1234), ('Keys_Edit', 7),
                    ('Torches_Edit', 9), ('Karma_Edit', 77)):
        s.editor_set(name, v)
    s.editor_pick('Class_ComboBox', 2)
    s.editor_pick('Status_ComboBox', 2)
    s.editor_pick('Gender_ComboBox', 1)
    s.editor_pick('Helmet_ComboBox', 3)
    s.editor_pick('Weapon_ComboBox', 10)
    s.editor_check('Grapple_CheckBox', True)
    s.editor_check('Crown_CheckBox', True)
    s.editor_check('MagicCarpet_CheckBox', True)
    items = s.editor_values()['Items_ListBox']['items']
    row = next((k for k, t in enumerate(items) if t.startswith('Dagger')), 2)
    s.editor_pick('Items_ListBox', row)
    s.editor_click('Increase_Button')
    s.editor_click('Increase_Button')
    s.editor_click('Decrease_Button')
    s.observe('item row', s.editor_values()['Items_ListBox'])
    s.editor_click('SaveChanges_Button')
    s.observe('memory', s.memory_changes())


def list_state(s):
    """Spells mixed (one at 99), items of every column (one at 255), scrolls, potions, quest items
    (an FF among them), magic carpets; the party's reagents (some none)."""
    st = s.run.state().world(100, 120)
    for i, v in ((0, 5), (13, 2), (47, 1), (27, 99)):
        st.save[0x24A + i] = v
    for off, v in ((0x21A, 2), (0x21A + 30, 1), (0x21A + 17, 255), (0x27A + 2, 3), (0x282 + 7, 1), (0x209, 1),
                   (0x217, 0xFF), (0x20A, 3)):
        st.save[off] = v
    return st


def list_row(s, i):
    """The middle of spell row i (1 up) in the list window, where the original puts the rows."""
    w, h = s.run.lists_geom[:2]
    fh = (h - 2 * round(w / 50) - 58) // 50
    return w // 2, (h - 50 * fh - 58) // 2 + 2 * (fh + 5) + (i - 1) * (fh + 1) + fh // 2


def lists(s):
    """The spell list and the inventory (menu: Spells, Inventory): the window's caption and picture."""
    s.set(list_state(s))
    s.start()
    s.lists('Spells')
    s.observe('spells caption', s.lists_caption())
    s.observe('spells', s.view('lists'))
    s.lists('Inventory')
    s.observe('inventory caption', s.lists_caption())
    s.observe('inventory', s.view('lists'))


def lists_choose(s):
    """The spell list's choice with the mouse and the keys; a click mixes a spell that can be
    mixed (and not one that can't), so does Enter, as the memory takes it; Tab and a right click
    switch lists, the inventory mixes nothing."""
    s.set(list_state(s))
    s.start()
    s.lists('Spells')
    s.lists_mouse(*list_row(s, 3))
    s.observe('mouse on row 3', s.view('lists'))
    for k in ('down', 'down', 'up', 'end', 'home', 'num2', 'num8', 'num2'):
        s.lists_key(k)
    s.observe('keys', s.view('lists'))
    s.lists_mouse(*list_row(s, 5), 'left')   # In Lor: ash
    s.observe('a click mixes', s.memory_changes())
    s.lists_mouse(*list_row(s, 1), 'left')   # An Nox: no ginseng
    s.observe('a click mixes nothing', s.memory_changes())
    s.lists_key('down')                      # An Ylem: garlic and blood moss
    s.lists_key('enter')
    s.observe('Enter mixes', s.memory_changes())
    s.observe('after mixing', s.view('lists'))
    s.lists_key('tab')
    s.observe('Tab', s.lists_caption())
    s.lists_key('enter')
    s.observe('the inventory mixes nothing', s.memory_changes())
    s.observe('inventory', s.view('lists'))
    s.lists_mouse(20, 20, 'right')
    s.observe('right click', s.lists_caption())
    s.observe('spells again', s.view('lists'))


def hud_lists(s):
    """A click on the HUD's right part: the left button shows the spell list (with the focus: its
    keys work), the right one the inventory; a click with the list shown (moved off the HUD)
    starts its choice over; a click on the party's columns shows nothing."""
    s.set(list_state(s))
    s.start()
    s.hud_click(0.1, 0.5)
    s.observe('party columns', s.lists_client())
    s.hud_click(0.95, 0.5)
    s.observe('left button', s.lists_caption())
    s.lists_key('down')
    s.lists_key('down')
    s.observe('spells', s.view('lists'))
    s.lists_aside()
    s.hud_click(0.95, 0.5)
    s.observe('clicked again', s.view('lists'))
    s.lists_key('esc')
    s.hud_click(0.95, 0.5, 'right')
    s.observe('right button', s.lists_caption())
    s.observe('inventory', s.view('lists'))


def lists_size(s):
    """PageDown and PageUp: the window 16 pixels shorter / taller in its proportions and what it
    shows then; hidden (Esc) and shown again, the size kept; R; the choice gone after 10 seconds
    without the mouse or a key."""
    s.set(list_state(s))
    s.start()
    s.lists('Spells')
    s.lists_key('pgdn')
    s.lists_key('pgdn')
    s.observe('smaller', s.lists_client())
    s.observe('smaller spells', s.view('lists'))
    for _ in range(5):
        s.lists_key('pgup')
    s.observe('larger', s.lists_client())
    s.lists_key('tab')
    s.observe('larger inventory', s.view('lists'))
    s.lists_key('esc')
    s.observe('hidden', s.lists_client())
    s.lists('Spells')
    s.observe('shown again', s.lists_client())
    s.lists_key('r')
    s.observe('R', s.lists_client())
    s.lists_mouse(*list_row(s, 7))
    time.sleep(11)
    s.observe('10 seconds later', s.view('lists'))


def debug_log(s):
    """The log with debug_log on: its lines when the game is found (DATA.OVL, SAVED.GAM), at a
    new location and with the party dead; off (the default) it stays empty."""
    r = s.run
    s.set(r.state().world(100, 120))
    s.start(debug_log=1)
    s.observe('found', s.log_text())
    s.poke(r.state().town(2, 0, 16, 20))
    s.settle()
    s.observe('new location', s.log_text())
    st = r.state().world(100, 120)
    for k in range(3):
        st.set(k, hp=0, status='D')
    s.poke(st)
    s.settle()
    s.observe('dead', s.log_text())


def log_off(s):
    """debug_log off (the default): nothing logged."""
    s.set(s.run.state().world(100, 120))
    s.start()
    s.poke(s.run.state().town(2, 0, 16, 20))
    s.settle()
    s.observe('log', s.log_text())


def tlk_entry(s, name, k):
    """The bytes of entry k (in file order) of a TLK file."""
    t = find_file(s.run.game, name).read_bytes()
    offs = sorted(t[4 + i * 4] | t[5 + i * 4] << 8 for i in range(t[0] | t[1] << 8))
    return t[offs[k]:offs[k + 1] if k + 1 < len(offs) else len(t)]


def dump_tlk(s):
    """Debug, Dump TLK during talk: the talk buffer's script (an NPC's of TOWNE.TLK, an @ after
    it) as the log's text; then a buffer without an @: two lines logged (debug_log on)."""
    st = s.run.state().world(100, 120)
    st.talk = tlk_entry(s, 'TOWNE.TLK', 3)[:900] + b'\xc0' + bytes(20)
    s.set(st)
    s.start(debug_log=1)
    s.menu('Debug', 'Dump TLK during talk')
    time.sleep(1.0)
    s.observe('dump', s.log_text())
    st.talk = bytes(1000)
    s.poke(st)
    s.menu('Debug', 'Dump TLK during talk')
    time.sleep(1.0)
    s.observe('no entry', s.log_text())


def dump_memory(s):
    """Debug, Dump memory to file: the game's data segment (64 KB) as Memory_Dump.UM5."""
    s.set(s.run.state().world(100, 120))
    s.start()
    s.files_since()
    s.menu('Debug', 'Dump memory to file')
    s.observe('file', s.new_files())


def backup(s):
    """Backup saved game: the description asked for; the saved game's files and Explored.UM5
    (written by then) into a folder (the page: a zip) named by the time and the description
    without the characters a file name can't have and double spaces."""
    s.set(s.run.state().world(100, 120))
    s.start()
    s.save_game()   # the game saved: both keep the explored maps (the original's Explored.UM5)
    s.files_since()
    s.answer('my: backup  one?')
    s.menu('Backup saved game')
    s.observe('asked', s.dialogs())
    s.observe('files', s.new_files())
    s.observe('folder', s.backup_folders())


def save_map(s):
    """Save map as bitmap: the name offered and the picture saved, on the world, in the
    underworld, on a town's floor and in its basement, in a dungeon and in a fight."""
    r = s.run

    def save(what):
        name, img = s.save_map()
        if img is not None and what == 'dungeon':
            img.info['ignore'] = arrow_cell(s, 1, 1)   # the party's arrow, the page's own drawing
        s.observe(f'{what} name', name)
        s.observe(what, img)
    s.set(r.state().world(100, 120))
    s.start()
    save('world')
    for what, st in (('underworld', r.state().world(100, 120, under=True)), ('town', r.state().town(2, 0, 16, 20)),
                     ('basement', r.state().town(4, -1, 16, 20)), ('dungeon', r.state().dungeon(34, 2, 1, 1)),
                     ('fight', r.state().combat(units=[(0x30, 25, 0, 4, 2)]))):
        s.poke(st)
        s.settle()
        save(what)


def quickfight_run(s, st, seconds=3.0, lines=8):
    """Quickfight (menu) on a state, the game taking the keys: the first keys put in, what it
    wrote, the log's first lines (debug_log on; the lines of the game found left out)."""
    s.set(st)
    s.start(debug_log=1)
    s.dosbox_foreground()
    s.menu('Toggle quickfight')
    s.consume_keys(seconds)
    s.observe('keys', s.keys_sent()[:4])
    s.observe('memory', s.memory_changes())
    s.observe('log', [l for l in reversed(s.log_text()) if 'DATA.OVL' not in l and 'SAVED.GAM' not in l][:lines])


def quickfight_melee(s):
    """Quickfight, the first member's turn, a monster next to it: it attacks (A)."""
    quickfight_run(s, s.run.state().combat(units=[(0x30, 25, 0, 3, 8)], active=0))


def quickfight_aim(s):
    """Quickfight, a bow, a monster in range, the crosshair active (on the member): insta-aimed
    (the crosshair onto it, Enter)."""
    st = s.run.state().combat(units=[(0x30, 25, 0, 3, 5)], active=0, aim=(3, 9)).set(0, eq=[0xFF, 0x0D, 0x1A, 0xFF, 0xFF, 0xFF])
    st.save[0x2F7] = 0x1A
    quickfight_run(s, st, lines=12)


def quickfight_crosshair(s):
    """Quickfight with insta-aiming off: the crosshair moved a step at a time (arrow keys)."""
    st = s.run.state().combat(units=[(0x30, 25, 0, 3, 5)], active=0, aim=(3, 9)).set(0, eq=[0xFF, 0x0D, 0x1A, 0xFF, 0xFF, 0xFF])
    st.save[0x2F7] = 0x1A
    s.settings['quickfight_insta_aim'] = 0
    quickfight_run(s, st, lines=12)


def quickfight_walk(s):
    """Quickfight, a monster out of reach of a melee weapon: steps towards it (arrow keys)."""
    quickfight_run(s, s.run.state().combat(units=[(0x30, 25, 0, 3, 3)], active=0))


def quickfight_none(s):
    """Quickfight with no hostile creature: weapons put back, a message, quickfight off."""
    quickfight_run(s, s.run.state().combat(units=[(0x30, 25, 0x80, 8, 2)], active=0), lines=30)


SESSIONS = {f.__name__: f for f in (
    town, towns, towns_unexplored, world, world_unexplored, world_debug, lens, under, hover, dungeons,
    dungeon_unexplored, combat, messages, name_mismatch, hud_party, menu_states, explore_menu, explored_import,
    forward_time, teleport, exit_combat, auto_level, lists, lists_choose, hud_lists, lists_size, editor_view,
    editor_changes, debug_log, log_off, dump_tlk, dump_memory, backup, quickfight_melee, quickfight_aim,
    quickfight_crosshair, quickfight_walk, quickfight_none, save_map)}

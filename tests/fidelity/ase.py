"""The All-Seeing Eye (1.10, the eXo build) against ase.html, with Eye of the
Beholder 1 and 2.

Both games run in real mode, their data in conventional memory, everything at
fixed distances from the first character's name: the party's coordinates, the
level map (9 / 10 bytes a cell: the four wall ids first), the monsters (30 of
28 / 30 bytes), the items (500 / 600 of 14 bytes), the item types. The
original finds the names it reads from the saved game; the page finds the
records and the game's wall tables by their structure. The test builds that
memory from the eXo saved game (its characters and location), a level map
(EOB 1: ASE's own example of level 1; EOB 2: the game's LEVELn.MAZ) and items
and monsters of its own around the party.

ASE's wizard is the page's start (it finds the game by itself); ASE's map
window is the page's map, its tooltip window the page's tooltip. The explored
maps are files of the game folder (ASE\\Explored_NN.dat, the working set, and
ASE_<slot>\\ copies) for the original, the browser's database for the page:
both are compared as those files' contents."""
import base64
import math
import os
import shutil
import struct
import time
from ctypes import wintypes
from pathlib import Path

import harness
import original

MEM = 1 << 20
NAME0 = 0x32792          # the first character's name
TABLES_AT = 0x50000      # the game's wall tables (shape map, special types, flags), which the page looks for
GAMES = {
    1: dict(dir='eob1', save='EOBDATA.SAV', first=0, size=243, cell=9, items=500, mon_size=28, types=57, levels=12,
            coords=0x646, map=-0x3CEE, item_at=-0x67B2, mon_at=-0x6B00, types_at=-0x4B92, block=2, dir_at=4,
            table_len=70, flags=[0x07, 0x00, 0x40, 0xA8, 0x88, 0x88, 0x88, 0x9F, 0xA8, 0x88, 0x88, 0x88, 0x9F, 0xAA,
                                 0x8A, 0x8A, 0x8A, 0x9F]),
    2: dict(dir='eob2', save='EOBDATA0.SAV', first=0x14, size=345, cell=10, items=600, mon_size=30, types=64, levels=16,
            coords=-0x783C, map=-0x42AA, item_at=-0x7440, mon_at=-0x77E0, types_at=-0x519C, block=4, dir_at=6,
            table_len=80, flags=[0x07, 0x00, 0x40, 0xA8, 0x88, 0x88, 0x88, 0x9F, 0xA8, 0x88, 0x88, 0x88, 0x9F, 0xA8,
                                 0x88, 0x88, 0x88, 0x9F]),
}
# items of the test: (item index, x, y, level or None (the party's), type, value) - type and value None:
# the game's own for that index (ASE's Item_Type.dat / Item_Subtype.dat), so ASE's Item_List names it
ITEMS = {
    1: [(57, 11, 16, None, None, None), (58, 11, 16, None, None, None), (48, 10, 14, None, None, None),
        (21, 12, 15, None, None, None), (47, 9, 15, None, None, None), (59, 10, 16, None, None, None),
        (45, 11, 15, None, None, 3), (18, 9, 16, None, None, 5), (23, 10, 14, 2, None, None),
        (26, 2, 2, None, None, None), (4, 12, 14, None, None, 1), (10, 8, 15, None, None, None)],
    2: [(16, 11, 6, None, None, None), (24, 12, 5, None, None, None), (59, 10, 5, None, None, None),
        (21, 11, 4, None, None, 5), (62, 11, 4, None, None, None), (45, 12, 6, None, None, None),
        (20, 10, 6, None, None, 40), (34, 3, 3, None, None, None), (31, 11, 5, 5, None, None)],
}
# monsters: (type, x, y, hit points max, hit points)
MONSTERS = {
    1: [(0, 12, 16, 6, 4), (1, 9, 14, 5, 0), (12, 11, 14, 20, 20), (11, 10, 16, 8, 8), (25, 9, 16, 10, 3), (3, 2, 30, 9, 9)],
    2: [(4, 12, 4, 30, 12), (7, 10, 4, 15, 15), (2, 1, 1, 9, 9)],
}


def lines(path):
    return path.read_bytes().decode('latin-1').split('\r\n')


class State:
    """EOB 1 or 2 in memory."""

    def __init__(self, run, level=None, x=None, y=None, d=None, items=True, monsters=True):
        self.run, g = run, run.g
        s = run.save
        self.records = [bytearray(s[g['first'] + k * g['size']:g['first'] + (k + 1) * g['size']]) for k in range(6)]
        o = g['first'] + 6 * g['size']
        lv, blk, dr = (struct.unpack_from('<HHH', s, o) if run.id == 1 else
                       struct.unpack_from('<HxxHH', s, o))
        self.level = lv if level is None else level
        self.x = (blk & 31) if x is None else x
        self.y = (blk >> 5) if y is None else y
        self.d = dr if d is None else d
        self.maze = run.maze(self.level)
        self.items = list(ITEMS[run.id]) if items is True else list(items or [])
        self.monsters = list(MONSTERS[run.id]) if monsters is True else list(monsters or [])
        self.types = bytearray(g['types'] * 16)
        for t in range(g['types']):   # some made-up usability flags, so the tweaks change them
            self.types[t * 16 + 5] = (t * 7) & 0x3F
            self.types[t * 16 + 6] = t & 1

    def image(self):
        g, run = self.run.g, self.run
        mem = bytearray(MEM)
        for k, r in enumerate(self.records):
            at = NAME0 - 2 + k * g['size']
            mem[at:at + g['size']] = r
        c = NAME0 + g['coords']
        mem[c:c + 2] = struct.pack('<H', self.level)
        mem[c + g['block']:c + g['block'] + 2] = struct.pack('<H', self.y << 5 | self.x)
        mem[c + g['dir_at']] = self.d
        m = NAME0 + g['map']
        for b in range(1024):
            x, y = b & 31, b >> 5
            mem[m + b * g['cell']:m + b * g['cell'] + 4] = self.maze[(y * 32 + x) * 4:(y * 32 + x) * 4 + 4]
        it = NAME0 + g['item_at']
        for n, (idx, x, y, lv, typ, val) in enumerate(self.items):
            names = run.item_names
            base = run.item_list[idx]
            nid = next((i for i, nm in enumerate(names) if nm and nm.lower() == base.split(' of ')[0].split(' +')[0].lower()),
                       2)
            rec = bytes([nid, nid, 0, 0, run.item_type[idx] if typ is None else typ, 0]) + \
                struct.pack('<HHH', y << 5 | x, 0, 0) + \
                bytes([self.level if lv is None else lv, run.item_value[idx] if val is None else val])
            mem[it + idx * 14:it + idx * 14 + 14] = rec
        mo = NAME0 + g['mon_at']
        for n, (typ, x, y, hp_max, hp) in enumerate(self.monsters):
            rec = bytearray(g['mon_size'])
            rec[0] = typ
            rec[2:4] = struct.pack('<H', y << 5 | x)
            rec[0xC:0xE] = struct.pack('<H', hp_max)
            rec[0xE:0x10] = struct.pack('<H', hp)
            mem[mo + n * g['mon_size']:mo + (n + 1) * g['mon_size']] = rec
        t = NAME0 + g['types_at']
        mem[t:t + len(self.types)] = self.types
        n = g['table_len']
        special = bytearray(n)
        special[3], special[8], special[13] = 1, 6, 1
        flags = bytearray(n)
        flags[:len(g['flags'])] = bytes(g['flags'])
        mem[TABLES_AT:TABLES_AT + 3 * n] = bytes(n) + special + flags
        return bytes(mem)


class Run:
    def __init__(self, work, tool_dir, game_dir, fake, browser, out):
        self.work, self.out, self.fake, self.browser = Path(work), Path(out), fake, browser
        self.id = 1 if Path(game_dir).name.lower() == 'eob1' else 2
        self.g = GAMES[self.id]
        self.game = self.work / self.g['dir']
        if self.game.exists():
            shutil.rmtree(self.game)
        self.game.mkdir(parents=True)
        for f in Path(game_dir).iterdir():
            if f.is_file():
                if f.suffix.lower() == '.pdf':
                    (self.game / f.name).write_bytes(b'%PDF-1.0\n')
                elif f.stat().st_size < 2 << 20:
                    shutil.copyfile(f, self.game / f.name)
        self.saves = {p.name: p.read_bytes() for p in self.game.iterdir() if p.suffix.upper() == '.SAV'}
        self.save = self.saves[self.g['save']]
        self.tool = self.work / 'ASE'
        if not (self.tool / 'ASE.exe').exists() or getattr(Run, 'prepared', None) != str(tool_dir):
            self.patch_log = original.prepare_tool(tool_dir, self.tool, harness.SANDBOX_DLL)
            Run.prepared = str(tool_dir)
        data = self.tool / f'EOB{self.id}'
        self.item_list = lines(data / 'Item_List.txt')
        self.item_names = lines(data / 'Item_Name.txt')
        self.item_type = (data / 'Item_Type.dat').read_bytes()
        self.item_value = (data / 'Item_Subtype.dat').read_bytes()
        fake.routes.update({'': str(harness.REPO / 'web'), 'game/': str(self.game), 'ase/': str(self.tool)})
        self.cell = 20

    def maze(self, level):
        """A level's wall ids, 32 x 32 cells of 4 (N E S W), row by row."""
        if self.id == 1:
            p = self.tool / 'EOB1_MAZ' / 'level1_example.maz'
        else:
            p = self.game / f'LEVEL{level}.MAZ'
        data = p.read_bytes() if p.exists() else b''
        return data[6:6 + 4096] if len(data) >= 4102 else bytes(4096)

    def reset_game(self):
        """The saved games as they came (dated ten minutes ago), nothing explored, no notes."""
        old = time.time() - 600
        for name, data in self.saves.items():
            p = self.game / name
            p.write_bytes(data)
            os.utime(p, (old, old))
        for p in self.game.iterdir():
            if p.is_dir() and (p.name.upper().startswith('ASE') or p.name == 'Save backups'):
                shutil.rmtree(p)
            elif p.suffix.upper() == '.TXT' and p.name.lower() in ('monsters.txt', 'items.txt'):
                p.unlink()

    def write_explored(self, folder, level, cells, faces=()):
        """<folder>\\Explored_<level>.dat (5120 bytes: [x][y] of 5, the cell and its faces N E S W)."""
        data = bytearray(5120)
        for x, y in cells:
            data[(x * 32 + y) * 5] = 1
        for x, y, f in faces:
            data[(x * 32 + y) * 5 + 1 + f] = 1
        d = self.game / folder
        d.mkdir(exist_ok=True)
        (d / f'Explored_{level:02d}.dat').write_bytes(bytes(data))

    def explored_file(self, folder, level):
        p = self.game / folder / f'Explored_{level:02d}.dat'
        return p.read_bytes() if p.exists() else None

    def date_save(self, age=0, slot=1):
        """The game saved (into slot), age seconds ago."""
        name = 'EOBDATA.SAV' if self.id == 1 else f'EOBDATA{slot - 1}.SAV'
        p = self.game / name
        if not p.exists():
            p.write_bytes(self.save)
        t = time.time() - age
        os.utime(p, (t, t))

    def state(self, **kw):
        return State(self, **kw)


def explored_runs(data):
    """An explored file (5120 bytes, [x][y] of 5: cell, faces N E S W) as runs per column
    and what (c cell, n e s w faces); nothing explored: []."""
    out = []
    if not data:
        return out
    for x in range(32):
        y = 0
        while y < 32:
            k = data[(x * 32 + y) * 5:(x * 32 + y) * 5 + 5]
            if any(k):
                y0, what = y, ''.join(ch for ch, v in zip('cnesw', k) if v)
                while y < 32 and ''.join(ch for ch, v in zip('cnesw', data[(x * 32 + y) * 5:(x * 32 + y) * 5 + 5]) if v) == what:
                    y += 1
                out.append(f'x {x:02d}, y {y0:02d}-{y - 1:02d}: {what}')
            else:
                y += 1
    return out


class Common(harness.Side):
    def __init__(self, run):
        super().__init__(run, run.fake)
        self.pending = []
        self.settings = dict(buttons=1, illusionary=0, monsters=0, items=0, hints=0, notes=0)

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
        """The answers to the next dialogs: 'Yes', 'No', 'OK', 'Cancel' or a text to enter."""
        self.pending += answers


SETTING_LINES = ['buttons', 'illusionary', 'monsters', 'items', 'hints', 'notes']


class Original(Common):
    which = 'original'

    def start(self, **settings):
        r, g = self.run, self.run.g
        self.settings.update(settings)
        s = self.settings
        span = f'${0x1000000 + MEM:x}'
        dat = ['0' if r.id == 1 else '1', str(r.game) + '\\' if r.id == 1 else '', str(r.game) + '\\' if r.id == 2 else '',
               self.fake.title, '$1000000', span, '$1000000', span, '', '', str(r.cell), '0', '0'] + \
            [str(s[k]) for k in SETTING_LINES] + ['0', '0', '0']
        (r.tool / 'ASE.dat').write_bytes('\r\n'.join(dat).encode('mbcs') + b'\r\n')
        for name in ('Monsters.txt', 'Items.txt'):
            if (r.tool / name).exists():
                (r.tool / name).unlink()
        self.t = original.Tool(r.tool / 'ASE.exe', [], self.fake, r.work)
        self.wizard = self.t.find('TSearch_Form', timeout=15)
        if not self.wizard:
            raise RuntimeError('ASE did not open its wizard')
        self.t.main = self.wizard
        self.t.place(self.wizard, -2540, 20)
        time.sleep(1.0)
        self.t.click_button(self.t.control('TButton', h=self.wizard, text='Search'))
        self.main = self.t.find('TMain_Form', timeout=30)
        if not self.main:
            memo = self.t.control('TMemo', h=self.wizard)
            raise RuntimeError('ASE did not find the game: ' + (original.window_text(memo)[-400:] if memo else ''))
        self.t.main = self.main
        self.t.place(self.main, -2540 + 760, 20)
        self.settle(1.0)

    def settle(self, minimum=0.8, limit=6.0):
        time.sleep(minimum)
        end = time.monotonic() + limit
        last = None
        while time.monotonic() < end:
            snap = self.t.capture(self.t.main)
            key = snap.tobytes() if snap else b''
            if key == last:
                return
            last = key
            time.sleep(0.3)

    def view(self, name):
        if name == 'map':
            return self.t.capture_texts(self.main)
        raise KeyError(name)

    def title(self):
        return original.window_text(self.main)

    def tooltip(self):
        """The tooltip window's text, '' when it is hidden."""
        h = self.t.find('TLegend_Form', timeout=0.3)
        if not h or not original.user32.IsWindowVisible(h):
            return ''
        memo = self.t.control('TMemo', h=h)
        return original.window_text(memo).replace('\r\n', '\n').rstrip('\n') if memo else ''

    def menu(self, *path):
        items = self.t.popup(self.main)
        it = original.Tool.find_item(items or [], list(path))
        if not it:
            raise RuntimeError(f'no menu item {path}')
        if not it[2]:
            return 'disabled'
        self.t.command(it[1])
        time.sleep(0.5)
        return 'ok'

    def menu_tree(self):
        def walk(items):
            out = []
            for c, _, en, ch, sub in items:
                cap, _, key = c.replace('&', '').partition('\t')
                out.append(['-' if c == '-' else cap, key, en, ch, walk(sub) if sub else None])
            return out
        return comparable_menu(walk(self.t.popup(self.main) or []))

    def at(self, x, y):
        return x * self.run.cell + self.run.cell // 2, y * self.run.cell + self.run.cell // 2

    def move(self, x, y):
        self.t.mouse(self.main, *self.at(x, y), 'move')
        time.sleep(0.4)

    def click(self, x, y, mods=()):
        self.t.mouse(self.main, *self.at(x, y), 'left', mods)
        time.sleep(0.4)

    def key(self, name, mods=()):
        vk = KEYS[name][1] if name in KEYS else ord(name.upper())
        self.t.key(self.main, vk, mods=mods)
        time.sleep(0.4)

    def dialogs(self, wait=2.0):
        """What the dialogs shown since the last call said (message dialogs: their text;
        input dialogs: their caption and prompt); answered with the given answers."""
        out = []
        end = time.monotonic() + (wait if self.pending else 0.2)
        while time.monotonic() < end:
            h = next((w for w in self.t.windows() if original.class_name(w) in ('TMessageForm', 'TForm')
                      and w not in (self.main, self.wizard)), None)
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

    def explored(self, folder, level):
        """An explored file: the working set's is written when the level changes or ASE
        closes, so this reads it after the window closed (only at a session's end)."""
        return self.run.explored_file(folder, level)

    def dumped(self, name):
        """A dump ASE wrote into its own folder (and opened, which the sandbox only logs)."""
        p = self.run.tool / name
        return p.read_bytes().decode('latin-1').rstrip('\r\n').split('\r\n') if p.exists() else None

    def export(self):
        """Export map: the name ASE's save dialog offers and the picture it saved."""
        from PIL import Image
        target = self.run.work / 'export.bmp'
        if target.exists():
            target.unlink()
        self.t.shared.write(file_answer=str(target))
        n0 = len(self.t.log())
        self.key('M', mods=('ctrl',))
        time.sleep(1.5)
        name = next((line.split('|', 1)[1] for line in self.t.log()[n0:] if line.split(' ')[1:2] == ['savefile']), None)
        return name, Image.open(target).convert('RGB') if target.exists() else None

    # ---- the character editor ---------------------------------------------------------
    def editor(self):
        self.key('E', mods=('ctrl',))
        self.ed = self.t.find('TEditor_Form', timeout=10)
        if not self.ed:
            raise RuntimeError('no editor')
        time.sleep(0.8)
        self.edc = {}
        for cls, h, text, r in self.t.controls(self.ed, visible=False):
            p = wintypes.POINT(r[0], r[1])
            original.user32.ScreenToClient(self.ed, original.ctypes.byref(p))
            name = EDITOR12.get((cls, p.x, p.y)) or (cls == 'TButton' and (CHAR_BUTTONS.get((p.x, p.y)) or text.replace('&', '')))
            if name:
                self.edc[name] = h

    def characters(self):
        return [[original.window_text(self.edc[f'C{k}']), bool(original.user32.IsWindowEnabled(self.edc[f'C{k}']))]
                for k in range(1, 7)]

    def character(self, i):
        self.t.click_button(self.edc[f'C{i + 1}'])
        time.sleep(0.6)
        out = {k: original.window_text(self.edc[k]) for k in EDITOR12.values() if k in self.edc and k not in
               ('spells', 'inventory', 'items', 'filter', 'mage', 'cleric')}
        out['AC enabled'] = bool(original.user32.IsWindowEnabled(self.edc['AC']))
        for kind in ('mage', 'cleric'):
            self.t.click_button(self.edc[kind])
            time.sleep(0.4)
            out[kind] = self.t.listview_items(self.edc['spells'], 3)
        self.t.click_button(self.edc['mage'])
        time.sleep(0.3)
        out['inventory'] = self.t.listview_items(self.edc['inventory'], 2)
        return out

    def item_list(self):
        return self.t.list_items(self.edc['items'])

    def backup_files(self):
        """The newest backup folder ("<date> - <time> - <comment>"): its comment, then its files
        (path from the folder, MD5)."""
        import hashlib
        root = self.run.game / 'Save backups'
        dirs = sorted(root.iterdir(), key=lambda p: p.stat().st_mtime) if root.exists() else []
        if not dirs:
            return None
        d = dirs[-1]
        return [d.name.split(' - ', 2)[-1]] + sorted(
            f"{str(p.relative_to(d)).replace(chr(92), '/')} {hashlib.md5(p.read_bytes()).hexdigest()}"
            for p in d.rglob('*') if p.is_file())

    def set_field(self, name, value):
        h = self.edc[name]
        if original.class_name(h) == 'TComboBox':
            self.t.select(h, self.t.list_items(h).index(value))
        else:
            self.t.set_text(h, str(value))
        time.sleep(0.2)

    def ed_button(self, text):
        h = next(c[1] for c in self.t.controls(self.ed) if c[0] == 'TButton' and c[2].replace('&', '') == text)
        self.t.click_button(h)
        time.sleep(0.8)

    def learn(self, kind, row, delta):
        self.t.click_button(self.edc[kind])
        time.sleep(0.3)
        self.t.listview_select(self.edc['spells'], row)
        self.ed_button('+' if delta > 0 else '-')

    def set_item(self, slot, item):
        self.t.listview_select(self.edc['inventory'], slot)
        self.t.select(self.edc['items'], item)
        time.sleep(0.2)
        self.ed_button('Set item')

    def finish(self):
        if hasattr(self, 't'):
            self.t.close()


# the ASE editor's controls by (class, place in its form), from its form
EDITOR12 = {
    ('TEdit', 88, 56): 'STR', ('TEdit', 136, 56): 'STR max', ('TEdit', 88, 88): 'STR%', ('TEdit', 136, 88): 'STR% max',
    ('TEdit', 88, 120): 'INT', ('TEdit', 136, 120): 'INT max', ('TEdit', 88, 152): 'WIS', ('TEdit', 136, 152): 'WIS max',
    ('TEdit', 88, 184): 'DEX', ('TEdit', 136, 184): 'DEX max', ('TEdit', 88, 216): 'CON', ('TEdit', 136, 216): 'CON max',
    ('TEdit', 88, 248): 'CHA', ('TEdit', 136, 248): 'CHA max', ('TEdit', 88, 288): 'AC', ('TEdit', 88, 320): 'HP',
    ('TEdit', 136, 320): 'HP max', ('TEdit', 216, 288): 'food', ('TComboBox', 88, 360): 'race',
    ('TComboBox', 88, 392): 'alignment', ('TComboBox', 88, 432): 'class', ('TEdit', 88, 464): 'level 1',
    ('TEdit', 136, 464): 'XP 1', ('TEdit', 88, 496): 'level 2', ('TEdit', 136, 496): 'XP 2', ('TEdit', 88, 528): 'level 3',
    ('TEdit', 136, 528): 'XP 3', ('TListView', 272, 72): 'spells', ('TListView', 536, 72): 'inventory',
    ('TListBox', 848, 72): 'items', ('TEdit', 984, 568): 'filter', ('TRadioButton', 272, 48): 'mage',
    ('TRadioButton', 344, 48): 'cleric',
}
CHAR_BUTTONS = {(8 + 112 * k, 8): f'C{k + 1}' for k in range(6)}


KEYS = {'PgUp': ('PageUp', 0x21), 'PgDn': ('PageDown', 0x22)}
# Menu items that are one side's own: the original's windows (docking, its title bar) and the
# page's own additions (README: what a browser can and can't do)
MENU_OWN = {'Toggle docking', 'Hide title bar', 'Save game slot', 'Fit to window', 'Open in its own window',
            'ASE / ASE3 data folder…', 'Game folder…', 'Legend', 'Debug log', 'Search again', 'Clear explored maps'}


def comparable_menu(items):
    """A menu tree without MENU_OWN items, separators collapsed as a menu shows them."""
    out = []
    for cap, key, en, ch, sub in items:
        if cap in MENU_OWN:
            continue
        if cap == '-' and (not out or out[-1][0] == '-'):
            continue
        out.append([cap, key, en, ch, comparable_menu(sub) if sub else None])
    while out and out[-1][0] == '-':
        out.pop()
    return out


PAGE_SETUP = '''(() => {
  for (const k of Object.keys(localStorage)) localStorage.removeItem(k);
  localStorage.setItem('ase.settings', JSON.stringify(%s));
  return new Promise(res => { const q = indexedDB.deleteDatabase('ase'); q.onsuccess = q.onerror = q.onblocked = () => res(1); });
})()'''
DOWNLOAD_NOTE = "can't be written from here"


class Page(Common):
    which = 'page'

    def start(self, **settings):
        self.settings.update(settings)
        b = self.b = self.run.browser
        b.goto(f'http://127.0.0.1:{self.fake.port}/{self.fake.BLANK}')
        v = {k: bool(self.settings[k]) for k in SETTING_LINES}
        v.update(zoom=self.run.cell, slot=1)
        b.js(PAGE_SETUP % harness.json.dumps(v))
        b.dialogs.clear()
        for p in b.downloads.iterdir():
            p.unlink()
        b.goto(f'http://127.0.0.1:{self.fake.port}/ase.html?asedata=ase/&gamedata=game/')
        b.wait('Game.coords && Game.id', 30)
        self.settle(1.0)

    def settle(self, minimum=0.8, limit=6.0):
        time.sleep(minimum)
        try:
            t0 = self.b.js('Game.tick || 0')
            self.b.wait(f'(Game.tick || 0) >= {t0 + 3}', limit)
        except (TimeoutError, RuntimeError):
            pass

    def view(self, name):
        if name == 'map':
            return self.b.canvas('#map')
        raise KeyError(name)

    def title(self):
        return self.b.js("document.querySelector('#title').textContent")

    def tooltip(self):
        return self.b.js("(t => t.style.display === 'block' ? t.textContent.replace(/\\n+$/, '') : '')(document.querySelector('#tip'))")

    def menu(self, *path):
        self.answer_next()
        r = self.b.js('''(path => {
          let items = Menu.items(), it = null;
          for (const p of path) {
            it = items.find(i => i !== '-' && i.label.replace(/\\u2026$/, '').trimEnd() === p);
            if (!it) return 'missing';
            items = it.sub || [];
          }
          if (it.disabled) return 'disabled';
          setTimeout(() => it.act(), 0);   // dialogs it opens must not hold up this call
          return 'ok';
        })(%s)''' % harness.json.dumps(list(path)))
        if r == 'missing':
            raise RuntimeError(f'no menu item {path}')
        time.sleep(0.5)
        return r

    def menu_tree(self):
        return comparable_menu(self.b.js('''(() => { const walk = items => items.map(i => i === '-' ? ['-', '', false, false, null]
          : [i.label, i.key || '', !i.disabled, !!i.checked, i.sub ? walk(i.sub) : null]); return walk(Menu.items()); })()'''))

    def at(self, x, y):
        ox, oy = self.b.js("(r => [r.left, r.top])(document.querySelector('#map').getBoundingClientRect())")
        c = self.run.cell
        return math.ceil(ox + x * c + c // 2), math.ceil(oy + y * c + c // 2)

    def move(self, x, y):
        self.b.mouse(*self.at(x, y), 'move')
        time.sleep(0.4)

    def click(self, x, y, mods=()):
        self.answer_next()
        self.b.mouse(*self.at(x, y), 'left', mods)
        time.sleep(0.4)

    def key(self, name, mods=()):
        key, vk = KEYS[name] if name in KEYS else (name.lower(), ord(name.upper()))
        code = key if len(key) > 1 else f'Key{key.upper()}'
        self.answer_next()
        self.b.key(key, code, vk, text=key if len(key) == 1 and not mods else None, mods=mods)
        time.sleep(0.4)

    def answer_next(self):
        self.b.dialog_answers[:] = [False if a in ('No', 'Cancel') else True if a in ('Yes', 'OK') else a for a in self.pending]

    def dialogs(self, wait=2.0):
        time.sleep(0.3 if not self.pending else 0.6)
        out = [' '.join((m or '').split()) for t, m in self.b.dialogs if DOWNLOAD_NOTE not in (m or '')]
        self.b.dialogs.clear()
        self.pending.clear()
        self.b.dialog_answers.clear()
        return out

    def explored(self, folder, level):
        b64 = self.b.js(EXPLORED_FILE % harness.json.dumps([folder, level]))
        return base64.b64decode(b64) if b64 else None

    def downloaded(self, pattern, timeout=5.0):
        """The newest file the page offered as a download whose name matches the glob
        pattern: (name, bytes), or (None, None)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = sorted(self.b.downloads.glob(pattern), key=lambda p: p.stat().st_mtime)
            if found and not list(self.b.downloads.glob('*.crdownload')):
                return found[-1].name, found[-1].read_bytes()
            time.sleep(0.2)
        return None, None

    def dumped(self, name):
        _, data = self.downloaded(name.replace('.', '*.'))
        return data.decode('latin-1').rstrip('\r\n').split('\r\n') if data else None

    def backup_files(self):
        """The backup the page offered: a zip named as the original's folder."""
        import hashlib
        import io
        import zipfile
        name, data = self.downloaded('*.zip')
        if not data:
            return None
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            files = sorted(f'{i.filename} {hashlib.md5(z.read(i)).hexdigest()}' for i in z.infolist())
        return [name[:-4].split(' - ', 2)[-1]] + files

    # ---- the character editor ---------------------------------------------------------
    def editor(self):
        self.key('E', mods=('ctrl',))
        self.b.wait("!!document.querySelector('#editor .chars button')", 10)
        time.sleep(0.5)

    def characters(self):
        return self.b.js("[...document.querySelectorAll('#editor .chars button')].slice(0, 6).map(b => [b.textContent, !b.disabled])")

    def character(self, i):
        self.b.js(f"document.querySelectorAll('#editor .chars button')[{i}].click()")
        time.sleep(0.4)
        out = self.b.js('''(() => { const o = {};
          for (const e of document.querySelectorAll('#editor [name]')) if (e.name !== 'spellkind')
            o[e.name] = e.tagName === 'SELECT' ? e.selectedOptions[0]?.textContent || '' : e.value;
          o['AC enabled'] = !document.querySelector('#editor [name=AC]').disabled; return o; })()''')
        for kind, label in (('mage', 'Spells'), ('cleric', 'Prayers')):
            self.b.js(f'''[...document.querySelectorAll('#editor label')].find(l => l.textContent.trim() === '{label}')
              .querySelector('input').click()''')
            time.sleep(0.3)
            out[kind] = self.b.js('''[...document.querySelectorAll('#editor table.spells tr')].slice(1)
              .map(tr => [...tr.children].map(td => td.textContent))''')
        self.b.js('''[...document.querySelectorAll('#editor label')].find(l => l.textContent.trim() === 'Spells')
          .querySelector('input').click()''')
        time.sleep(0.3)
        out['inventory'] = self.b.js('''[...document.querySelectorAll('#editor table.inventory tr')].slice(1)
          .map(tr => [...tr.children].map(td => td.textContent))''')
        return out

    def item_list(self):
        return self.b.js("[...document.querySelectorAll('#editor select[size] option')].map(o => o.textContent)")

    def set_field(self, name, value):
        self.b.js('''((n, v) => { const e = document.querySelector(`#editor [name="${n}"]`);
          if (e.tagName === 'SELECT') e.value = [...e.options].find(o => o.textContent === v).value; else e.value = v;
          e.dispatchEvent(new Event('change')); })(%s, %s)''' % (harness.json.dumps(name), harness.json.dumps(str(value))))
        time.sleep(0.2)

    def ed_button(self, text):
        text = {'Save changes to character': 'Save changes to character'}.get(text, text)
        self.b.js(f'''[...document.querySelectorAll('#editor button')].find(b => b.textContent === {harness.json.dumps(text)}).click()''')
        time.sleep(0.8)

    def learn(self, kind, row, delta):
        label = 'Spells' if kind == 'mage' else 'Prayers'
        self.b.js(f'''[...document.querySelectorAll('#editor label')].find(l => l.textContent.trim() === '{label}')
          .querySelector('input').click()''')
        time.sleep(0.3)
        self.b.js(f"document.querySelectorAll('#editor table.spells tr')[{row + 1}].click()")
        time.sleep(0.3)
        self.ed_button('+' if delta > 0 else '-')

    def set_item(self, slot, item):
        self.b.js(f"document.querySelectorAll('#editor table.inventory tr')[{slot + 1}].click()")
        time.sleep(0.3)
        self.b.js(f"(s => {{ s.selectedIndex = {item}; }})(document.querySelector('#editor select[size]'))")
        self.ed_button('Set item')

    def export(self):
        import io
        from PIL import Image
        for p in self.b.downloads.iterdir():
            p.unlink()
        self.key('M', mods=('ctrl',))
        name, data = self.downloaded('*')
        img = Image.open(io.BytesIO(data)).convert('RGB') if data else None
        if img:   # the text on the map, which the comparison leaves to its looser test
            img.info['texts'] = self.b.js("__fidCanvas('#map').boxes")
        return name, img

    def finish(self):
        # off the page: it would go on reading (and writing) the next session's game
        if hasattr(self, 'b'):
            self.b.goto(f'http://127.0.0.1:{self.fake.port}/{self.fake.BLANK}')


# the page's explored maps as ASE's files: the working set (ASE\) or a slot's copy (ASE_<n>\)
EXPLORED_FILE = '''(async ([folder, lv]) => {
  Store.flush();
  const key = folder === 'ASE' ? `${Game.id}:work:${lv}` : `${Game.id}:${folder.slice(4)}:${lv}`;
  const b = folder === 'ASE' && Store.work[key] ? Store.work[key] : await DB.get('kv', 'exp:' + key);
  if (!b) return null;
  const m = new Uint8Array(b.buffer || b);
  if (!m.some(v => v)) return null;
  let s = '';
  for (const c of m) s += String.fromCharCode(c);
  return btoa(s);
})(%s)'''


# ---- the sessions -------------------------------------------------------------------

def see(s):
    s.observe('map', s.view('map'))
    s.observe('title', s.title())


def search_map(s):
    """The game found; the party moves and turns."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    see(s)
    for dx, dy in ((1, 0), (1, 1), (0, 1)):
        s.poke(r.state(x=st.x + dx, y=st.y + dy))
        s.settle()
    see(s)
    for d in (1, 2, 3):
        s.poke(r.state(x=st.x + 0, y=st.y + 1, d=d))
        s.settle(0.5)
        see(s)


def explore_all(s):
    """Explore level, answered Yes."""
    s.answer('Yes')
    s.key('X')
    s.dialogs()
    s.settle()


def show_toggles(s):
    """The level explored, then buttons, illusionary walls, monsters, items, hints and
    notes shown and hidden by their keys."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    explore_all(s)
    see(s)
    for k in ('M', 'I', 'H', 'B', 'W', 'N', 'M', 'I', 'H', 'B', 'W'):
        s.key(k)
        s.settle(0.6)
        s.observe('map', s.view('map'))


def tooltips(s):
    """The tooltip and the title over cells with items, monsters, hints, features and
    without; the tooltip hides 5 seconds after the mouse stopped."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start(monsters=1, items=1, hints=1)
    explore_all(s)
    cells = [(x, y) for _, x, y, lv, _, _ in ITEMS[r.id] if lv is None] + \
        [(x, y) for _, x, y, _, _ in MONSTERS[r.id]] + [(st.x, st.y), (st.x + 3, st.y + 3), (0, 0), (31, 31)]
    for x, y in cells:
        s.move(0, 0)   # a cell with nothing to tell: the tooltip hides, its 5 seconds start again
        s.move(x, y)
        s.observe(f'tooltip {x},{y}', s.tooltip())
        s.observe('title', s.title())
    for x, y in cells[:3]:   # from one cell to the next: the tooltip still hides 5 s after it appeared
        s.move(x, y)
    s.wait(5.6)
    s.observe('tooltip', s.tooltip())


def hints_level(s):
    """Hints and their tooltips on a level with many (EOB 1 level 1, EOB 2 level 4)."""
    r = s.run
    r.reset_game()
    st = r.state(items=(), monsters=())
    s.set(st)
    s.start(hints=1)
    explore_all(s)
    see(s)
    hints = (r.tool / f'EOB{r.id}' / f'Hints_{st.level:02d}.txt').read_bytes().decode('latin-1').split('\r\n')
    for line in hints:
        if line.startswith('#'):
            x, y = (int(v) - 1 for v in line[1:].split(','))
            s.move(0, 0)
            s.move(x, y)
            s.observe(f'tooltip {x},{y}', s.tooltip())


def menu_states(s):
    """The popup menu, before and after toggles."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    s.observe('menu', s.menu_tree())
    for k in ('M', 'I'):
        s.key(k)
    s.observe('menu', s.menu_tree())


def sizes(s):
    """PgUp makes the cells 2 pixels smaller (not below 14), PgDn larger (not above 32)."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    explore_all(s)
    for k in ['PgUp'] * 4 + ['PgDn'] * 11:
        s.key(k)
        s.settle(0.5)
        s.observe('map', s.view('map'))


def teleport(s):
    """Teleport here: the mouse's cell, from the menu and by key."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    s.move(st.x + 2, st.y)
    s.menu('Teleport here')
    s.settle()
    s.observe('memory', s.memory_changes())
    s.move(st.x, st.y + 3)
    s.key('T')
    s.settle()
    s.observe('memory', s.memory_changes())
    see(s)


def explore_menu(s):
    """Explore level / Unexplore level, ASE's question answered No and Yes; Peek."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    s.answer('No')
    s.menu('Explore level')
    s.observe('dialogs', s.dialogs())
    s.settle()
    see(s)
    s.answer('Yes')
    s.menu('Explore level')
    s.observe('dialogs', s.dialogs())
    s.settle()
    see(s)
    s.answer('Yes')
    s.menu('Unexplore level')
    s.observe('dialogs', s.dialogs())
    s.settle()
    see(s)
    s.key('Z')
    time.sleep(0.6)
    s.observe('map', s.view('map'))
    s.wait(2.5)
    s.observe('map', s.view('map'))


def memory_commands(s):
    """Identify all items, item usability tweaks (on and off), weaken and petrify monsters."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    s.menu('Identify all items')
    s.settle()
    s.observe('memory', s.memory_changes())
    s.poke(r.state())
    s.menu('Item usability tweaks')
    s.settle()
    s.observe('memory', s.memory_changes())
    s.observe('menu', s.menu_tree())
    s.poke(r.state())
    s.menu('Item usability tweaks')
    s.settle()
    s.observe('memory', s.memory_changes())
    for item in ('Weaken monsters to 1 HP', 'Petrify monsters'):
        s.poke(r.state())
        s.observe(item, s.menu('Debug', item))
        s.settle()
        s.observe('memory', s.memory_changes())


def notes(s):
    """Notes: Ctrl+click and the A key ask for one (ASE's question), it shows on the map and in
    the tooltip; an empty one removes it."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    explore_all(s)
    s.answer('Secret door here')
    s.click(st.x + 1, st.y, mods=('ctrl',))
    s.observe('dialogs', s.dialogs())
    s.settle()
    see(s)
    s.move(0, 0)
    s.move(st.x + 1, st.y)
    s.observe('tooltip', s.tooltip())
    s.move(st.x + 2, st.y + 1)
    s.answer('Lever')
    s.key('A')
    s.observe('dialogs', s.dialogs())
    s.settle()
    s.observe('map', s.view('map'))
    s.move(st.x + 1, st.y)
    s.answer('')
    s.key('A')
    s.observe('dialogs', s.dialogs())
    s.settle()
    s.observe('map', s.view('map'))


def dumps(s):
    """Dump monsters and dump items: Monsters.txt and Items.txt."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    for item, name in (('Dump monsters', 'Monsters.txt'), ('Dump items', 'Items.txt')):
        s.menu('Debug', item)
        time.sleep(1.5)
        s.observe(name, s.dumped(name))


def export_map(s):
    """Export map (Ctrl+M): the picture and the name offered."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start(monsters=1, items=1, hints=1)
    explore_all(s)
    name, img = s.export()
    s.observe('name', name)
    s.observe('picture', img)


def debug_mode(s):
    """Debug mode (Ctrl+D): the title with the cell's wall bytes, the tooltips with the raw
    item and monster records, the map."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start(monsters=1, items=1)
    explore_all(s)
    s.key('D', mods=('ctrl',))
    s.settle()
    see(s)
    cells = [(x, y) for _, x, y, lv, _, _ in ITEMS[r.id] if lv is None][:5] + [(x, y) for _, x, y, _, _ in MONSTERS[r.id]][:3]
    for x, y in cells:
        s.move(0, 0)
        s.move(x, y)
        s.observe(f'tooltip {x},{y}', s.tooltip())
        s.observe('title', s.title())


def explored_files(s):
    """The explored maps: slot 1's at the start; the party walks; the game saves (into slot 1:
    its copy is replaced); EOB 2: another slot's copied in, a level changed and back."""
    r = s.run
    r.reset_game()
    st = r.state()
    r.write_explored('ASE_1', st.level, [(x, st.y - 2) for x in range(3, 20)], [(x, st.y - 3, 2) for x in range(3, 20)])
    if r.id == 2:
        r.write_explored('ASE_2', st.level, [(st.x, y) for y in range(0, 32)], [(st.x + 1, y, 3) for y in range(0, 32)])
    s.set(st)
    s.start()
    see(s)
    for dx, dy in ((1, 0), (2, 0), (2, 1), (2, 2)):
        s.poke(r.state(x=st.x + dx, y=st.y + dy))
        s.settle(0.6)
    see(s)
    r.date_save()
    s.wait(4.5)
    s.observe('ASE_1', explored_runs(s.explored('ASE_1', st.level)))
    if r.id == 2:
        s.observe('menu', s.menu_tree())
        s.menu('Copy explored from', 'Slot 2')
        s.settle()
        see(s)
        s.poke(r.state(level=5, x=st.x, y=st.y))
        s.settle(1.5)
        see(s)
        s.poke(r.state())
        s.settle(1.5)
        see(s)


def editor_view(s):
    """The character editor: the characters, each one's fields, spells and inventory, the item list."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    s.editor()
    chars = s.characters()
    s.observe('characters', chars)
    for i, (name, enabled) in enumerate(chars):
        if enabled:
            s.observe(f'character {i}', s.character(i))
    s.observe('items', s.item_list())


def editor_changes(s):
    """The character editor's writes: stats, hit points, race, alignment, class, experience
    saved; spells learnt and unlearnt (at once); an item set into a slot (at once)."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    s.editor()
    s.character(2)
    for k, v in (('STR', 17), ('STR max', 18), ('INT max', 18), ('CHA', 9), ('HP', 120), ('HP max', 140), ('food', 50),
                 ('XP 2', 7777), ('race', 'Dwarf female'), ('alignment', 'True neutral'), ('class', 'Fighter / Mage')):
        s.set_field(k, v)
    s.ed_button('Save changes to character')
    s.observe('memory', s.memory_changes())
    s.learn('mage', 2, +1)
    s.learn('mage', 2, +1)
    s.learn('mage', 0, +1)
    s.learn('mage', 3, -1)
    s.learn('cleric', 1, +1)
    s.learn('cleric', 1, -1)
    s.observe('memory', s.memory_changes())
    s.observe('character 2', s.character(2))
    s.set_item(0, 42)
    s.set_item(13, 59)
    s.observe('memory', s.memory_changes())
    s.observe('character 2', s.character(2))


def backup(s):
    """Backup save game (Ctrl+S): ASE's question, the files of the backup."""
    r = s.run
    r.reset_game()
    st = r.state()
    r.write_explored('ASE_1', st.level, [(x, st.y) for x in range(5, 15)], [(x, st.y, 0) for x in range(5, 15)])
    s.set(st)
    s.start()
    s.answer('before the boss')
    s.key('S', mods=('ctrl',))
    s.observe('dialogs', s.dialogs())
    time.sleep(1.5)
    s.observe('backup', s.backup_files())


SESSIONS = {f.__name__: f for f in (search_map, show_toggles, tooltips, hints_level, menu_states, sizes, teleport,
                                     explore_menu, memory_commands, notes, dumps, export_map, debug_mode,
                                     explored_files, editor_view, editor_changes, backup)}

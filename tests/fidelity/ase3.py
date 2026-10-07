"""The All-Seeing Eye 3 (0.12) against ase.html, with Eye of the Beholder III.

EOB 3 runs on the AESOP engine under DOS/4GW: the level map (32 x 32 bytes,
FF open) sits in a heap block somewhere in the 4 MB of memory, the party's
location (x, y, direction, level) after the party's seven member slots, the
character records 623 bytes apart. The original finds them with the newest
saved game (its Search button); the page by their structure.

ASE3's start form (the saved games, their preview, the party location in a
save, Clear explored, the save file editor) is the page's "Saved games"
dialog; its map window is the page's map. The explored maps are files of
the game folder (ASE\\Explored_NN.dat, one per save slot) for the original,
the browser's database for the page: both are compared as the file's
contents."""
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

MEM = 4 << 20
SIGN_AT, MAP_AT, LOC_AT, RECS_AT = 0x20000, 0x1E13AA, 0x1DA9CB, 0x1D0000
LEVEL_NAMES = ["Warrior's tomb 1", "Warrior's tomb 2", 'Burial glen', 'Forest trail', 'Guildhall quarter ruins',
               "Mages' guild 1", "Mages' guild 2", "Mages' guild 3", "Mages' guild 4", 'Temple quarter ruins',
               'Temple of Lathander 1', 'Temple of Lathander 2', 'Temple of Lathander 3', 'Temple of Lathander 4']
# the start form's controls (client coordinates of their top left corners, from its form)
PREVIEW_AT = (608, 16)
X_EDIT_AT, Y_EDIT_AT = (608 + 248, 504 + 24), (608 + 296, 504 + 24)
KEYS = {'PgUp': ('PageUp', 0x21), 'PgDn': ('PageDown', 0x22)}


def find_file(folder, name):
    for f in Path(folder).iterdir():
        if f.name.lower() == name.lower():
            return f
    return None


class State:
    """EOB 3 in memory: one level's map, the party's location, the records."""

    def __init__(self, run, level=None, x=None, y=None, d=None, save_slot=1):
        self.run = run
        save = (run.game / 'SAVEGAME' / f'ITEMS_{save_slot:02d}.BIN').read_bytes()
        sx, sy, sd, sl = save[252:256]
        self.save = save
        self.level = sl if level is None else level
        self.x, self.y, self.d = (sx if x is None else x), (sy if y is None else y), (sd if d is None else d)
        self.map = bytearray(run.map_of(self.level if 1 <= self.level <= 14 else sl))
        self.stale = True

    def image(self):
        mem = bytearray(MEM)
        mem[SIGN_AT:SIGN_AT + 31] = b'Eye of the Beholder III requires'
        mem[MAP_AT - 8:MAP_AT] = bytes(4) + struct.pack('<I', 0x1234)   # an AESOP heap block's header
        mem[MAP_AT:MAP_AT + 1024] = self.map
        if self.stale:   # an older copy of the map elsewhere (EOB 3 keeps one), slightly different
            old = bytearray(self.map)
            old[0x3F8] = 0xFF
            mem[0x21532B:0x21532B + 1024] = old
        # the party's member objects (as in the save: 20-23, FFFF), then the location
        mem[LOC_AT - 14:LOC_AT + 4] = self.save[238:252] + bytes([self.x, self.y, self.d, self.level])
        for k in range(10):   # the save's records, 627 bytes apart there, 623 in memory
            at = 0x340 + k * 627
            mem[RECS_AT + k * 623:RECS_AT + k * 623 + 0x1F8] = self.save[at - 0x3C:at + 0x1BC]
        return bytes(mem)

    def open_cells(self, n, avoid=()):
        """A walk of n steps from the party over open cells, each next to the last."""
        out, x, y, seen = [], self.x, self.y, {(self.x, self.y), *avoid}
        for _ in range(n):
            for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < 32 and 0 <= ny < 32 and self.map[ny * 32 + nx] == 0xFF and (nx, ny) not in seen:
                    x, y = nx, ny
                    seen.add((x, y))
                    out.append((x, y))
                    break
            else:
                break
        return out

    def first(self, open_=True, near=(16, 16)):
        """The cell nearest to near that is open (or a wall)."""
        cells = [(abs(x - near[0]) + abs(y - near[1]), x, y) for y in range(32) for x in range(32)
                 if (self.map[y * 32 + x] == 0xFF) == open_]
        _, x, y = min(cells)
        return x, y


class Run:
    def __init__(self, work, tool_dir, game_dir, fake, browser, out):
        self.work, self.out, self.fake, self.browser = Path(work), Path(out), fake, browser
        self.game = self.work / 'eob3'
        if self.game.exists():
            shutil.rmtree(self.game)
        self.game.mkdir(parents=True)
        for f in Path(game_dir).iterdir():
            if f.is_file():
                if f.suffix.lower() == '.pdf':
                    (self.game / f.name).write_bytes(b'%PDF-1.0\n')
                elif f.stat().st_size < 2 << 20:
                    shutil.copyfile(f, self.game / f.name)
        shutil.copytree(Path(game_dir) / 'SAVEGAME', self.game / 'SAVEGAME')
        self.saves = {p.name: p.read_bytes() for p in (self.game / 'SAVEGAME').iterdir()}
        self.tool = self.work / 'ASE3'
        self.patch_log = original.prepare_tool(tool_dir, self.tool, harness.SANDBOX_DLL)
        fake.routes.update({'': str(harness.REPO / 'web'), 'game/': str(self.game), 'ase3/': str(self.tool)})
        self.map_size = 480

    def map_of(self, level):
        return (self.tool / 'Maps' / f'{level:02d}.dat').read_bytes()

    def reset_game(self):
        """The saved games as they came (dated ten minutes ago), nothing explored."""
        old = time.time() - 600
        for p in (self.game / 'SAVEGAME').iterdir():
            if p.name not in self.saves:
                p.unlink()
        for name, data in self.saves.items():
            p = self.game / 'SAVEGAME' / name
            p.write_bytes(data)
            os.utime(p, (old, old))
        if (self.game / 'ASE').exists():
            shutil.rmtree(self.game / 'ASE')

    def write_save(self, slot, name, age, x=None, y=None, d=None, level=None):
        """SAVEGAME\\ITEMS_<slot>.BIN: a copy of slot 1's with another location, its
        name in SAVEGAME.DIR, dated age seconds ago."""
        data = bytearray(self.saves['ITEMS_01.BIN'])
        for off, v in ((252, x), (253, y), (254, d), (255, level)):
            if v is not None:
                data[off] = v
        p = self.game / 'SAVEGAME' / f'ITEMS_{slot:02d}.BIN'
        p.write_bytes(bytes(data))
        d_ = self.game / 'SAVEGAME' / 'SAVEGAME.DIR'
        lines = d_.read_bytes().split(b'\r\n')
        lines[slot - 1] = name.encode('latin-1')
        d_.write_bytes(b'\r\n'.join(lines))
        self.date_save(slot, age)

    def date_save(self, slot, age=0):
        """The game saved into slot age seconds ago (the file's date)."""
        t = time.time() - age
        os.utime(self.game / 'SAVEGAME' / f'ITEMS_{slot:02d}.BIN', (t, t))

    def write_explored(self, slot, cells):
        """ASE\\Explored_<slot>.dat with {level: [(x, y), ...]} explored."""
        data = bytearray(14 * 1024)
        for lv, xy in cells.items():
            for x, y in xy:
                data[(lv - 1) * 1024 + x * 32 + y] = 1
        (self.game / 'ASE').mkdir(exist_ok=True)
        (self.game / 'ASE' / f'Explored_{slot:02d}.dat').write_bytes(bytes(data))

    def state(self, **kw):
        return State(self, **kw)


def explored_runs(data):
    """An explored file as 'level: column x, rows y0-y1' runs (nothing explored: [])."""
    out = []
    if not data:
        return out
    for lv in range(14):
        for x in range(32):
            col = data[lv * 1024 + x * 32:lv * 1024 + x * 32 + 32]
            y = 0
            while y < 32:
                if col[y]:
                    y0 = y
                    while y < 32 and col[y]:
                        y += 1
                    out.append(f'{lv + 1:02d}: x {x:02d}, y {y0:02d}-{y - 1:02d}')
                else:
                    y += 1
    return out


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
        """The answers to the next dialogs ('Yes', 'No', 'OK')."""
        self.pending += answers

    def save_file(self, slot):
        return (self.run.game / 'SAVEGAME' / f'ITEMS_{slot:02d}.BIN').read_bytes()


def pstring(s, n):
    b = s.encode('mbcs')[:n]
    return bytes([len(b)]) + b.ljust(n, b'\0')


class Original(Common):
    which = 'original'

    def start(self, search=True):
        r = self.run
        rec = bytearray(0x1A8)
        rec[0:201] = pstring(str(r.game) + '\\', 200)   # the folder ends in a backslash, as ASE3 keeps it
        rec[0xC9:0xC9 + 201] = pstring(self.fake.title, 200)
        struct.pack_into('<iiiii', rec, 0x194, 0x1000000, 0x1000000 + MEM, r.map_size, 0, 0)
        (r.tool / 'ASE3.dat').write_bytes(bytes(rec))
        self.t = original.Tool(r.tool / 'ASE3.exe', [], self.fake, r.work)
        self.start_form = self.t.find('TStart_Form', timeout=15)
        if not self.start_form:
            raise RuntimeError('ASE3 did not open its start window')
        self.t.main = self.start_form
        self.t.place(self.start_form, -2540, 20)
        time.sleep(1.0)
        if search:
            self.search()

    def search(self):
        self.t.click_button(self.t.control('TButton', h=self.start_form, text='Search'))
        self.map_form = self.t.find('TMap_Form', timeout=30)
        if not self.map_form:
            raise RuntimeError('ASE3 did not find the game')
        self.t.main = self.map_form
        self.t.place(self.map_form, -2540 + 600, 40)
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
            return self.t.capture_texts(self.map_form)
        if name == 'preview':
            img = self.t.capture(self.start_form)
            x, y = PREVIEW_AT
            return img.crop((x, y, x + 480, y + 480)) if img else None
        raise KeyError(name)

    def size(self):
        l, t, r, b = original.rect(self.map_form, client=True)
        return [r - l, b - t]

    def title(self):
        return original.window_text(self.map_form)

    def saves(self):
        """The saved games list: [slot, name, level, date] a line, [] for an empty one."""
        lb = self.t.control('TListBox', h=self.start_form)
        out = []
        for line in self.t.list_items(lb):
            # "%2.2d  %-26.26s  %2.2d: %-22.22s  %s"
            out.append([line[0:2], line[4:30].rstrip(), line[32:58].rstrip(), line[60:].strip()] if line.strip() else [])
        return out

    def menu(self, *path):
        items = self.t.popup(self.map_form)
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
            out = []
            for c, _, en, ch, sub in items:
                cap, _, key = c.replace('&', '').partition('\t')
                out.append(['-' if c == '-' else cap, key, en, ch, walk(sub) if sub else None])
            return out
        return comparable_menu(walk(self.t.popup(self.map_form) or []))

    def move(self, x, y):
        self.t.mouse(self.map_form, x, y, 'move')
        time.sleep(0.3)

    def key(self, name):
        vk = KEYS[name][1] if name in KEYS else ord(name.upper())
        self.t.key(self.map_form, vk)
        time.sleep(0.4)

    def dialogs(self, wait=2.0):
        """What the message dialogs shown since the last call said; each answered
        with the next answer given (else the first button)."""
        out = []
        end = time.monotonic() + (wait if self.pending else 0.2)
        while time.monotonic() < end:
            h = next((w for w in self.t.windows() if original.class_name(w) == 'TMessageForm'), None)
            if not h:
                time.sleep(0.1)
                continue
            self.t.capture(h)   # painted (into the capture, which the log follows)
            time.sleep(0.2)
            want = '%08x' % h
            texts = []
            for line in self.t.log():
                p = line.split(' ', 2)
                if len(p) == 3 and p[1] in ('text', 'drawtext'):
                    head, text = p[2].split('|', 1)
                    if head.split(' ')[3].lower().rjust(8, '0') == want and original.unescape(text) not in texts:
                        texts.append(original.unescape(text))
            out.append(' '.join(texts))
            ans = self.pending.pop(0) if self.pending else None
            buttons = [c for c in self.t.controls(h) if c[0] == 'TButton']
            pick = next((c for c in buttons if c[2].replace('&', '') == ans), buttons[0] if buttons else None)
            if pick:
                self.t.click_button(pick[1])
            for _ in range(30):
                if not original.user32.IsWindow(h) or not original.user32.IsWindowVisible(h):
                    break
                time.sleep(0.1)
            end = time.monotonic() + (wait if self.pending else 0.3)
        return out

    def explored_file(self, slot):
        p = self.run.game / 'ASE' / f'Explored_{slot:02d}.dat'
        return p.read_bytes() if p.exists() else None

    # ---- the start form ------------------------------------------------------------
    def to_start(self):
        """The map window closed: the start form is back."""
        if getattr(self, 'map_form', None) and original.user32.IsWindowVisible(self.map_form):
            original.user32.PostMessageW(self.map_form, original.WM_CLOSE, 0, 0)
            time.sleep(1.0)
        self.t.main = self.start_form

    def button(self, text):
        h = next((c[1] for c in self.t.controls(self.start_form) if c[0] in ('TButton', 'TCheckBox')
                  and c[2].replace('&', '') == text), None)
        if not h:
            raise RuntimeError(f'no button {text!r}')
        self.t.click_button(h)
        time.sleep(0.6)

    def edit_at(self, at):
        for cls, h, _, r in self.t.controls(self.start_form):
            if cls == 'TEdit':
                p = wintypes.POINT(r[0], r[1])
                original.user32.ScreenToClient(self.start_form, original.ctypes.byref(p))
                if abs(p.x - at[0]) <= 3 and abs(p.y - at[1]) <= 3:
                    return h
        raise RuntimeError(f'no edit at {at}')

    def pick(self, slot):
        lb = self.t.control('TListBox', h=self.start_form)
        self.t.select(lb, slot - 1)
        time.sleep(0.8)

    def location(self):
        combo = self.t.control('TComboBox', h=self.start_form)
        i = self.t.list_selection(combo)
        return [i + 1 if i >= 0 else 0, original.window_text(self.edit_at(X_EDIT_AT)),
                original.window_text(self.edit_at(Y_EDIT_AT))]

    def set_location(self, level=None, x=None, y=None):
        if level is not None:
            self.t.select(self.t.control('TComboBox', h=self.start_form), level - 1)
            time.sleep(0.5)
        for at, v in ((X_EDIT_AT, x), (Y_EDIT_AT, y)):
            if v is not None:
                self.t.set_text(self.edit_at(at), str(v))
                time.sleep(0.2)

    def preview_click(self, x, y):
        self.t.mouse(self.start_form, PREVIEW_AT[0] + x, PREVIEW_AT[1] + y, 'left')
        time.sleep(0.6)

    # ---- the character editor ---------------------------------------------------------
    def editor(self, file_slot=None):
        """The character editor: from the map's menu, or for a saved game."""
        if file_slot:
            self.pick(file_slot)
            self.button('Edit characters in save file')
        else:
            self.menu('Character editor')
        self.ed = self.t.find('TEditor_Form', timeout=20)
        if not self.ed:
            raise RuntimeError('no editor')
        time.sleep(1.0)
        self.edc = {}
        for cls, h, text, r in self.t.controls(self.ed, visible=False):
            parent = original.user32.GetParent(h)
            p = wintypes.POINT(r[0], r[1])
            original.user32.ScreenToClient(parent, original.ctypes.byref(p))
            group = original.window_text(parent).strip() if parent != self.ed else ''
            name = EDITOR_CONTROLS.get((group, cls, p.x, p.y)) or (cls == 'TButton' and f'{group} {text}'.strip())
            if name:
                self.edc[name] = h

    def characters(self):
        return self.t.list_items(self.edc['characters'])

    def character(self, i):
        self.t.select(self.edc['characters'], i)
        time.sleep(0.6)
        out = {k: original.window_text(self.edc[k]) for k in STAT_FIELDS}
        spells = []
        for kind in ('mage', 'cleric'):
            for line in self.t.list_items(self.edc[kind]):   # "%s%-27.27s  %s", "%d  " or "   " first
                spells.append([kind, line[0:3].strip(), line[3:30].rstrip(), line[32:].strip()])
        out['spells'] = spells
        lb = self.edc['equipment']
        out['equipment'] = [[line[0:12].rstrip(), line[14:18].strip(), line[20:]] for line in self.t.list_items(lb)] \
            if original.user32.IsWindowEnabled(lb) else []
        return out

    def item_list(self):
        return self.t.list_items(self.edc['items'])

    def set_field(self, name, value):
        self.t.set_text(self.edc[name], str(value))
        time.sleep(0.3)

    def ed_button(self, name):
        self.t.click_button(self.edc[name])
        time.sleep(0.8)

    def spell_step(self, kind, row, dv):
        self.t.select(self.edc[kind], row)   # ItemIndex only matters
        time.sleep(0.2)
        self.ed_button(f'{"Mage" if kind == "mage" else "Cleric"} spells {"+" if dv > 0 else "-"}')

    def set_item(self, slot_row, item_row):
        self.t.select(self.edc['equipment'], slot_row)
        self.t.select(self.edc['items'], item_row)
        time.sleep(0.3)
        self.ed_button('Equipment Set item')

    def clear_item(self, slot_row):
        self.t.select(self.edc['equipment'], slot_row)
        time.sleep(0.3)
        self.ed_button('Equipment Clear item')

    def finish(self):
        if hasattr(self, 't'):
            self.t.close()


# the editor's controls by (group box, class, place in it), from its form
EDITOR_CONTROLS = {
    ('', 'TListBox', 16, 16): 'characters', ('', 'TButton', 16, 200): 'apply',
    ('Stats', 'TComboBox', 88, 24): 'race', ('Stats', 'TComboBox', 88, 48): 'class',
    ('Stats', 'TComboBox', 88, 72): 'alignment', ('Stats', 'TEdit', 88, 96): 'portrait',
    ('Stats', 'TEdit', 88, 120): 'hp', ('Stats', 'TEdit', 144, 120): 'hp max', ('Stats', 'TEdit', 88, 144): 'food',
    ('Stats', 'TEdit', 88, 176): 'STR', ('Stats', 'TEdit', 184, 176): 'STR 18/**', ('Stats', 'TEdit', 88, 200): 'INT',
    ('Stats', 'TEdit', 88, 224): 'WIS', ('Stats', 'TEdit', 88, 248): 'DEX', ('Stats', 'TEdit', 88, 272): 'CON',
    ('Stats', 'TEdit', 88, 296): 'CHA', ('Stats', 'TEdit', 88, 328): 'level 1', ('Stats', 'TEdit', 136, 328): 'XP 1',
    ('Stats', 'TEdit', 88, 352): 'level 2', ('Stats', 'TEdit', 136, 352): 'XP 2', ('Stats', 'TEdit', 88, 376): 'level 3',
    ('Stats', 'TEdit', 136, 376): 'XP 3',
    ('Mage spells', 'TListBox', 16, 24): 'mage', ('Cleric spells', 'TListBox', 16, 24): 'cleric',
    ('Equipment', 'TListBox', 16, 24): 'equipment', ('Equipment', 'TListBox', 432, 24): 'items',
    ('Equipment', 'TEdit', 232, 0): 'ammunition', ('Equipment', 'TEdit', 672, 416): 'filter',
}
STAT_FIELDS = ['race', 'class', 'alignment', 'portrait', 'hp', 'hp max', 'food', 'STR', 'STR 18/**', 'INT', 'WIS', 'DEX',
               'CON', 'CHA', 'level 1', 'XP 1', 'level 2', 'XP 2', 'level 3', 'XP 3']


# Menu items that are one side's own: the original's windows (docking, its empty item)
# and the page's own additions (README: what a browser can and can't do)
MENU_OWN = {'Toggle docking', '', 'Fit to window', 'Open in its own window', 'Add a note', 'Peek level', 'Show',
            'Saved games…', 'Rule book', 'Clue book', 'Backup save game', 'Export map', 'ASE / ASE3 data folder…',
            'Game folder…', 'Debug', 'Search again'}


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

EXPLORED_FILE = '''(async slot => {
  let any = false;
  const out = new Uint8Array(14 * 1024);
  for (let lv = 1; lv <= 14; lv++) {
    const b = await DB.get('kv', `exp:3:${slot}:${lv}`);
    if (!b) continue;
    any = true;
    const m = new Uint8Array(b);
    for (let i = 0; i < 1024; i++) if (m[i]) out[(lv - 1) * 1024 + ((i & 31) << 5 | i >> 5)] = 1;
  }
  if (!any) return null;
  let s = '';
  for (const c of out) s += String.fromCharCode(c);
  return btoa(s);
})(%d)'''

# the page's notice that it offered a download instead of writing into the folder
DOWNLOAD_NOTE = "can't be written from here"


class Page(Common):
    which = 'page'

    def start(self, search=True):
        b = self.b = self.run.browser
        b.goto(f'http://127.0.0.1:{self.fake.port}/{self.fake.BLANK}')
        b.js(PAGE_SETUP % harness.json.dumps({'size3': self.run.map_size}))
        b.dialogs.clear()
        for p in b.downloads.iterdir():
            p.unlink()
        b.goto(f'http://127.0.0.1:{self.fake.port}/ase.html?ase3data=ase3/&gamedata=game/')
        if search:
            b.wait('Game.coords', 30)
            self.settle(1.0)
        else:
            b.wait('Files.has()', 30)
            time.sleep(1.0)

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
        if name == 'preview':
            return self.b.canvas('#saves3 canvas')
        raise KeyError(name)

    def size(self):
        return self.b.js("(c => [c.width, c.height])(document.querySelector('#map'))")

    def title(self):
        return self.b.js("document.querySelector('#title').textContent")

    def saves(self):
        self.open_saves()
        return self.b.js('''[...document.querySelectorAll('#saves3 table.list tr')].map(tr =>
          [...tr.children].map(td => td.textContent.trimEnd())).map(r => r.some(Boolean) ? r : [])''')

    def open_saves(self):
        if not self.b.js("!!document.getElementById('saves3')"):
            self.b.js('Saves3.open()')
            time.sleep(0.6)

    def menu(self, *path):
        self.answer_next()
        r = self.b.js('''(path => {
          let items = Menu.items(), it = null;
          for (const p of path) {
            it = items.find(i => i !== '-' && i.label.replace(/\\u2026$/, '') === p);
            if (!it) return 'missing';
            items = it.sub || [];
          }
          if (it.disabled) return 'disabled';
          setTimeout(() => it.act(), 0);   // dialogs it opens must not hold up this call
          return 'ok';
        })(%s)''' % harness.json.dumps(list(path)))
        if r == 'missing':
            raise RuntimeError(f'no menu item {path}')
        time.sleep(0.4)
        return r

    def menu_tree(self):
        return comparable_menu(self.b.js('''(() => { const walk = items => items.map(i => i === '-' ? ['-', '', false, false, null]
          : [i.label, i.key || '', !i.disabled, !!i.checked, i.sub ? walk(i.sub) : null]); return walk(Menu.items()); })()'''))

    def at(self, x, y, sel='#map'):
        ox, oy = self.b.js(f"(r => [r.left, r.top])(document.querySelector('{sel}').getBoundingClientRect())")
        return math.ceil(ox + x), math.ceil(oy + y)

    def move(self, x, y):
        self.b.mouse(*self.at(x, y), 'move')
        time.sleep(0.3)

    def key(self, name):
        key, vk = KEYS[name] if name in KEYS else (name.lower(), ord(name.upper()))
        code = key if len(key) > 1 else f'Key{key.upper()}'
        self.answer_next()
        self.b.key(key, code, vk, text=key if len(key) == 1 else None)
        time.sleep(0.4)

    def answer_next(self):
        self.b.dialog_answers[:] = [a != 'No' for a in self.pending]

    def dialogs(self, wait=2.0):
        time.sleep(0.3 if not self.pending else 0.6)
        out = [m for t, m in self.b.dialogs if DOWNLOAD_NOTE not in (m or '')]
        self.b.dialogs.clear()
        self.pending.clear()
        self.b.dialog_answers.clear()
        return out

    def explored_file(self, slot):
        b64 = self.b.js(EXPLORED_FILE % slot)
        return base64.b64decode(b64) if b64 else None

    def downloaded(self, name, timeout=5.0):
        """The file the page offered as a download (the newest of that name: the browser
        numbers repeated ones)."""
        stem, dot, ext = name.rpartition('.')
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = sorted((p for p in self.b.downloads.iterdir() if p.name.startswith(stem) and p.name.endswith(dot + ext)),
                           key=lambda p: p.stat().st_mtime)
            if found and not list(self.b.downloads.glob('*.crdownload')):
                return found[-1].read_bytes()
            time.sleep(0.2)
        return None

    # ---- the saved games dialog -------------------------------------------------------
    def to_start(self):
        self.open_saves()

    def button(self, text):
        self.answer_next()
        r = self.b.js('''(t => { const b = [...document.querySelectorAll('#saves3 button, #saves3 label')]
          .find(e => e.textContent.trim() === t); if (!b) return false;
          const box = b.querySelector && b.querySelector('input[type=checkbox]');
          setTimeout(() => (box || b).click(), 0); return true; })(%s)''' % harness.json.dumps(text))
        if not r:
            raise RuntimeError(f'no button {text!r}')
        time.sleep(0.8)

    def pick(self, slot):
        self.open_saves()
        self.b.js(f"document.querySelectorAll('#saves3 table.list tr')[{slot - 1}].click()")
        time.sleep(0.8)

    def location(self):
        return self.b.js('''(() => { const d = document.getElementById('saves3'); const [x, y] = d.querySelectorAll('input[type=number]');
          return [+d.querySelector('select').value, x.value, y.value]; })()''')

    def set_location(self, level=None, x=None, y=None):
        self.b.js('''((lv, x, y) => { const d = document.getElementById('saves3'), s = d.querySelector('select');
          const [xi, yi] = d.querySelectorAll('input[type=number]');
          if (lv !== null) { s.value = lv; s.dispatchEvent(new Event('change')); }
          if (x !== null) { xi.value = x; xi.dispatchEvent(new Event('input')); }
          if (y !== null) { yi.value = y; yi.dispatchEvent(new Event('input')); } })(%s, %s, %s)'''
                  % tuple(harness.json.dumps(v) for v in (level, x, y)))
        time.sleep(0.6)

    def preview_click(self, x, y):
        self.b.mouse(*self.at(x, y, '#saves3 canvas'), 'left')
        time.sleep(0.6)

    # ---- the character editor ---------------------------------------------------------
    def editor(self, file_slot=None):
        if file_slot:
            self.pick(file_slot)
            self.button('Edit characters in save file')
        else:
            self.menu('Character editor')
        self.b.wait("!!document.querySelector('#editor3 .chars button')", 20)
        time.sleep(0.5)

    def characters(self):
        return self.b.js("[...document.querySelectorAll('#editor3 .chars button')].slice(0, -2).map(b => b.textContent)")

    def character(self, i):
        self.b.js(f"document.querySelectorAll('#editor3 .chars button')[{i}].click()")
        time.sleep(0.5)
        return self.b.js(PAGE_CHARACTER)

    def item_list(self):
        return self.b.js("[...document.querySelectorAll('#editor3 select[size] option')].map(o => o.textContent)")

    def set_field(self, name, value):
        k = PAGE_NUMBERS.index(name)
        self.b.js(f'''(i => {{ i.value = {harness.json.dumps(str(value))}; i.dispatchEvent(new Event('change')); }})
          ([...document.querySelectorAll('#editor3 fieldset')][0].querySelectorAll('input')[{k}])''')
        time.sleep(0.2)

    def ed_button(self, name):
        text = {'apply': 'Apply changes'}.get(name, name)
        self.answer_next()
        self.b.js(f'''setTimeout(() => [...document.querySelectorAll('#editor3 button')].find(b => b.textContent === {harness.json.dumps(text)})
          .click(), 0)''')
        time.sleep(0.8)

    def spell_step(self, kind, row, dv):
        legend = 'Mage spells' if kind == 'mage' else 'Cleric spells'
        self.b.js(f'''[...document.querySelectorAll('#editor3 fieldset')].find(f => f.querySelector('legend').textContent.trim() ===
          {harness.json.dumps(legend)}).querySelectorAll('tr')[{row}].querySelectorAll('button')[{0 if dv > 0 else 1}].click()''')
        time.sleep(0.6)

    def set_item(self, slot_row, item_row):
        self.b.js(f'''(() => {{ const f = [...document.querySelectorAll('#editor3 fieldset')].find(f => f.querySelector('legend')
          .textContent.trim() === 'Equipment'); f.querySelectorAll('table tr')[{slot_row}].click();
          f.querySelector('select').selectedIndex = {item_row}; }})()''')
        self.ed_button('Set item')

    def clear_item(self, slot_row):
        self.b.js(f'''[...document.querySelectorAll('#editor3 fieldset')].find(f => f.querySelector('legend').textContent.trim() ===
          'Equipment').querySelectorAll('table tr')[{slot_row}].click()''')
        self.ed_button('Clear item')

    def finish(self):
        # off the page: it would go on reading (and writing) the next session's game
        if hasattr(self, 'b'):
            self.b.goto(f'http://127.0.0.1:{self.fake.port}/{self.fake.BLANK}')


# the page's number fields in the editor's Stats, in order
PAGE_NUMBERS = ['portrait', 'hp', 'hp max', 'food', 'STR', 'STR 18/**', 'INT', 'WIS', 'DEX', 'CON', 'CHA', 'level 1', 'XP 1',
                'level 2', 'XP 2', 'level 3', 'XP 3']
PAGE_CHARACTER = '''(() => {
  const d = document.getElementById('editor3');
  const fs = t => [...d.querySelectorAll('fieldset')].find(f => f.querySelector('legend').textContent.trim() === t);
  const stats = fs('Stats'), sel = [...stats.querySelectorAll('select')].map(s => s.selectedOptions[0]?.textContent || '');
  const nums = [...stats.querySelectorAll('input')].map(i => i.value);
  const out = { race: sel[0], class: sel[1], alignment: sel[2] };
  %s.forEach((n, k) => out[n] = nums[k]);
  out.spells = [];
  for (const [kind, t] of [['mage', 'Mage spells'], ['cleric', 'Cleric spells']])
    for (const tr of fs(t).querySelectorAll('tr'))
      out.spells.push([kind, tr.children[0].textContent, tr.children[1].textContent, tr.querySelector('input').value]);
  out.equipment = [...fs('Equipment').querySelectorAll('table tr')].map(tr => [...tr.children].map(td => td.textContent));
  return out;
})()''' % harness.json.dumps(PAGE_NUMBERS)


# ---- the sessions -------------------------------------------------------------------

def see(s):
    s.observe('map', s.view('map'))
    s.observe('title', s.title())


def search_map(s):
    """The newest save's level found; the party moves; another level."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    see(s)
    for dx, dy in ((1, 0), (1, 1), (0, 2)):
        x, y = st.x + dx, st.y + dy
        if 0 <= x < 32 and 0 <= y < 32 and st.map[y * 32 + x] == 0xFF:
            s.poke(r.state(x=x, y=y))
            s.settle()
    see(s)
    for d in (1, 2, 3):
        s.poke(r.state(d=d))
        s.settle(0.5)
        see(s)


def saves(s):
    """The saved games list: names, levels, dates, unused slots; a slot with a file but
    no name, a name without a file, a level outside 1-14."""
    r = s.run
    r.reset_game()
    r.write_save(3, 'Before the tomb', 300, x=5, y=6, level=1)
    r.write_save(5, '__________________________', 200, x=7, y=8, level=20)
    d_ = r.game / 'SAVEGAME' / 'SAVEGAME.DIR'
    lines = d_.read_bytes().split(b'\r\n')
    lines[6] = b'A name without a file'
    d_.write_bytes(b'\r\n'.join(lines))
    s.set(r.state())
    s.start(search=False)
    s.observe('saves', s.saves())


def menu_states(s):
    """The map's popup menu."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    s.observe('menu', s.menu_tree())


def hover(s):
    """The mouse's cell: framed and in the title for 2 seconds."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    s.move(st.x * 15 + 7, st.y * 15 + 3)
    see(s)
    s.move(0 * 15 + 2, 0 * 15 + 14)   # the corner cell: the frame goes past the map's edge
    see(s)
    s.move(20 * 15 + 14, 31 * 15 + 14)
    see(s)
    s.wait(2.8)
    see(s)


def sizes(s):
    """PgUp / PgDn: the window 30 pixels larger or smaller, the map in its middle."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    for k in ('PgUp', 'PgUp', 'PgDn', 'PgDn', 'PgDn'):
        s.key(k)
        s.settle(0.6)
        s.observe('size', s.size())
        s.observe('map', s.view('map'))
    s.key('PgUp')
    s.key('PgUp')
    s.settle(0.6)
    s.move(5 * 16 + 30 + 3, 6 * 16 + 30 + 3)   # 540 pixels: cells of 16, 14 pixels around them
    see(s)


def teleport(s):
    """Teleport here: the mouse's cell (open or a wall), from the menu and by key."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    x, y = st.first(near=(st.x + 5, st.y))
    s.move(x * 15 + 5, y * 15 + 5)
    s.menu('Teleport here')
    s.settle()
    s.observe('memory', s.memory_changes())
    see(s)
    x, y = st.first(open_=False, near=(st.x, st.y + 4))
    s.move(x * 15 + 5, y * 15 + 5)
    s.wait(2.5)   # the frame is gone, the cell still the mouse's
    s.key('T')
    s.settle()
    s.observe('memory', s.memory_changes())
    see(s)


def explore_menu(s):
    """Explore level / Unexplore level, with ASE3's question answered No and Yes."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
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
    s.answer('Yes')
    s.key('X')
    s.observe('dialogs', s.dialogs())
    s.settle()
    see(s)


def explored_files(s):
    """The newest save's explored maps are loaded; when the game saves, the explored
    maps go to the slot it saved in."""
    r = s.run
    r.reset_game()
    st = r.state()
    r.date_save(1, 60)
    r.write_save(2, 'The second save', 30, x=st.x, y=st.y, level=st.level)   # the newest
    r.write_explored(1, {st.level: [(x, 2) for x in range(3, 20)]})
    r.write_explored(2, {st.level: [(x, 4) for x in range(3, 20)] + [(10, y) for y in range(5, 30)],
                         4: [(1, 1), (2, 2)]})
    s.set(st)
    s.start()
    see(s)
    for x, y in st.open_cells(4):
        s.poke(r.state(x=x, y=y))
        s.settle(0.6)
    see(s)
    r.date_save(1)   # the game saves into slot 1
    s.wait(3.0)
    s.observe('explored 1', explored_runs(s.explored_file(1)))
    s.observe('explored 2', explored_runs(s.explored_file(2)))


def explored_error(s):
    """The party's location goes wrong: ASE3 writes the explored maps to the newest save's slot."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    for x, y in st.open_cells(3):
        s.poke(r.state(x=x, y=y))
        s.settle(0.6)
    s.answer('Yes')
    s.menu('Explore level')
    s.dialogs()
    s.settle()
    s.poke(r.state(x=0x40))
    s.wait(2.5)
    s.observe('explored 1', explored_runs(s.explored_file(1)))


def level_change(s):
    """The party goes to another level (its map where the last one was)."""
    r = s.run
    r.reset_game()
    st = r.state()
    s.set(st)
    s.start()
    st4 = r.state(level=4)
    x, y = st4.first(near=(10, 10))
    s.poke(r.state(level=4, x=x, y=y))
    s.settle(2.0)
    see(s)
    s.poke(r.state(level=4, x=x, y=y, d=2))
    s.settle(1.0)
    see(s)


def preview(s):
    """The saved games' preview: the newest save, another one, fully explored, another
    level, a click on the map; the location fields."""
    r = s.run
    r.reset_game()
    st = r.state()
    r.date_save(1, 60)
    r.write_save(2, 'Forest walk', 30, x=12, y=9, d=1, level=4)
    r.write_explored(1, {st.level: [(x, 6) for x in range(2, 25)]})
    r.write_explored(2, {4: [(x, y) for x in range(4, 20) for y in range(5, 14)]})
    s.set(st)
    s.start(search=False)
    s.to_start()
    s.observe('preview', s.view('preview'))
    s.observe('location', s.location())
    s.pick(1)
    s.observe('preview', s.view('preview'))
    s.observe('location', s.location())
    s.button('Show preview map as fully explored')
    s.observe('preview', s.view('preview'))
    s.button('Show preview map as fully explored')
    s.set_location(level=5)
    s.observe('preview', s.view('preview'))
    s.set_location(level=3)
    s.preview_click(20 * 15 + 4, 7 * 15 + 9)
    s.observe('preview', s.view('preview'))
    s.observe('location', s.location())
    s.set_location(x=3, y=4)   # typed: the preview stays as it is
    s.observe('preview', s.view('preview'))


def location_apply(s):
    """Apply to save: the level and the coordinates into the saved game."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start(search=False)
    s.to_start()
    s.pick(1)
    s.set_location(level=4, x=10, y=12)
    before = s.save_file(1)
    s.answer('OK')
    s.button('Apply to save')
    s.observe('save file', file_diff(before, s.downloaded('ITEMS_01.BIN') if s.which == 'page' else s.save_file(1)))
    s.dialogs()


def file_diff(before, after):
    """A file's changed bytes."""
    if after is None:
        return ['not written']
    return [f'{i:X}: {a:02X} -> {b:02X}' for i, (a, b) in enumerate(zip(before, after)) if a != b] + \
        ([f'size {len(before)} -> {len(after)}'] if len(after) != len(before) else [])


def clear_explored(s):
    """Clear explored: the question, the slot's explored maps emptied."""
    r = s.run
    r.reset_game()
    st = r.state()
    r.write_explored(1, {st.level: [(x, 6) for x in range(2, 25)], 5: [(3, 3)]})
    s.set(st)
    s.start(search=False)
    s.to_start()
    s.pick(1)
    s.answer('No')
    s.button('Clear explored')
    s.observe('dialogs', s.dialogs())
    s.observe('explored 1', explored_runs(s.explored_file(1)))
    s.answer('Yes')
    s.button('Clear explored')
    s.observe('dialogs', s.dialogs())
    s.observe('explored 1', explored_runs(s.explored_file(1)))
    s.observe('preview', s.view('preview'))


def editor_memory(s):
    """The character editor on the game's memory: each character as it shows it; stats
    changed and applied; spells one up and down (written at once)."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start()
    s.editor()
    names = s.characters()
    s.observe('characters', names)
    for i in range(len(names)):
        s.observe(f'character {i}', s.character(i))
    s.character(0)
    for k, v in (('STR', 18), ('hp', 50), ('XP 1', 123456), ('WIS', 3)):
        s.set_field(k, v)
    s.ed_button('apply')
    s.observe('memory', s.memory_changes())
    s.character(1)
    s.spell_step('cleric', 0, +1)
    s.spell_step('cleric', 1, +1)   # "-": one more is 0
    s.spell_step('cleric', 2, -1)
    s.spell_step('mage', 0, -1)     # "-": nothing less
    s.observe('memory', s.memory_changes())
    s.observe('character 1', s.character(1))


def editor_file(s):
    """The character editor on a saved game: all ten characters with their equipment;
    an item set and one cleared (written at once), a stat applied."""
    r = s.run
    r.reset_game()
    s.set(r.state())
    s.start(search=False)
    s.to_start()
    s.editor(file_slot=1)
    names = s.characters()
    s.observe('characters', names)
    for i in range(len(names)):
        s.observe(f'character {i}', s.character(i))
    s.observe('items', s.item_list())
    before = s.save_file(1)
    s.character(0)
    s.set_item(0, 5)
    s.clear_item(1)
    s.spell_step('cleric', 0, +1)
    s.set_field('STR', 18)
    s.answer('OK')
    s.ed_button('apply')
    s.observe('save file', file_diff(before, s.downloaded('ITEMS_01.BIN') if s.which == 'page' else s.save_file(1)))
    s.dialogs()


SESSIONS = {f.__name__: f for f in (search_map, saves, menu_states, hover, sizes, teleport, explore_menu,
                                     explored_files, explored_error, level_change, preview, location_apply,
                                     clear_explored, editor_memory, editor_file)}

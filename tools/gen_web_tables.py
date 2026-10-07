#!/usr/bin/env python3
"""Regenerates the tables built into the companion pages from the tools' own
files and writes them into the pages, between their /*@NAME@*/ and
/*@/NAME@*/ lines.

  web/gbc.html          GAME_INFO  per game: GBC's folder name, character record
                                   size, spell block and effect record sizes,
                                   the program offsets and the two ID patterns
                                   (Game.dat 608, 610, 68C, 690-6CC, 6D0, 7D0)
                        FIELDS     character record fields [offset, length] by
                                   GBC's field names (Game.dat's table at 8B8)
                        FIELD_ALIASES  the page's short names for some of them
                        VALUES     race, gender, class, alignment, status,
                                   knight, god, robe and flag names (from
                                   Resources\\Character file formats)
  web/ultimapper5.html  SPELLS     [name, circle, reagent mask, effect] in
                                   SAVED.GAM order: circles and reagents from
                                   Ultima5Redux's MagicDefinitions.json, the
                                   effects as Ultimapper_5.exe names them
                        U5_TABLES  Ultimapper_5.exe's own tables: the colour of
                                   each tile on the large maps, which combat
                                   tiles can be walked on, quickfight's weapon
                                   preferences, the HUD's item names and the
                                   colours of its bars

  every page            GDI_FONTS  GDI's ascents, descents and character widths of
                                   the fonts the original draws text in (--fonts:
                                   measured with the fonts of the Windows it runs on)
                        GDI_ELLIPSES the circles GDI's Ellipse draws (--fonts too)
                        GDI_TRIANGLES GBC's party triangle with a 2-pixel pen (--fonts too)
                        WIN_SORT   Windows' sort weights of the ASCII characters (--fonts too)

usage: gen_web_tables.py [--check] [--gbc FOLDER] [--ultimapper EXE [--magic JSON]] [--fonts]

--gbc is Gold Box Companion 2.65's folder, with Game.dat patched by patch.py
(the 1st IDs of five games are cut there). --check only reports the tables
that would change.
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

# the repo's web/, or the release zip's (the script is in source/tools there)
HERE = Path(__file__).resolve().parent
WEB = next((d for d in (HERE.parent / 'web', HERE.parent.parent / 'web') if (d / 'gbc.html').is_file()),
           HERE.parent / 'web')
ROW = re.compile(r'^\s+([0-9A-F]{3})(?:\s*-\s*([0-9A-F]{3}))?\s+\d+(?:\s*-\s*\d+)?\s+(\d+)\s+(.+?)\s*$')
FIELD_KEYS = {
    'name length': 'nameLen', 'name': 'name', 'str current': 'str', 'int current': 'int', 'wis current': 'wis',
    'dex current': 'dex', 'con current': 'con', 'cha current': 'cha', 'str exc current': 'strExc',
    'str original': 'strO', 'int original': 'intO', 'wis original': 'wisO', 'dex original': 'dexO',
    'con original': 'conO', 'cha original': 'chaO', 'str exc original': 'strExcO', 'tch current': 'tch',
    'race': 'race', 'class': 'cls', 'gender': 'gender', 'alignment': 'align', 'age': 'age',
    'hit points maximum': 'hpMax', 'hit points current': 'hp', 'hit points rolled': 'hpRolled',
    'experience': 'xp', 'status': 'status', 'enabled': 'enabled', 'npc': 'npc', 'hostile': 'hostile',
    'effects address': 'effects', 'items address': 'items', 'next character address': 'next',
    'combat address': 'combat', 'number of items': 'nItems', 'drained levels': 'drained',
    'drained hps': 'drainedHp', 'ac current': 'ac', 'thac0 current': 'thac0', 'ac base': 'acBase',
    'thac0 base': 'thac0Base', 'movement current': 'move', 'movement base': 'moveBase', 'quickfight': 'quickfight',
    'level cleric': 'lvCleric', 'level druid': 'lvDruid', 'level fighter': 'lvFighter', 'level paladin': 'lvPaladin',
    'level ranger': 'lvRanger', 'level mage': 'lvMage', 'level thief': 'lvThief', 'level monk': 'lvMonk',
    'level knight': 'lvKnight', 'icon head': 'iconHead', 'icon body': 'iconBody', 'icon size': 'iconSize',
    'icon': 'icon', 'icon dimensions': 'iconDim', 'order number': 'order', 'encumbrance': 'enc',
    'save 1': 'save1', 'save 2': 'save2', 'save 3': 'save3', 'save 4': 'save4', 'save 5': 'save5',
    'coins platinum': 'platinum', 'coins gold': 'gold', 'coins steel': 'steel', 'coins electrum': 'electrum',
    'coins silver': 'silver', 'coins copper': 'copper', 'coins bronze': 'bronze', 'gems': 'gems',
    'jewelry': 'jewelry', 'coins credit': 'credits', 'icon color1 body': 'icBody', 'icon color1 arm': 'icArm',
    'icon color1 leg': 'icLeg', 'icon color1 hair': 'icHair', 'icon color1 shield': 'icShield',
    'icon color1 weapon': 'icWeapon',
    'memorized spells': 'memSpells', 'spells address': 'spellsAddr', 'level highest 1': 'lvHighest',
}
# GBC's field names in its numbering (field 1 first), from GBC.exe
GBC_NAMES = [
    'next_character_address', 'effects_address', 'items_address', 'spells_address', 'combat_address', 'equipped_weapon_address',
    'equipped_shield_address', 'equipped_armor_address', 'equipped_gauntlets_address', 'equipped_helm_address', 'equipped_belt_address', 'equipped_robe_address',
    'equipped_cloak_address', 'equipped_boots_address', 'equipped_ring_1_address', 'equipped_ring_2_address', 'equipped_arrow_address', 'equipped_bolt_address',
    'hands_equipped', 'save_bonus', 'name_length', 'name', 'string_terminator', 'race',
    'gender', 'class', 'type', 'alignment', 'age', 'flags_1',
    'flags_2', 'str_original', 'int_original', 'wis_original', 'dex_original', 'con_original',
    'cha_original', 'tch_original', 'str_exc_original', 'str_current', 'int_current', 'wis_current',
    'dex_current', 'con_current', 'cha_current', 'tch_current', 'str_exc_current', 'modified',
    'hit_points_maximum', 'hit_points_current', 'hit_points_rolled', 'highest_hps', 'status', 'enabled',
    'save_1', 'save_2', 'save_3', 'save_4', 'save_5', 'save_6',
    'save_7', 'save_8', 'experience', 'highest_experience', 'xp_award', 'xp_bonus_per_hp',
    'able_to_train', 'level_cleric', 'level_druid', 'level_fighter', 'level_paladin', 'level_ranger',
    'level_mage', 'level_thief', 'level_monk', 'level_knight', 'former_level_cleric', 'former_level_druid',
    'former_level_fighter', 'former_level_paladin', 'former_level_ranger', 'former_level_mage', 'former_level_thief', 'former_level_monk',
    'former_level_knight', 'level_highest_1', 'level_highest_2', 'level_undead', 'highest_level_cleric', 'highest_level_druid',
    'highest_level_fighter', 'highest_level_paladin', 'highest_level_ranger', 'highest_level_mage', 'highest_level_thief', 'highest_level_monk',
    'highest_level_knight', 'drained_levels', 'drained_hps', 'knight', 'god', 'robe',
    'thief_1', 'thief_2', 'thief_3', 'thief_4', 'thief_5', 'thief_6',
    'thief_7', 'thief_8', 'jewelry', 'gems', 'coins_platinum', 'coins_gold',
    'coins_steel', 'coins_electrum', 'coins_silver', 'coins_bronze', 'coins_copper', 'coins_credit',
    'ac_base', 'ac_current', 'ac_behind', 'thac0_base', 'thac0_current', 'attacks',
    'attacks_2', 'unarmed_rolls', 'unarmed_dice', 'unarmed_modifier', 'unarmed_rolls_2', 'unarmed_dice_2',
    'unarmed_modifier_2', 'current_attacks', 'current_attacks_2', 'current_rolls', 'current_dice', 'current_modifier',
    'current_rolls_2', 'current_dice_2', 'current_modifier_2', 'attack_level', 'quickfight', 'movement_base',
    'movement_current', 'item_limits', 'number_of_items', 'encumbrance', 'npc', 'hostile',
    'monster_index', 'cure_disease_count', 'order_number', 'icon_dimensions', 'icon_head', 'icon_body',
    'icon_size', 'icon_color1_weapon', 'icon_color1_body', 'icon_color1_hair', 'icon_color1_shield', 'icon_color1_arm',
    'icon_color1_leg', 'icon_color2_weapon', 'icon_color2_body', 'icon_color2_face', 'icon_color2_shield', 'icon_color2_arm',
    'icon_color2_leg', 'icon', 'portrait_head', 'portrait_body', 'magic_resistance', 'cleric_spells_1',
    'cleric_spells_2', 'cleric_spells_3', 'cleric_spells_4', 'cleric_spells_5', 'cleric_spells_6', 'cleric_spells_7',
    'mage_spells_1', 'mage_spells_2', 'mage_spells_3', 'mage_spells_4', 'mage_spells_5', 'mage_spells_6',
    'mage_spells_7', 'mage_spells_8', 'mage_spells_9', 'druid_spells_1', 'druid_spells_2', 'druid_spells_3',
    'druid_spells_4', 'druid_spells_5', 'druid_spells_6', 'druid_spells_7', 'special_spells_1', 'known_spells',
    'memorized_spells',
]
REAGENT_KEYS = ['SulfurAsh', 'Ginseng', 'Garlic', 'SpiderSilk', 'BloodMoss', 'BlackPearl', 'NightShade', 'MandrakeRoot']


def compact(name, value):
    return f'const {name} = ' + json.dumps(value, separators=(',', ':')) + ';'


def game_info(gbc):
    """GBC's Game.dat headers, games in folder order (01. Pool of Radiance ...)."""
    out = []
    for d in sorted(p for p in (gbc / 'Games').iterdir() if re.match(r'\d\d\. ', p.name)):
        g = (d / 'Game.dat').read_bytes()
        sstr = lambda off: g[off + 1:off + 1 + g[off]].decode('latin-1')
        out.append({'dir': d.name, 'rec': struct.unpack_from('<i', g, 0x608)[0], 'ext': struct.unpack_from('<i', g, 0x610)[0],
                    'fx': struct.unpack_from('<i', g, 0x68C)[0], 'o': list(struct.unpack_from('<16i', g, 0x690)),
                    'id1': sstr(0x6D0), 'id2': sstr(0x7D0)})
    return compact('GAME_INFO', out)


def formats(gbc):
    """(game number, text) of Resources\\Character file formats\\NN. <game>.txt."""
    for p in sorted((gbc / 'Resources' / 'Character file formats').iterdir()):
        m = re.match(r'(\d\d)\. ', p.name)
        if m:
            yield int(m.group(1)), p.read_text('latin-1')


def fields(gbc):
    """[offset, length] by GBC's field name, from Game.dat's field table (field id
    at 8B8 + id * 18: int offset, byte length); a field beyond the record and its
    spell block is left out, as GBC can't read it (Treasures' movement current)."""
    out = {}
    for d in sorted(p for p in (gbc / 'Games').iterdir() if re.match(r'\d\d\. ', p.name)):
        g = (d / 'Game.dat').read_bytes()
        size = struct.unpack_from('<i', g, 0x608)[0] + struct.unpack_from('<i', g, 0x610)[0]
        f = {}
        for fid, name in enumerate(GBC_NAMES, 1):
            off, length = struct.unpack_from('<i', g, 0x8B8 + fid * 0x18)[0], g[0x8B8 + fid * 0x18 + 4]
            if length and off + length <= size:
                f[name] = [off, length]
        out[int(d.name[:2])] = f
    return compact('FIELDS', out)


def aliases(gbc):
    return compact('FIELD_ALIASES', {v: k.replace(' ', '_') for k, v in FIELD_KEYS.items()})


def values(gbc):
    out = {}
    for game, text in formats(gbc):
        g = {}
        for key, title in (('race', 'RACE'), ('gender', 'GENDER'), ('cls', 'CLASS'), ('align', 'ALIGNMENT'),
                           ('status', 'STATUS'), ('knight', 'KNIGHT'), ('god', 'GOD'), ('robe', 'ROBE'),
                           ('flags1', 'FLAGS 1'), ('flags2', 'FLAGS 2')):
            sec = re.search(title + r' VALUES:\n((?:\s+[0-9A-F]{2}: .*\n?)+)', text.replace('\r\n', '\n'))
            if sec:
                g[key] = {int(a, 16): b.strip() for a, b in re.findall(r'([0-9A-F]{2}): (.*)', sec.group(1))}
        out[game] = {k: [v.get(i, '') for i in range(max(v) + 1)] for k, v in g.items()}
    return compact('VALUES', out)


def spells(exe_path, magic_path):
    exe = Path(exe_path).read_bytes()
    # Ultimapper's own list: by circle, then alphabetically (An Nox, An Ylem, ...), then the effects
    start = exe.find(b'An Nox\0\0\xff\xff\xff\xff\x07\0\0\0An Ylem')
    if start < 0:
        sys.exit(f"{exe_path}: Ultimapper's spell list not found")
    strs = [m.group().decode() for m in re.finditer(rb'[ -~]{3,}', exe[start:start + 0x900])]
    effect = dict(zip(strs[:48], strs[48:96]))
    rows = []
    for v in json.loads(Path(magic_path).read_text()).values():
        if v['Spell'] in effect:   # MagicDefinitions ends with an extra "Nox"
            rows.append([v['Spell'], v['Circle'], sum(1 << i for i, r in enumerate(REAGENT_KEYS) if v[r]),
                         effect[v['Spell']]])
    if len(rows) != 48:
        sys.exit(f'{len(rows)} spells instead of 48')
    return 'const SPELLS = [\n  ' + ',\n  '.join(json.dumps(r) for r in rows) + '];'


def pe_offsets(exe):
    """file offset of a virtual address in a PE image"""
    pe = struct.unpack_from('<I', exe, 0x3c)[0]
    nsec = struct.unpack_from('<H', exe, pe + 6)[0]
    opt = pe + 24
    base = struct.unpack_from('<I', exe, opt + 28)[0]
    off = opt + struct.unpack_from('<H', exe, pe + 20)[0]
    secs = [struct.unpack_from('<IIII', exe, off + i * 40 + 8) for i in range(nsec)]   # vsize, va, rawsize, rawptr

    def fo(va):
        for vs, v, rs, ra in secs:
            if v <= va - base < v + vs:
                return ra + (va - base - v)
        sys.exit(f'address {va:#x} is not in the file')
    return fo


def u5_tables(exe_path):
    """Ultimapper's data, found by its contents: the 256 tile colours (Delphi $BBGGRR;
    tile 0 black, 1-3 water), then in the exe's order the combat walkability bytes,
    the extra titles, the inventory's groups and names, the HUD's 48 item names and
    the 45 (weapon, off-hand) pairs quickfight equips; the bar colours apart"""
    exe = Path(exe_path).read_bytes()
    fo = pe_offsets(exe)

    def u32(o):
        return struct.unpack_from('<I', exe, o)[0]

    def pstr(o):   # a pointer to a Delphi string
        f = fo(u32(o))
        return exe[f:f + u32(f - 4)].decode('latin-1')

    def colour(v):
        return '#%02X%02X%02X' % (v & 0xff, v >> 8 & 0xff, v >> 16 & 0xff)

    def rows(items, per):
        return ',\n  '.join(', '.join(items[i:i + per]) for i in range(0, len(items), per))

    p = exe.find(bytes.fromhex('00000000' '0426fc00' '0492fc00' '04b6fc00'))
    if p < 0:
        sys.exit(f"{exe_path}: Ultimapper's tile colours not found")
    colours = [colour(u32(p + 4 * i)) for i in range(256)]
    p += 1024
    walk = exe[p:p + 256]
    p += 256 + 9 * 8 + 9 * 4 + 5 * 8 + 5 * 4 + 8 * 4 + 8 * 4 + 112 * 4
    hud = [pstr(p + 4 * i) for i in range(48)]
    p += 48 * 4
    pref = exe[p:p + 90]
    if hud[0] != 'Leather Helm' or pref[:2] != b'\x26\x07' or set(walk) != {0, 1}:
        sys.exit(f"{exe_path}: Ultimapper's tables are not where expected")
    q = exe.find(bytes.fromhex('66000000' '66220000' '66660000' '22660000' '00660000'))
    if q < 0:
        sys.exit(f"{exe_path}: Ultimapper's bar colours not found")
    bars = [colour(u32(q + 4 * i)) for i in range(15)]
    out = ['const TILE_COLOURS = [\n  ' + rows([json.dumps(c) for c in colours], 12) + '];',
           "const WALKABLE = Uint8Array.from('" + ''.join(str(b) for b in walk) + "');",
           'const EQUIP_PREF = [\n  ' + rows(['[%d, %d]' % (pref[i], pref[i + 1]) for i in range(0, 90, 2)], 9) + '];',
           'const HUD_ITEMS = [\n  ' + rows([json.dumps(n) for n in hud], 6) + '];',
           'const HP_COLOURS = [' + ', '.join(json.dumps(c) for c in bars[:5]) + '];',
           'const XP_COLOURS = [' + ', '.join(json.dumps(c) for c in bars[5:10]) + '];',
           'const XP_FULL_COLOURS = [' + ', '.join(json.dumps(c) for c in bars[10:]) + '];']
    return '\n'.join(out)


# the fonts each page draws text in, as the original tools' canvases (GDI) do, and the
# pixel heights measured (GBC's map scales its text with its window)
FONT_PAGES = {'ultimapper5.html': (['Verdana', 'Tahoma'], range(5, 41)),
              'ase.html': (['Tahoma', 'Arial Narrow', 'Consolas'], range(5, 41)),
              'gbc.html': (['Verdana', 'Consolas', 'Arial Narrow'], range(5, 65))}
# the round things a page draws as the original's GDI does: ASE's glyphs are circles six
# pixels smaller than the cell (cells of 8 to 76 pixels)
ELLIPSE_PAGES = {'ase.html': range(2, 71)}
# GBC's party triangle on map cells of 32 pixels and up (its pen is 2 pixels wide there;
# the pages draw the 1-pixel one themselves)
TRIANGLE_PAGES = {'gbc.html': range(32, 97)}
# the pages that sort text as the original's string lists do (AnsiCompareText)
SORT_PAGES = ['gbc.html']


def win_sort():
    """WIN_SORT: Windows' primary sort weights (LCMapString's sort key up to its first level
    separator, case ignored) of the characters 32-126, as Delphi's AnsiCompareText (word
    sort) compares them; [] for the ones it passes over there (the hyphen, the apostrophe),
    which only count when all else is equal."""
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32')
    out = []
    for c in range(32, 127):
        key = ctypes.create_string_buffer(64)
        n = kernel32.LCMapStringA(0x0400, 0x00000400 | 0x00000001, bytes([c]), 1, key, 64)   # SORTKEY | IGNORECASE
        raw = key.raw[:n]
        out.append(list(raw[:raw.index(1)] if 1 in raw else raw.rstrip(b'\0')))
    return 'const WIN_SORT = ' + json.dumps(out, separators=(',', ':')) + ';'


def gdi_triangles(sizes):
    """GDI_TRIANGLES: the party triangle GBC draws with Polygon (a 2-pixel pen, a brush) in a
    map cell of cs pixels, facing north, east, south and west; cs -> four strings, each
    the first row and then four characters a row (where the pen starts, where the brush
    starts, where the pen starts again, where the row ends), all chr(48 + n) from
    cs / 5 - 2. GDI's wide lines follow no simple rule, so they are measured."""
    import ctypes
    from ctypes import wintypes
    gdi32 = ctypes.WinDLL('gdi32')
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                       wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.CreatePen.restype = wintypes.HPEN
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.Polygon.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_int]
    pad, out = 4, {}
    for cs in sizes:
        a5, h2, base = cs // 5, cs >> 1, cs // 5 - 2
        shapes = []
        for pts in ([(a5, cs - a5), (h2, a5), (cs - a5, cs - a5)], [(a5, a5), (cs - a5, h2), (a5, cs - a5)],
                    [(a5, a5), (h2, cs - a5), (cs - a5, a5)], [(cs - a5, a5), (a5, h2), (cs - a5, cs - a5)]):
            n = cs + 2 * pad
            dc = gdi32.CreateCompatibleDC(None)
            bits = ctypes.c_void_p()
            bm = gdi32.CreateDIBSection(dc, struct.pack('<IiiHHIIiiII', 40, n, -n, 1, 32, 0, 0, 0, 0, 0, 0), 0,
                                        ctypes.byref(bits), None, 0)
            old = gdi32.SelectObject(dc, bm)
            px = (ctypes.c_uint32 * (n * n)).from_address(bits.value)
            for i in range(n * n):
                px[i] = 0xFFFFFF
            pen, brush = gdi32.CreatePen(0, 2, 0x000000), gdi32.CreateSolidBrush(0x00FF00)
            op, ob = gdi32.SelectObject(dc, pen), gdi32.SelectObject(dc, brush)
            gdi32.Polygon(dc, (ctypes.c_int * 6)(*[v + pad for p in pts for v in p]), 3)
            rows = []
            for y in range(n):
                kinds = ''.join('#' if px[y * n + x] == 0 else 'o' if px[y * n + x] == 0x00FF00 else '.' for x in range(n))
                if kinds.strip('.'):
                    m = re.fullmatch(r'(\.*)(#+)(o*)(#*)(\.*)', kinds)
                    if not m:
                        sys.exit(f'GDI triangle {cs}, row {y - pad}: {kinds}')
                    a = len(m.group(1))
                    b = a + len(m.group(2))
                    c = b + len(m.group(3))
                    rows.append((y - pad, [v - pad for v in (a, b, c, c + len(m.group(4)))]))
            gdi32.SelectObject(dc, op), gdi32.SelectObject(dc, ob), gdi32.SelectObject(dc, old)
            for h in (pen, brush, bm):
                gdi32.DeleteObject(h)
            gdi32.DeleteDC(dc)
            if any(y != rows[0][0] + k for k, (y, _) in enumerate(rows)):
                sys.exit(f'GDI triangle {cs}: rows not together')
            vals = [rows[0][0]] + [v for _, r in rows for v in r]
            if min(vals) < base or max(vals) - base > 78:
                sys.exit(f'GDI triangle {cs}: out of the encoding')
            shapes.append(''.join(chr(48 + v - base) for v in vals))
        out[cs] = shapes
    return 'const GDI_TRIANGLES = {\n' + ',\n'.join(f'  {cs}: {json.dumps(s)}' for cs, s in out.items()) + '\n};'


def gdi_ellipses(sizes):
    """GDI_ELLIPSES: the circles GDI's Ellipse draws (a 1-pixel pen, a brush) in a square of
    d pixels; d -> four characters a row (chr(48 + n)): where the pen starts, where the
    brush starts, where the pen starts again, where the row ends. Windows draws them through
    Bezier curves, a little lopsided, so they are measured rather than computed."""
    import ctypes
    from ctypes import wintypes
    gdi32 = ctypes.WinDLL('gdi32')
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                       wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.CreatePen.restype = wintypes.HPEN
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.Ellipse.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4
    out = {}
    for d in sizes:
        n = d + 2
        dc = gdi32.CreateCompatibleDC(None)
        bits = ctypes.c_void_p()
        bm = gdi32.CreateDIBSection(dc, struct.pack('<IiiHHIIiiII', 40, n, -n, 1, 32, 0, 0, 0, 0, 0, 0), 0,
                                    ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(dc, bm)
        px = (ctypes.c_uint32 * (n * n)).from_address(bits.value)
        for i in range(n * n):
            px[i] = 0xFFFFFF
        pen, brush = gdi32.CreatePen(0, 1, 0x000000), gdi32.CreateSolidBrush(0x00FF00)
        op, ob = gdi32.SelectObject(dc, pen), gdi32.SelectObject(dc, brush)
        gdi32.Ellipse(dc, 1, 1, 1 + d, 1 + d)
        rows = []
        for y in range(1, 1 + d):
            kinds = ''.join('#' if px[y * n + x] == 0 else 'o' if px[y * n + x] == 0x00FF00 else '.'
                            for x in range(1, 1 + d))
            m = re.fullmatch(r'(\.*)(#+)(o*)(#*)(\.*)', kinds)
            if not m:
                sys.exit(f'GDI ellipse {d}, row {y - 1}: {kinds}')
            a = len(m.group(1))
            b = a + len(m.group(2))
            c = b + len(m.group(3))
            rows.append(''.join(chr(48 + v) for v in (a, b, c, c + len(m.group(4)))))
        gdi32.SelectObject(dc, op), gdi32.SelectObject(dc, ob), gdi32.SelectObject(dc, old)
        for h in (pen, brush, bm):
            gdi32.DeleteObject(h)
        gdi32.DeleteDC(dc)
        out[d] = ''.join(rows)
    return 'const GDI_ELLIPSES = {\n' + ',\n'.join(f'  {d}: {json.dumps(s)}' for d, s in out.items()) + '\n};'


def gdi_fonts(faces, sizes):
    """GDI's ascent, descent and character advance widths (32-126) of the fonts at
    the pixel heights given, from 5 up (lfHeight = -px), measured with this Windows'
    fonts: the pages place text with them exactly as the originals' TCanvas.TextOut does."""
    import ctypes
    from ctypes import wintypes
    gdi32 = ctypes.WinDLL('gdi32')

    class TEXTMETRICW(ctypes.Structure):
        _fields_ = [(n, ctypes.c_long) for n in ('tmHeight', 'tmAscent', 'tmDescent', 'tmInternalLeading',
                                                  'tmExternalLeading', 'tmAveCharWidth', 'tmMaxCharWidth',
                                                  'tmWeight', 'tmOverhang', 'tmDigitizedAspectX',
                                                  'tmDigitizedAspectY')] + \
                   [(n, ctypes.c_wchar) for n in ('tmFirstChar', 'tmLastChar', 'tmDefaultChar', 'tmBreakChar')] + \
                   [(n, ctypes.c_byte) for n in ('tmItalic', 'tmUnderlined', 'tmStruckOut', 'tmPitchAndFamily',
                                                 'tmCharSet')]

    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.GetTextMetricsW.argtypes = [wintypes.HDC, ctypes.POINTER(TEXTMETRICW)]
    gdi32.GetCharWidth32W.argtypes = [wintypes.HDC, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
    dc = gdi32.CreateCompatibleDC(None)
    out = []
    for face in faces:
        a, d, w = [], [], []
        for px in sizes:
            f = gdi32.CreateFontW(-px, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, face)
            old = gdi32.SelectObject(dc, f)
            tm = TEXTMETRICW()
            gdi32.GetTextMetricsW(dc, ctypes.byref(tm))
            widths = (ctypes.c_int * 95)()
            gdi32.GetCharWidth32W(dc, 32, 126, widths)
            gdi32.SelectObject(dc, old)
            gdi32.DeleteObject(f)
            a.append(tm.tmAscent)
            d.append(tm.tmDescent)
            w.append(''.join(chr(32 + v) for v in widths))
        out.append(f'  {json.dumps(face)}: {{ a: {json.dumps(a)}, d: {json.dumps(d)},\n    w: [' +
                   ',\n      '.join(json.dumps(s) for s in w) + '] },')
    return 'const GDI_FONTS = {\n' + '\n'.join(out) + '\n};'


def splice(page, name, table, check):
    text = page.read_text('utf-8')
    m = re.search(r'(/\*@' + name + r'@\*/\n)(.*?)(/\*@/' + name + r'@\*/)', text, re.S)
    if not m:
        sys.exit(f'{page.name}: no /*@{name}@*/ ... /*@/{name}@*/ lines')
    if m.group(2) == table + '\n':
        print(f'{page.name} {name}: up to date')
        return
    print(f'{page.name} {name}: ' + ('differs' if check else 'written'))
    if not check:
        page.write_text(text[:m.start(2)] + table + '\n' + text[m.end(2):], 'utf-8', newline='\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--gbc', type=Path, help="Gold Box Companion 2.65's folder (Game.dat patched by patch.py)")
    ap.add_argument('--ultimapper', help='Ultimapper_5.exe')
    ap.add_argument('--magic', help="Ultima5Redux's MagicDefinitions.json")
    ap.add_argument('--fonts', action='store_true', help="GDI's font metrics, measured on this Windows")
    ap.add_argument('--check', action='store_true', help='only report the tables that would change')
    a = ap.parse_args()
    if not a.gbc and not a.ultimapper and not a.fonts:
        ap.error('give --gbc, --ultimapper or --fonts')
    if a.fonts:
        for page, (faces, sizes) in FONT_PAGES.items():
            splice(WEB / page, 'GDI_FONTS', gdi_fonts(faces, sizes), a.check)
        for page, sizes in ELLIPSE_PAGES.items():
            splice(WEB / page, 'GDI_ELLIPSES', gdi_ellipses(sizes), a.check)
        for page, sizes in TRIANGLE_PAGES.items():
            splice(WEB / page, 'GDI_TRIANGLES', gdi_triangles(sizes), a.check)
        for page in SORT_PAGES:
            splice(WEB / page, 'WIN_SORT', win_sort(), a.check)
    if a.gbc:
        for name, make in (('GAME_INFO', game_info), ('FIELDS', fields), ('FIELD_ALIASES', aliases), ('VALUES', values)):
            splice(WEB / 'gbc.html', name, make(a.gbc), a.check)
    if a.ultimapper:
        splice(WEB / 'ultimapper5.html', 'U5_TABLES', u5_tables(a.ultimapper), a.check)
        if a.magic:
            splice(WEB / 'ultimapper5.html', 'SPELLS', spells(a.ultimapper, a.magic), a.check)


if __name__ == '__main__':
    main()

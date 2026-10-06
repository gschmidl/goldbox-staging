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

usage: gen_web_tables.py [--check] [--gbc FOLDER] [--ultimapper EXE [--magic JSON]]

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
    ap.add_argument('--check', action='store_true', help='only report the tables that would change')
    a = ap.parse_args()
    if not a.gbc and not a.ultimapper:
        ap.error('give --gbc or --ultimapper')
    if a.gbc:
        for name, make in (('GAME_INFO', game_info), ('FIELDS', fields), ('FIELD_ALIASES', aliases), ('VALUES', values)):
            splice(WEB / 'gbc.html', name, make(a.gbc), a.check)
    if a.ultimapper:
        splice(WEB / 'ultimapper5.html', 'U5_TABLES', u5_tables(a.ultimapper), a.check)
        if a.magic:
            splice(WEB / 'ultimapper5.html', 'SPELLS', spells(a.ultimapper, a.magic), a.check)


if __name__ == '__main__':
    main()

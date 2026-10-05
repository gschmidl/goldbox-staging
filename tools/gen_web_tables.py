#!/usr/bin/env python3
"""Regenerates the tables built into the companion pages from the tools' own
files and writes them into the pages, between their /*@NAME@*/ and
/*@/NAME@*/ lines.

  web/gbc.html          GAME_INFO  per game: GBC's folder name, character record
                                   size, the program offsets and the two ID
                                   patterns (Game.dat 608, 690-6CC, 6D0, 7D0)
                        FIELDS     character record fields [offset, length]
                        VALUES     race, gender, class, alignment, status names
                                   (both from Resources\\Character file formats)
  web/ultimapper5.html  SPELLS     [name, circle, reagent mask, effect] in
                                   SAVED.GAM order: circles and reagents from
                                   Ultima5Redux's MagicDefinitions.json, the
                                   effects as Ultimapper_5.exe names them

usage: gen_web_tables.py [--check] [--gbc FOLDER] [--ultimapper EXE --magic JSON]

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
REAGENT_KEYS = ['SulfurAsh', 'Ginseng', 'Garlic', 'SpiderSilk', 'BloodMoss', 'BlackPearl', 'NightShade', 'MandrakeRoot']


def compact(name, value):
    return f'const {name} = ' + json.dumps(value, separators=(',', ':')) + ';'


def game_info(gbc):
    """GBC's Game.dat headers, games in folder order (01. Pool of Radiance ...)."""
    out = []
    for d in sorted(p for p in (gbc / 'Games').iterdir() if re.match(r'\d\d\. ', p.name)):
        g = (d / 'Game.dat').read_bytes()
        sstr = lambda off: g[off + 1:off + 1 + g[off]].decode('latin-1')
        out.append({'dir': d.name, 'rec': struct.unpack_from('<i', g, 0x608)[0],
                    'o': list(struct.unpack_from('<16i', g, 0x690)), 'id1': sstr(0x6D0), 'id2': sstr(0x7D0)})
    return compact('GAME_INFO', out)


def formats(gbc):
    """(game number, text) of Resources\\Character file formats\\NN. <game>.txt."""
    for p in sorted((gbc / 'Resources' / 'Character file formats').iterdir()):
        m = re.match(r'(\d\d)\. ', p.name)
        if m:
            yield int(m.group(1)), p.read_text('latin-1')


def fields(gbc):
    out = {}
    for game, text in formats(gbc):
        f = {}
        for line in text.splitlines():
            r = ROW.match(line)
            if not r:
                continue
            key = FIELD_KEYS.get(re.split(r'\s{2,}', r.group(4))[0].strip().lower())
            if key and key not in f:
                f[key] = [int(r.group(1), 16), int(r.group(3))]
        out[game] = f
    return compact('FIELDS', out)


def values(gbc):
    out = {}
    for game, text in formats(gbc):
        g = {}
        for key, title in (('race', 'RACE'), ('gender', 'GENDER'), ('cls', 'CLASS'), ('align', 'ALIGNMENT'),
                           ('status', 'STATUS')):
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
    if not a.gbc and not (a.ultimapper and a.magic):
        ap.error('give --gbc, or --ultimapper and --magic')
    if a.gbc:
        for name, make in (('GAME_INFO', game_info), ('FIELDS', fields), ('VALUES', values)):
            splice(WEB / 'gbc.html', name, make(a.gbc), a.check)
    if a.ultimapper and a.magic:
        splice(WEB / 'ultimapper5.html', 'SPELLS', spells(a.ultimapper, a.magic), a.check)


if __name__ == '__main__':
    main()

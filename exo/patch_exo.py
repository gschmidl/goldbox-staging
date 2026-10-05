#!/usr/bin/env python3
"""Switches an eXoDOS installation's companion tools to the web pages.

The Gold Box Companion, All-Seeing Eye and Ultimapper 5 options of eXoDOS's
English game launchers (eXoDOS\\!dos\\<game>\\exception.bat) then start the game
in DOSBox Staging with its webserver on and open gbc.html, ase.html or
ultimapper5.html in the default web browser instead of the Windows tools.

- Launchers: the tool's start becomes gbc_staging_page.bat, which opens the
  page as soon as Staging's webserver answers; the option's DOSBox becomes
  the given Staging with gbc_staging.conf; the taskkill of the tool goes.
  exception.bat.orig keeps each launcher as it was.
- emulators\\dosbox\\gbc_staging.conf and gbc_staging_page.bat.
- The Staging folder's resources\\webserver, which Staging serves: the three
  pages, and the links util and eXoDOS (to the eXo folder's util and eXoDOS)
  that give the pages the tools' data and the game folders.

usage: python patch_exo.py [--check | --revert] [--staging FOLDER] EXO_FOLDER

EXO_FOLDER is eXoDOS's "eXo" folder, the one with eXoDOS, emulators and util in
it. --check shows what would change, --revert undoes it. --staging is the
DOSBox Staging folder, relative to the eXo folder (default:
emulators\\dosbox\\staging0.83.0); it has to be Staging 0.83 or newer, which has
the webserver.
"""
import argparse
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES = ('gbc.html', 'ase.html', 'ultimapper5.html')
LINKS = ('util', 'eXoDOS')
NOTE = 'goldbox-staging.txt'

CONF = r'''# DOSBox Staging settings for the companion pages (gbc.html, ase.html,
# ultimapper5.html) and the patched companion tools. eXo's launchers load it
# after the game's own configs.

[sdl]
# The patched tools find the DOSBox window by its title; keep "DOSBox
# Staging" in it (Staging's default, dosbox=auto, drops it while a program runs).
window_titlebar = program=name dosbox=always cycles=on mouse=full

[webserver]
# The pages read and write the game's memory through the HTTP API;
# gbc_staging_page.bat opens them on this port.
webserver_enabled = on
webserver_port = 8086

[mt32]
# eXo's MT-32 ROMs (the GBC options' game configs name them the DOSBox ECE
# way, mt32.romdir, which Staging doesn't read).
romdir = .\mt32
'''

HELPER = r'''@echo off
rem Opens the companion page for an eXo game in the web browser as soon as
rem DOSBox Staging's webserver answers (gbc_staging.conf turns it on, port 8086).
rem   %1 = gbc, ase or ultimapper5
rem   %2 = the game's folder under eXoDOS, e.g. poolrad or ultima5/upgrade
rem Staging serves the pages from its resources\webserver folder, where the
rem links util and eXoDOS give them the tools' data and the game's files.
set port=8086
set "page=%1.html?gamedata=eXoDOS/%2"
if /i "%1"=="gbc" set "page=%page%&gbcdata=util/GBC"
if /i "%1"=="ase" set "page=%page%&asedata=util/ASE&ase3data=util/ASE3"
if /i "%1"=="ultimapper5" set "page=%1.html?data=eXoDOS/%2"
curl.exe -s -f -o nul --retry 60 --retry-delay 1 --retry-connrefused "http://127.0.0.1:%port%/api/v1/dosbox/info" || exit /b
start "" "http://localhost:%port%/%page%"
'''

README = r'''Companion pages for DOSBox Staging (goldbox-staging, exo\patch_exo.py)

DOSBox Staging serves this folder over its webserver. patch_exo.py put the
pages here (gbc.html, ase.html, ultimapper5.html), and two links that give
them the tools' data and the games' files:

  util   -> the eXo folder's util     (GBC, ASE, ASE3)
  eXoDOS -> the eXo folder's eXoDOS   (the game folders: saved games, maps)

The launchers' GBC / ASE / Ultimapper options start this DOSBox Staging with
emulators\dosbox\gbc_staging.conf and open the page with
emulators\dosbox\gbc_staging_page.bat. "python patch_exo.py --revert <eXo
folder>" undoes all of it.
'''

TOOL = re.compile(r'start\s+\.\\util\\(GBC\\GBC\.exe|ASE3\\ASE3|ASE\\ASE|Ultimapper5\\Ultimapper_5)\b', re.I)
PAGE = re.compile(r'start\s+""\s+/b\s+cmd\s+/c\s+\.\\emulators\\dosbox\\gbc_staging_page\.bat\s+(\S+)', re.I)
KILL = re.compile(r'taskkill\s+/IM\s+(GBC|ASE|ASE3|Ultimapper_5)\.exe$', re.I)
EXE = re.compile(r'"[^"]*\\dosbox\.exe"|"\.\\emulators\\dosbox\\%dosbox%"', re.I)
NOTES = {
    'echo Note: Dosbox Staging is not compatible with Gold Box Companion.':
        'echo Note: GBC opens in your web browser, served by DOSBox Staging.',
    'echo Note: Dosbox Staging is not compatible with Ultimapper5.':
        'echo Note: Ultimapper5 opens in your web browser, served by DOSBox Staging.',
}


def crlf(text):
    return text.replace('\r\n', '\n').replace('\n', '\r\n').encode('latin-1')


def same(a, b):
    """Equal apart from line ends."""
    return a.replace(b'\r\n', b'\n') == b.replace(b'\r\n', b'\n')


def game_folder(exo, game, dosbox_line):
    """The game's folder under eXoDOS that an option runs, from its config's
    autoexec ("mount c .\\eXoDOS\\..." and the cd's after it), else the
    launcher's folder name."""
    m = re.search(r'-conf\s+"([^"]+)"', dosbox_line)
    if not m:
        return game
    conf = re.sub(r'%var%', lambda _: 'eXoDOS\\!dos\\' + game, m.group(1), flags=re.I)
    try:
        text = (exo / conf.lstrip('.\\')).read_text('latin-1')
    except OSError:
        return game
    parts, mounted, auto = [], False, False
    for line in text.splitlines():
        s = line.strip().lstrip('@').strip()
        if s.startswith('['):
            auto = s.lower() == '[autoexec]'
            continue
        if not auto:
            continue
        mm = re.match(r'mount\s+c\s+"?\.\\eXoDOS\\?([^"]*?)\\?"?(\s+-.*)?$', s, re.I)
        if mm and not mounted:
            parts, mounted = [p for p in mm.group(1).split('\\') if p], True
            continue
        mc = re.match(r'cd\s+(\S+)$', s, re.I)
        if mc and mounted:
            for p in mc.group(1).split('\\'):
                if p == '':
                    parts = []
                elif p == '..':
                    parts = parts[:-1]
                elif p != '.':
                    parts.append(p)
    if parts and parts[0].lower() == game.lower():
        parts[0] = game   # the folder's own spelling (Windows ignores case anyway)
    return '/'.join(parts) if parts else game


def convert(exo, game, text, exe):
    """The launcher with its tool options switched to the pages (exe: the
    quoted dosbox.exe path), and a list of (page, folder) of the options.
    Options switched before are brought up to date."""
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(nl)
    out, opts, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        m = TOOL.match(s) or PAGE.match(s)
        j = next((k for k in range(i + 1, min(i + 7, len(lines))) if EXE.search(lines[k])), None) if m else None
        if m and j is not None:
            tool = m.group(1).lower()
            page = 'gbc' if tool.startswith('gbc') else 'ultimapper5' if tool.startswith('ultimapper') else 'ase'
            dos = lines[j]
            folder = game_folder(exo, game, dos)
            out.append(f'start "" /b cmd /c .\\emulators\\dosbox\\gbc_staging_page.bat {page} {folder}')
            out.extend(lines[i + 1:j])
            dos = EXE.sub(lambda _: exe, dos, count=1)
            if 'gbc_staging.conf' not in dos.lower():
                conf = ' -conf ".\\emulators\\dosbox\\gbc_staging.conf"'
                dos = dos.replace(' -noconsole', conf + ' -noconsole', 1) if ' -noconsole' in dos else dos + conf
            out.append(re.sub(r' -nomenu\b', '', dos))
            opts.append((page, folder))
            i = j + 1
            continue
        if KILL.match(s):
            i += 1
            continue
        out.append(line.replace(s, NOTES[s]) if s in NOTES else line)
        i += 1
    return nl.join(out), opts


def page_stagings(exo, text):
    """The Staging folders that a launcher's switched options start."""
    lines, found = text.splitlines(), set()
    for i, line in enumerate(lines):
        if not PAGE.match(line.strip()):
            continue
        for k in range(i + 1, min(i + 7, len(lines))):
            m = EXE.search(lines[k])
            if m:
                p = m.group(0).strip('"')
                if p.lower().endswith('\\dosbox.exe'):
                    p = p[:-len('\\dosbox.exe')]
                    found.add((exo / p[2:]).resolve() if p.startswith('.\\') else Path(p).resolve())
                break
    return found


def is_link(p):
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def points_to(link, target):
    return os.path.normcase(os.path.realpath(link)) == os.path.normcase(os.path.realpath(target))


def make_link(link, target):
    """A relative directory symlink, or a junction where Windows doesn't allow
    symlinks (they need Developer Mode or admin rights)."""
    try:
        os.symlink(os.path.relpath(target, link.parent), link, target_is_directory=True)
        return 'symbolic link'
    except OSError:
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        except (ImportError, AttributeError, OSError):
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
        return 'junction'


class Patcher:
    def __init__(self, exo, staging, check):
        self.exo, self.check, self.changes = exo, check, 0
        self.staging = (exo / staging).resolve()
        try:
            rel = os.path.relpath(self.staging, exo)
        except ValueError:   # on another drive
            rel = '..'
        # the launchers run from the eXo folder: a path relative to it where possible
        self.exe = f'"{self.staging}\\dosbox.exe"' if rel.startswith('..') else f'".\\{rel}\\dosbox.exe"'
        self.web = self.staging / 'resources' / 'webserver'

    def say(self, text):
        print(('would ' if self.check else '') + text)
        self.changes += 1

    def rel(self, p):
        try:
            return str(p.relative_to(self.exo))
        except ValueError:
            return str(p)

    def write(self, path, data, backup=True):
        """Writes data unless the file already says that (line ends aside);
        a different file is kept as .orig first (once)."""
        if path.exists() and same(path.read_bytes(), data):
            return
        orig = path.with_name(path.name + '.orig')
        keep = backup and path.exists() and not orig.exists()
        self.say(f'write {self.rel(path)}' + (f' (old one kept as {orig.name})' if keep else ''))
        if self.check:
            return
        if keep:
            orig.write_bytes(path.read_bytes())
        path.write_bytes(data)

    def remove(self, path):
        self.say(f'remove {self.rel(path)}')
        if not self.check:
            os.rmdir(path) if is_link(path) else path.unlink()

    def restore(self, path, ours=None):
        """Puts back path.orig; without one, removes the file if it is ours."""
        orig = path.with_name(path.name + '.orig')
        if orig.exists():
            self.say(f'restore {self.rel(path)} from {orig.name}')
            if not self.check:
                path.write_bytes(orig.read_bytes())
                orig.unlink()
        elif path.exists() and (ours is None or same(path.read_bytes(), ours)):
            self.remove(path)

    def launchers(self):
        """The English launchers that start one of the tools or the pages."""
        for d in sorted((self.exo / 'eXoDOS' / '!dos').iterdir(), key=lambda p: p.name.lower()):
            bat = d / 'exception.bat'
            if d.name.startswith('!') or not bat.is_file():
                continue
            text = bat.read_bytes().decode('latin-1')
            if TOOL.search(text) or 'gbc_staging_page.bat' in text:
                yield d.name, bat, text

    def clear(self, web, keep_folder):
        """Removes the pages, links and note from a webserver folder; the
        folder goes too when nothing else is left and keep_folder is off."""
        if not web.is_dir():
            return
        for name in LINKS:
            if is_link(web / name) and points_to(web / name, self.exo / name):
                self.remove(web / name)
        for name in PAGES + (NOTE,):
            if (web / name).is_file():
                self.remove(web / name)
        if not keep_folder and not self.check and not any(web.iterdir()):
            web.rmdir()
            print(f'removed {self.rel(web)}')

    def old_webservers(self, warn=True):
        """A webserver folder in the eXo folder hides the Staging folder's
        (Staging serves the first of <working folder>\\webserver,
        <working folder>\\resources\\webserver and its own resources\\webserver,
        and eXo starts it from the eXo folder). One with only the pages, links
        and notes (README.txt, from an earlier setup) is removed."""
        for web in (self.exo / 'webserver', self.exo / 'resources' / 'webserver'):
            if not web.is_dir():
                continue
            ours = all(e.name in PAGES + (NOTE, 'README.txt') and e.is_file()
                       or e.name in LINKS and is_link(e) and points_to(e, self.exo / e.name) for e in web.iterdir())
            if not ours:
                if warn:
                    print(f'warning: {self.rel(web)} hides {self.rel(self.web)} from DOSBox Staging; move it away')
                continue
            if (web / 'README.txt').is_file():
                self.remove(web / 'README.txt')
            self.clear(web, keep_folder=False)

    def apply(self, pages_dir):
        dbx, before = self.exo / 'emulators' / 'dosbox', set()
        for game, bat, text in self.launchers():
            before |= page_stagings(self.exo, text)
            new, opts = convert(self.exo, game, text, self.exe)
            if new == text:
                continue
            self.say(f'switch {game}: ' + ', '.join(f'{p}.html ({f})' for p, f in opts))
            orig = bat.with_name('exception.bat.orig')
            if not self.check:
                if not orig.exists():
                    orig.write_bytes(text.encode('latin-1'))
                bat.write_bytes(new.encode('latin-1'))
        self.write(dbx / 'gbc_staging.conf', crlf(CONF))
        self.write(dbx / 'gbc_staging_page.bat', crlf(HELPER))
        for s in before - {self.staging}:   # the launchers started another Staging so far
            self.clear(s / 'resources' / 'webserver', keep_folder=True)
        self.old_webservers()
        if not self.web.is_dir():
            self.say(f'create {self.rel(self.web)}')
            if not self.check:
                self.web.mkdir(parents=True)
        for name in PAGES:
            self.write(self.web / name, (pages_dir / name).read_bytes(), backup=False)
        self.write(self.web / NOTE, crlf(README), backup=False)
        for name in LINKS:
            link, target = self.web / name, self.exo / name
            if is_link(link) and points_to(link, target):
                continue
            if os.path.lexists(link):
                print(f'warning: {self.rel(link)} exists and is not a link to {name}; left alone')
                continue
            if self.check:
                self.say(f'link {self.rel(link)} -> {name}')
            else:
                kind = make_link(link, target)
                self.say(f'link {self.rel(link)} -> {name} ({kind})')

    def revert(self):
        dbx, stagings = self.exo / 'emulators' / 'dosbox', {self.staging}
        norm = lambda t: EXE.sub('"dosbox.exe"', t)
        for game, bat, text in self.launchers():
            stagings |= page_stagings(self.exo, text)
            orig = bat.with_name('exception.bat.orig')
            if not orig.exists():
                continue
            old = orig.read_bytes().decode('latin-1')
            if text != old and norm(text) != norm(convert(self.exo, game, old, self.exe)[0]):
                print(f'warning: {game}\\exception.bat changed since it was patched; left alone')
                continue
            self.say(f'restore {game}\\exception.bat')
            if not self.check:
                bat.write_bytes(orig.read_bytes())
                orig.unlink()
        self.restore(dbx / 'gbc_staging.conf', crlf(CONF))
        self.restore(dbx / 'gbc_staging_page.bat')
        for s in sorted(stagings):
            self.clear(s / 'resources' / 'webserver', keep_folder=True)
        self.old_webservers(warn=False)


def has_webserver(exe):
    """DOSBox Staging 0.83+ (the webserver's settings are in the program)."""
    tail = b''
    with open(exe, 'rb') as f:
        while chunk := f.read(1 << 20):
            if b'webserver_enabled' in tail + chunk:
                return True
            tail = chunk[-32:]
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('exo', help="eXoDOS's eXo folder (with eXoDOS, emulators and util in it)")
    ap.add_argument('--check', action='store_true', help='only show what would change')
    ap.add_argument('--revert', action='store_true', help='undo the changes')
    ap.add_argument('--staging', default='emulators\\dosbox\\staging0.83.0',
                    help='the DOSBox Staging folder, relative to the eXo folder (default: %(default)s)')
    a = ap.parse_args()
    exo = Path(a.exo).resolve()
    if not (exo / 'eXoDOS' / '!dos').is_dir() and (exo / 'eXo' / 'eXoDOS' / '!dos').is_dir():
        exo = exo / 'eXo'
    if not (exo / 'eXoDOS' / '!dos').is_dir():
        sys.exit(f'{exo} is not an eXo folder (no eXoDOS\\!dos in it)')
    p = Patcher(exo, Path(a.staging), a.check)
    if a.revert:
        p.revert()
    else:
        exe = p.staging / 'dosbox.exe'
        if not exe.is_file():
            sys.exit(f'no DOSBox Staging at {exe} (--staging names another folder)')
        if not has_webserver(exe):
            sys.exit(f'{exe} has no webserver: the pages need DOSBox Staging 0.83 or newer')
        pages = next((d for d in (HERE.parent / 'web', HERE / 'web') if (d / PAGES[0]).is_file()), None)
        if not pages:
            sys.exit('the pages (gbc.html, ase.html, ultimapper5.html) are not in ..\\web or web\\ next to this script')
        p.apply(pages)
    if not p.changes:
        print('nothing would change' if a.check else 'nothing to do')
    elif not a.check:
        print('done')


if __name__ == '__main__':
    main()

"""The fidelity tests' common part: a session is a script of steps (game
state, settings, input, observations) that runs once against the original
tool and once against the page, both on the same fake DOSBox; then the
observations are compared pair by pair.

A side (Original or Page subclass of a tool module) implements:
  start(settings), stop(), state(image) (via the fake DOSBox), settle(),
  view(name) -> PIL image, text(name) -> str, menu(path), click(...), key(...)
and the session records what it sees with side.observe(name, value)."""
import io
import json
import re
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SANDBOX_DLL = REPO / 'build' / 'sandbox' / 'dbxapi32.dll'   # build.sh


class Observation:
    def __init__(self, name, value, kind):
        self.name, self.value, self.kind = name, value, kind


class Side:
    """What both sides share: the fake DOSBox, the observation list."""
    which = '?'

    def __init__(self, run, fake):
        self.run = run
        self.fake = fake
        self.obs = []
        self.step = 0

    def observe(self, name, value, kind=None):
        if kind is None:
            kind = 'image' if isinstance(value, Image.Image) else 'text'
        self.obs.append(Observation(name, value, kind))

    def writes(self):
        """The memory writes since the last call: [(offset, hex bytes)]."""
        return [(off, data.hex()) for _, off, data, _ in self.fake.take_writes()]

    def wait(self, seconds):
        time.sleep(seconds)


def colour(css):
    """(r, g, b) of a CSS colour as canvas reports it (#rrggbb or rgba())."""
    css = (css or '').strip()
    if css.startswith('#') and len(css) == 7:
        return tuple(int(css[i:i + 2], 16) for i in (1, 3, 5))
    if css.startswith('rgb'):
        return tuple(int(float(v)) for v in css[css.index('(') + 1:-1].split(',')[:3])
    return None


def ink_box(px, bg, threshold=90):
    """The bounding box of the pixels that differ from the background."""
    m = np.abs(px - np.array(bg)).sum(axis=2) > threshold
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def diff_images(a, b, texts=None, tolerance=0, slack=2, ignore=()):
    """Compares the original's picture a with the page's b.
    texts: what the page drew as text (instrument.js); their boxes (grown by
    slack pixels) are left out of the pixel comparison, since the two draw
    the same font with different rasterizers, and are checked loosely
    instead: the ink of the text's colour has to cover the same box within
    slack pixels in both. Returns (differing pixels, their areas, text
    problems, a diff picture)."""
    a = np.asarray(a.convert('RGB')).astype(np.int16)
    b = np.asarray(b.convert('RGB')).astype(np.int16)
    if a.shape != b.shape:
        h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
        pa, pb = np.zeros((h, w, 3), np.int16) - 1, np.zeros((h, w, 3), np.int16) - 2
        pa[:a.shape[0], :a.shape[1]] = a
        pb[:b.shape[0], :b.shape[1]] = b
        a, b = pa, pb
    H, W = a.shape[:2]
    d = (np.abs(a - b) > tolerance).any(axis=2)
    keep = np.ones_like(d)
    for l, t, r, bt in ignore:   # parts drawn differently on purpose
        keep[max(t, 0):max(bt, 0), max(l, 0):max(r, 0)] = False
    problems = []
    for k, t in enumerate(texts or []):
        l, tp, r, bt = t['box']
        if any(il <= l < ir and it <= tp < ib for il, it, ir, ib in ignore):
            continue
        l, tp, r, bt = max(l - slack, 0), max(tp - slack, 0), min(r + slack + 1, W), min(bt + slack + 1, H)
        if l >= r or tp >= bt or not t['text'].strip():
            continue
        keep[tp:bt, l:r] = False
        region_a, region_b = a[tp:bt, l:r], b[tp:bt, l:r]
        # the loose check needs a plain background around the text (both sides)
        ring_b = np.concatenate([region_b[0], region_b[-1], region_b[:, 0], region_b[:, -1]])
        ring_a = np.concatenate([region_a[0], region_a[-1], region_a[:, 0], region_a[:, -1]])
        vals, counts = np.unique(ring_b, axis=0, return_counts=True)
        bg = vals[counts.argmax()]
        if counts.max() < 0.9 * len(ring_b) or (np.abs(ring_a - bg).sum(axis=1) > 30).mean() > 0.1:
            continue
        # ink: what differs from the background by 90, or by 30 % of the text colour's own
        # difference when that is less (dim text at small sizes keeps faint on both sides)
        col, thr = colour(t.get('colour')), 90
        if col:
            thr = min(90, max(30, int(0.3 * sum(abs(int(c) - int(v)) for c, v in zip(col, bg)))))
        # the other texts' ink isn't this one's: where their boxes reach into this one's
        # margin (close rows, a shadow), it counts as background; their part inside this
        # one's box stays (a shadow's ink there is checked with the text)
        region_a, region_b = region_a.copy(), region_b.copy()
        own = t['box']
        inside = np.zeros(region_a.shape[:2], bool)
        inside[max(own[1] - tp, 0):max(own[3] + 1 - tp, 0), max(own[0] - l, 0):max(own[2] + 1 - l, 0)] = True
        for j, o in enumerate(texts):
            if j == k or not o['text'].strip():
                continue
            x0, y0 = max(o['box'][0], l) - l, max(o['box'][1], tp) - tp
            x1, y1 = min(o['box'][2] + 1, r) - l, min(o['box'][3] + 1, bt) - tp
            if x0 < x1 and y0 < y1:
                theirs = np.zeros_like(inside)
                theirs[y0:y1, x0:x1] = True
                theirs &= ~inside
                region_a[theirs] = bg
                region_b[theirs] = bg
        ia, ib = ink_box(region_a, bg, thr), ink_box(region_b, bg, thr)
        if ib is None:
            continue
        if ia is None:
            problems.append(f'text {t["text"]!r} at {t["box"]}: no {t.get("colour")} ink in the original')
        elif max(abs(p - q) for p, q in zip(ia, ib)) > slack:
            problems.append(f'text {t["text"]!r} at {t["box"]}: ink box original {ia}, page {ib} '
                            f'(relative to {l},{tp})')
    counted = d & keep
    pic = np.clip(a, 0, 255).astype(np.uint8) // 3
    pic[counted] = [255, 0, 255]
    pic[d & ~keep] = [0, 160, 255]
    return int(counted.sum()), clusters(counted), problems, Image.fromarray(pic)


def clusters(mask, gap=4, limit=12):
    """Rough bounding boxes of the differing areas."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return []
    boxes = []
    for x, y in zip(xs.tolist(), ys.tolist()):
        for bx in boxes:
            if bx[0] - gap <= x <= bx[2] + gap and bx[1] - gap <= y <= bx[3] + gap:
                bx[0], bx[1], bx[2], bx[3] = min(bx[0], x), min(bx[1], y), max(bx[2], x), max(bx[3], y)
                break
        else:
            boxes.append([x, y, x, y])
            if len(boxes) > 200:
                break
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                p, q = boxes[i], boxes[j]
                if p[0] - gap <= q[2] and q[0] - gap <= p[2] and p[1] - gap <= q[3] and q[1] - gap <= p[3]:
                    boxes[i] = [min(p[0], q[0]), min(p[1], q[1]), max(p[2], q[2]), max(p[3], q[3])]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    boxes.sort(key=lambda b: -(b[2] - b[0] + 1) * (b[3] - b[1] + 1))
    return [tuple(b) for b in boxes[:limit]]


class Result:
    def __init__(self, session):
        self.session = session
        self.items = []     # (name, ok, detail)
        self.error = None

    @property
    def ok(self):
        return self.error is None and all(ok for _, ok, _ in self.items)


def compare(session, orig, page, out_dir, image_tolerance=0):
    """Pairs the two sides' observations by order and name."""
    res = Result(session)
    out_dir = Path(out_dir)
    for i in range(max(len(orig.obs), len(page.obs))):
        o = orig.obs[i] if i < len(orig.obs) else None
        p = page.obs[i] if i < len(page.obs) else None
        name = (o or p).name
        if not o or not p or o.name != p.name:
            res.items.append((name, False, f'observation lists differ: original {o and o.name}, '
                                           f'page {p and p.name}'))
            continue
        tag = f'{session}-{i:02d}-{name}'.replace('/', '_').replace(' ', '_')
        if o.kind != p.kind and not (o.value is None or p.value is None):
            res.items.append((name, False, f'original gave {o.kind}, page {p.kind}'))
            continue
        if o.kind == 'image' or p.kind == 'image':
            if o.value is None or p.value is None:
                res.items.append((name, o.value is None and p.value is None,
                                  f'no image: original {o.value is None}, page {p.value is None}'))
                continue
            ignore = o.value.info.get('ignore', []) + p.value.info.get('ignore', [])
            n, boxes, problems, pic = diff_images(o.value, p.value, p.value.info.get('texts'), image_tolerance,
                                                  ignore=ignore)
            if 'texts' in o.value.info and 'texts' in p.value.info:
                def kept(texts):   # text starting in an ignored part is left out too
                    def corner(t):
                        return (t['box'][0], t['box'][1]) if 'box' in t else (t.get('x', -1), t.get('y', -1))
                    return [t for t in texts if not any(l <= corner(t)[0] < r and tp <= corner(t)[1] < bt
                                                        for l, tp, r, bt in ignore)]
                diffs, count = compare_texts(kept(o.value.info['texts']), kept(p.value.info['texts']))
                if count:
                    problems = [f'{count} texts differ: ' + ', '.join(f'{w} {k[0]!r} {k[1]} {k[2]}px'
                                                                      for k, w in diffs)] + problems
            ok = n == 0 and not problems and o.value.size == p.value.size
            if not ok:
                out_dir.mkdir(parents=True, exist_ok=True)
                o.value.save(out_dir / f'{tag}-original.png')
                p.value.save(out_dir / f'{tag}-page.png')
                pic.save(out_dir / f'{tag}-diff.png')
            detail = '' if ok else '; '.join(
                [f'{n} pixels differ' + (f' (sizes {o.value.size} / {p.value.size})'
                                         if o.value.size != p.value.size else '')
                 + (f', areas {boxes[:6]}' if boxes else '')] + problems[:8])
            res.items.append((name, ok, detail))
        else:
            ok = o.value == p.value
            if ok:
                res.items.append((name, True, ''))
            elif isinstance(o.value, list) and isinstance(p.value, list):
                res.items.append((name, False, list_diff(o.value, p.value)))
            elif isinstance(o.value, dict) and isinstance(p.value, dict):
                res.items.append((name, False, dict_diff(o.value, p.value)))
            else:
                res.items.append((name, False, f'original {short(o.value)}\n      page     {short(p.value)}'))
    return res


def flatten(v, depth=0):
    """Lines of a nested list (menus: [caption, enabled, checked, children])."""
    out = []
    for item in v:
        if isinstance(item, list) and item and isinstance(item[-1], list) and isinstance(item[0], str):
            out.append('  ' * depth + json.dumps(item[:-1]))
            out += flatten(item[-1], depth + 1)
        else:
            out.append('  ' * depth + (item if isinstance(item, str) else json.dumps(item)))
    return out


def list_diff(a, b, limit=40):
    import difflib
    lines = [l for l in difflib.unified_diff(flatten(a), flatten(b), 'original', 'page', lineterm='', n=1)][2:]
    return '\n        '.join([''] + lines[:limit] + ([f'... ({len(lines) - limit} more)'] if len(lines) > limit else []))


def dict_diff(a, b):
    """The fields of two dicts that differ (lists as a unified diff)."""
    out = []
    for k in list(a) + [k for k in b if k not in a]:
        va, vb = a.get(k), b.get(k)
        if va == vb:
            continue
        if isinstance(va, list) and isinstance(vb, list):
            out.append(f'{k}:' + list_diff(va, vb).replace('\n', '\n  '))
        else:
            out.append(f'{k}: original {short(va, 200)}, page {short(vb, 200)}')
    return '\n        '.join([''] + out)


def text_key(t):
    """(text, colour, pixel size) of a text item from either side."""
    size = t.get('height')
    if size is None:
        m = re.search(r'(\d+(?:\.\d+)?)px', t.get('font', ''))
        size = round(float(m.group(1))) if m else 0
    c = colour(t.get('colour'))
    return (t['text'], '#%02x%02x%02x' % c if c else t.get('colour'), size)


def compare_texts(orig, page, limit=10):
    """What text only one side drew: [(text, colour, size, 'original'/'page')]."""
    from collections import Counter

    def once(texts):   # the same text drawn again at the same place (a repaint over itself) counts once
        seen, out = set(), []
        for t in texts:
            if not t['text'].strip():
                continue
            at = tuple(t['box'][:2]) if 'box' in t else (t.get('x'), t.get('y'))
            if (text_key(t), at) not in seen:
                seen.add((text_key(t), at))
                out.append(t)
        return out
    o = Counter(text_key(t) for t in once(orig))
    p = Counter(text_key(t) for t in once(page))
    out = [(k, 'original only') for k in (o - p).elements()] + [(k, 'page only') for k in (p - o).elements()]
    out.sort(key=lambda e: (e[0][0], e[1]))
    return out[:limit], len(out)


def short(v, n=900):
    s = v if isinstance(v, str) else json.dumps(v)
    return s if len(s) <= n else s[:n] + f'... ({len(s)} chars)'


def run_session(name, fn, sides, out_dir):
    """Runs session fn on each side (a factory each), compares."""
    done = []
    for make in sides:
        side = make()
        try:
            fn(side)
        except Exception:
            side.observe('error', traceback.format_exc().splitlines()[-1])
            print(f'  {side.which}: {traceback.format_exc()}')
        finally:
            try:
                side.finish()
            except Exception:
                print(f'  {side.which} finish: {traceback.format_exc()}')
        done.append(side)
    return compare(name, done[0], done[1], out_dir)


def image_from_png(data):
    return Image.open(io.BytesIO(data)).convert('RGB')

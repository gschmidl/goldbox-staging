// Injected into the page before its own scripts by the fidelity tests: every
// canvas remembers where text was drawn on it since it was last cleared (a
// fillRect over all of it, or a new size), so that the comparison with the
// original's pixels can leave the text to a looser test - the two draw the
// same font with different rasterizers. Canvases drawn onto others pass
// their boxes on.
(() => {
  const P = CanvasRenderingContext2D.prototype;
  const fillRect = P.fillRect, fillText = P.fillText, strokeText = P.strokeText, drawImage = P.drawImage;
  const boxes = c => c.__fidBoxes || (c.__fidBoxes = []);
  const map = (t, x, y) => [t.a * x + t.c * y + t.e, t.b * x + t.d * y + t.f];
  P.fillRect = function (x, y, w, h) {
    const c = this.canvas, t = this.getTransform();
    const [x0, y0] = map(t, x, y), [x1, y1] = map(t, x + w, y + h);
    if (c && Math.min(x0, x1) <= 0 && Math.min(y0, y1) <= 0 && Math.max(x0, x1) >= c.width && Math.max(y0, y1) >= c.height)
      c.__fidBoxes = [];
    return fillRect.apply(this, arguments);
  };
  const record = (ctx, text, x, y, how) => {
    const c = ctx.canvas;
    if (!c) return;
    const m = ctx.measureText(text), t = ctx.getTransform();
    const l = x - m.actualBoundingBoxLeft, r = x + m.actualBoundingBoxRight;
    const top = y - m.actualBoundingBoxAscent, bot = y + m.actualBoundingBoxDescent;
    const a = map(t, l, top), b = map(t, r, bot);
    boxes(c).push({ text: String(text), how, colour: String(ctx[how === 'fill' ? 'fillStyle' : 'strokeStyle']), font: ctx.font,
      box: [Math.floor(Math.min(a[0], b[0])), Math.floor(Math.min(a[1], b[1])), Math.ceil(Math.max(a[0], b[0])), Math.ceil(Math.max(a[1], b[1]))] });
  };
  let inGdi = 0;
  P.fillText = function (text, x, y) { if (!inGdi) record(this, text, x, y, 'fill'); return fillText.apply(this, arguments); };
  P.strokeText = function (text, x, y) { if (!inGdi) record(this, text, x, y, 'stroke'); return strokeText.apply(this, arguments); };
  // The pages draw GDI-placed text a character at a time (their Gdi.text): one record
  // for the whole text, its box the GDI character cell
  addEventListener('DOMContentLoaded', () => {
    let gdi;
    try { gdi = Gdi; } catch { return; }   // eslint-disable-line no-undef
    const text = gdi.text;
    gdi.text = function (g, s, x, y) {
      const c = g.canvas;
      if (c && String(s).trim()) {
        const t = g.getTransform(), a = map(t, x, y), b = map(t, x + gdi.width(g, s), y + gdi.height(g));
        // a font asked for by its cell height (GDI's positive lfHeight) is that height, as the
        // original's log has it
        const cell = g.gdiFont && g.gdiFont[4];
        boxes(c).push({ text: String(s), how: 'fill', colour: String(g.fillStyle), font: g.font, ...(cell ? { height: cell } : {}),
          box: [Math.floor(Math.min(a[0], b[0])), Math.floor(Math.min(a[1], b[1])), Math.ceil(Math.max(a[0], b[0])), Math.ceil(Math.max(a[1], b[1]))] });
      }
      inGdi++;
      try { return text.apply(this, arguments); } finally { inGdi--; }
    };
  });
  P.drawImage = function (src, ...a) {
    const c = this.canvas;
    if (c && src && src.__fidBoxes && src.__fidBoxes.length) {
      let sx = 0, sy = 0, sw = src.width, sh = src.height, dx, dy, dw, dh;
      if (a.length === 2) [dx, dy] = a, dw = sw, dh = sh;
      else if (a.length === 4) [dx, dy, dw, dh] = a;
      else [sx, sy, sw, sh, dx, dy, dw, dh] = a;
      const t = this.getTransform(), kx = dw / sw, ky = dh / sh;
      for (const bx of src.__fidBoxes) {
        const p = map(t, dx + (bx.box[0] - sx) * kx, dy + (bx.box[1] - sy) * ky);
        const q = map(t, dx + (bx.box[2] - sx) * kx, dy + (bx.box[3] - sy) * ky);
        boxes(c).push({ ...bx, box: [Math.floor(Math.min(p[0], q[0])), Math.floor(Math.min(p[1], q[1])), Math.ceil(Math.max(p[0], q[0])), Math.ceil(Math.max(p[1], q[1]))] });
      }
    }
    return drawImage.call(this, src, ...a);
  };
  for (const prop of ['width', 'height']) {
    const d = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, prop);
    Object.defineProperty(HTMLCanvasElement.prototype, prop, {
      get() { return d.get.call(this); },
      set(v) { this.__fidBoxes = []; d.set.call(this, v); },
      configurable: true,
    });
  }
  // a canvas's pixels and its text boxes, for the test
  window.__fidCanvas = sel => {
    const c = typeof sel === 'string' ? document.querySelector(sel) : sel;
    if (!c) return null;
    return { png: c.toDataURL('image/png'), boxes: c.__fidBoxes || [], w: c.width, h: c.height };
  };
})();

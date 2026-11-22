// SPDX-License-Identifier: GPL-3.0-only
// Part of Q2 Theme Studio, which holds work from DiamondBond/q2-pod (GPL-3.0-only): see LICENSE at the repository root.
// Q2 Theme Studio preview: the status bar (DRAWING.md section 4), painted on every screen as
// Q2Draw.bar(ctx, env, state). Two themes meet in it: the live theme gives the layout (its geometry set), the
// title, the clock, the digits' face and the half; the bar theme (env.barTheme: the live one unless Status
// Bar names another) gives the fill, the battery, the play-state art and the two icon offsets.
//
// state (each optional, Q2Draw.STATE has the defaults): title (the page's name), home (Home is in front),
// play 'none' | 'playing' | 'paused', wifi 0..4 or null, bt null | 'on' | 'linked', eq (the EQ mark's text),
// battery 0..100, charging, low, plugged, hour, minute, clock24.
(function (root, add) {
  if (typeof module === 'object' && module.exports) module.exports = add(require('./draw_core.js'));
  else add(root.Q2Draw);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Q2Draw) {
  'use strict';

  const { W, div, fill, paintStops } = Q2Draw;
  const MARGIN = 54; // STATUS_MARGIN: the stock-style bar's side margin
  const GAP = 4; // STATUS_GAP, between cells
  const ROOM = 94; // BATT_ROOM: what the right group may take before the battery falls back to its icon
  const NUB_W = 2;
  const NUB_H = 5;
  const BATT_GAP = 2; // between the icon and its percentage
  const CHARGE = 0x34c759;
  const LOW = 0xff1448;
  const CLOCK_MIN = 105; // the centred clock's box on a bar with a title
  const BAR_PAD = 9; // the title's ink this far clear of the glass
  const MODES = ['icon', 'percent', 'both', 'inside'];

  // The clock's text: the stock-style bar writes AM or PM in 12-hour time, a bar with a title does not.
  function clockText(s, titled) {
    const two = (n) => String(n).padStart(2, '0');
    if (s.hour === null || s.hour === undefined) return titled ? '--:--' : '';
    if (s.clock24) return `${two(s.hour)}:${two(s.minute)}`;
    const h = s.hour % 12 || 12;
    return titled ? `${h}:${two(s.minute)}` : `${h}:${two(s.minute)} ${s.hour < 12 ? 'AM' : 'PM'}`;
  }

  // The boxes of a bar with a title (a set with bar_px), from the build's own model (tools/ipod.py
  // status_metrics): the capitals of bar_px text in Classic's face centred on the rows above the bar's two
  // lines, the title's ink 9 px clear of the glass there.
  function titledBoxes(G) {
    const f = Q2Draw.FACES['classic-light'];
    const span = f.ascent - f.descent;
    const scale = G.bar_px / span;
    const cap = Math.ceil(f.cap * scale);
    const h = G.bar - 1;
    const capTop = Math.floor((G.bar - 2 - cap) / 2);
    const y = capTop - (Math.floor((h - G.bar_px) / 2) + Math.floor(f.ascent * scale + 0.5) - cap);
    const inset = Q2Draw.glassInset(capTop) + BAR_PAD;
    return {
      title: [inset - 2, y, G.bar_title_w + 4, h],
      clock: [div(W - CLOCK_MIN, 2), y, CLOCK_MIN, h],
      // the right group's row: as high as centres stock's 16 px icons on the battery's middle row
      rowH: 2 * (Math.floor((G.bar - 2 - G.batt_h) / 2) + div(G.batt_h, 2)),
    };
  }

  // The layout of everything in the bar for an env and a state: where each cell is and what it shows. Kept
  // apart from the painting so the tests and the screens can ask it questions.
  function layout(ctx, env, state) {
    const s = Object.assign({}, Q2Draw.STATE, state);
    const G = env.G;
    const B = env.barTheme;
    const titled = G.bar_px > 0;
    const classicRow = env.choice('bar.battery.painter') === 'classic-light';
    const classic = B.choice('bar.battery.painter') === 'classic-light';
    const boxes = titled ? titledBoxes(G) : null;
    const rowH = titled ? boxes.rowH : G.bar;
    const out = { state: s, titled, classic, rowH, height: G.bar };

    // the battery's mode, gated by the room the right group has (navigation.c bar_sync)
    const liveBarPx = env.T('bar.title.font_size');
    const pctPx = classic && liveBarPx ? liveBarPx : 16;
    const face = env.canvasFace(pctPx, '100%');
    const digit = Q2Draw.measure(ctx, '0', face.face, face.px);
    const sign = Q2Draw.measure(ctx, '%', face.face, face.px);
    const pct = (n) => (n >= 100 ? 3 : n >= 10 ? 2 : 1) * digit + sign;
    const level = Math.max(0, Math.min(100, Math.round(s.battery)));
    const playing = s.play === 'playing' || s.play === 'paused';
    const wifi = s.wifi !== null && s.wifi !== undefined && s.wifi !== false;
    const bt = Boolean(s.bt);
    const stateW = titled ? 18 : 15;
    const body = classic ? B.G.batt_w + 1 : 16;
    const inside = classic ? body : 28;
    let mode = Math.max(0, MODES.indexOf(env.set.battery));
    if (mode) {
      let reach = mode === 1 ? pct(100) : mode === 3 ? inside + NUB_W : body + NUB_W + BATT_GAP + pct(100);
      if (wifi) reach += 14 + GAP;
      if (bt) reach += GAP + 10;
      if (classicRow && playing) reach += stateW + GAP;
      if (reach > ROOM && !(classic && mode === 3)) mode = classic && mode === 2 ? 3 : 0;
    }
    const slotW = mode === 1 ? pct(level) : (mode === 3 ? inside : body) + NUB_W + (mode === 2 ? BATT_GAP + pct(level) : 0);
    out.battery = { mode, level, pctPx, face, charging: Boolean(s.charging), low: Boolean(s.low), plugged: Boolean(s.plugged) };

    // the right group, packed against its margin: Bluetooth, Wi-Fi, the play state (a titled bar), battery
    const right = W - (titled ? G.bar_right : MARGIN);
    let x = right - slotW;
    out.slot = { x, y: 0, w: slotW, h: rowH };
    if (titled && playing) {
      x -= GAP + stateW;
      out.play = { x, y: 0, w: stateW, h: rowH };
    }
    if (wifi) {
      x -= GAP + 14;
      out.wifi = { x, y: B.T('bar.icons.wifi_dy'), w: 14, h: rowH, level: s.wifi };
    }
    if (bt) {
      x -= GAP + 43;
      out.bt = { x, y: B.T('bar.icons.bt_dy'), w: 43, h: rowH, linked: s.bt === 'linked' };
    }

    if (!titled) {
      // the stock-style bar's left group and its centre label
      let at = MARGIN;
      if (playing) {
        out.play = { x: at, y: 0, w: stateW, h: rowH };
        at += stateW + GAP;
      }
      if (s.eq) out.eq = { x: at, y: 0, w: 28, h: rowH, text: s.eq };
      if (!playing && !s.eq) out.idle = { x: MARGIN, y: 0, w: 28, h: G.bar, caps: Boolean(env.T('bar.title.caps')) };
      const centre = { x: 129, y: 0, w: W - 2 * 129, h: G.bar, align: 'center', colour: env.fg };
      let title = null;
      if (!env.timeTitle) {
        title = s.title || null;
        if (s.home) title = env.wordmark ? s.title || 'Q2 Pod' : '';
      }
      if (title === null) out.centre = Object.assign(centre, { text: clockText(s, false), face: 'regular', px: 16, faux: false, clock: true });
      else out.centre = Object.assign(centre, { text: title }, env.role('np', 16, title));
    } else {
      // a bar with a title: the title on the left, the clock centred, both in the bar's role
      const role = (str) => (!env.T('bar.title.font') && !env.T('bar.title.font_size') ? Q2Draw.fallback('classic-light', G.bar_px, str) : env.role('bar', G.bar_px, str));
      const text = s.home ? (env.wordmark ? s.title || 'Q2 Pod' : '') : s.title || '';
      const gone = !env.timeTitle && (s.home || text !== ''); // the clock makes way for the title
      const [tx, ty, tw, th] = boxes.title;
      let width = tw;
      if (gone) {
        // the title takes the clock's room, up to where the right group's room starts
        const widest = Math.ceil(Q2Draw.measureExact(ctx, '12:59 PM', 'classic-light', G.bar_px));
        const room = Math.trunc(W - G.bar_right - (W / 2 + widest / 2 + 2));
        width = Math.max(tw, W - G.bar_right - room - tx);
      }
      out.title = Object.assign({ x: tx, y: ty, w: width, h: th, text, align: 'left', colour: env.fg }, role(text));
      const clock = gone ? '' : clockText(s, true);
      const [cx, cy, cw, ch] = boxes.clock;
      out.clock = Object.assign({ x: cx, y: cy, w: cw, h: ch, text: clock, align: 'center', colour: env.fg }, role(clock));
    }
    return out;
  }

  // The bar's fill by the bar theme's painter: flat, or the gloss rows over their two lines.
  function paintFill(ctx, env, H) {
    const B = env.barTheme;
    const S = B.S;
    if (B.choice('bar.fill.painter') === 'gloss') {
      paintStops(ctx, 0, 0, W, H - 1, S.bar);
      if (S.bar_line2 && env.light) fill(ctx, 0, H - 2, W, 1, S.bar_line2);
      fill(ctx, 0, H - 1, W, 1, S.bar_line);
    } else {
      fill(ctx, 0, 0, W, H, S.bar_light && env.light ? S.bar_light : env.INK(0x000000));
    }
  }

  // The stock painter's battery: an outline with its level, or the solid body with dark digits.
  function stockBattery(ctx, env, L) {
    const b = L.battery;
    const c = env.INK(b.charging ? CHARGE : b.low ? LOW : 0xffffff);
    const { x, w } = L.slot;
    const digits = String(b.level);
    if (b.mode === 1) {
      env.canvasText(ctx, `${digits}%`, x, 0, w, L.rowH, b.pctPx, c);
      return;
    }
    const inside = b.mode === 3;
    const bw = inside ? 28 : 16;
    const bh = inside ? 15 : 11;
    const y = div(L.rowH + 1 - bh, 2) - (b.mode === 2 ? 1 : 0);
    if (inside) {
      Q2Draw.box(ctx, x, y, bw, bh, 3, c);
      fill(ctx, x + bw, y + div(bh - NUB_H, 2), NUB_W, NUB_H, c);
      env.canvasText(ctx, digits, x + 2, y + 1, bw - 4, bh, 13, env.INK(0x000000));
      return;
    }
    fill(ctx, x + 1, y, bw - 2, 1, c);
    fill(ctx, x + 1, y + bh - 1, bw - 2, 1, c);
    fill(ctx, x, y + 1, 1, bh - 2, c);
    fill(ctx, x + bw - 1, y + 1, 1, bh - 2, c);
    fill(ctx, x + bw, y + div(bh - NUB_H, 2), NUB_W, NUB_H, c);
    fill(ctx, x + 2, y + 2, div((bw - 4) * (b.charging ? 100 : b.level), 100), bh - 4, c);
    if (b.mode === 2) {
      const x0 = bw + NUB_W + BATT_GAP;
      env.canvasText(ctx, `${digits}%`, x + x0, 0, w - x0, L.rowH, 16, c);
    }
  }

  // The classic-light painter's battery (navigation.c classic_light_battery): final colours, the bar
  // theme's own; the body is the bar theme's set's batt_w x batt_h with the nub outside.
  function classicBattery(ctx, env, L) {
    const b = L.battery;
    const B = env.barTheme;
    const T = B.T;
    const light = env.light;
    const state = env.INK(b.charging ? CHARGE : b.low ? LOW : 0xffffff);
    const digits = String(b.level);
    if (b.mode === 1) {
      env.canvasText(ctx, `${digits}%`, L.slot.x, 0, L.slot.w, L.rowH, b.pctPx, state);
      return;
    }
    const bw = B.G.batt_w;
    const bh = B.G.batt_h;
    const x = L.slot.x + 1;
    const y = div(L.rowH + 1 - bh, 2) - (b.mode === 2 ? 1 : 0);
    const iw = bw - 2;
    const ih = bh - 2;
    const r = x + bw - 1;
    const ny = y + div(bh - NUB_H, 2);
    const f = b.low ? T('bar.battery.low_w') : div(iw * (b.charging ? 100 : b.level), 100);
    const line = T('bar.battery.line');
    if (light) {
      fill(ctx, x - 1, y, 1, bh, 0x000000, T('bar.battery.soft_a'));
      fill(ctx, x, y - 1, bw, 1, 0x000000, T('bar.battery.soft_top_a'));
    }
    fill(ctx, x + 1, y, iw, 1, line);
    fill(ctx, x, y + 1, 1, ih, line);
    fill(ctx, r, y + 1, 1, ih, line);
    fill(ctx, x + bw, ny, NUB_W - 1, 1, line);
    fill(ctx, x + bw, ny + NUB_H - 1, NUB_W - 1, 1, line);
    fill(ctx, x + bw + NUB_W - 1, ny + 1, 1, NUB_H - 2, line);
    for (const [px, py] of [[x, y], [r, y], [x + bw + NUB_W - 1, ny], [x + bw + NUB_W - 1, ny + NUB_H - 1]]) fill(ctx, px, py, 1, 1, line, T('bar.battery.corner_a'));
    fill(ctx, x, y + bh - 1, 1, 1, line, T('bar.battery.foot_a'));
    fill(ctx, r, y + bh - 1, 1, 1, line, T('bar.battery.foot_a'));
    fill(ctx, x + 1, y + bh - 1, iw, 1, T('bar.battery.edge'));
    paintStops(ctx, x + 1, y + 1, iw, ih, T('bar.battery.empty'));
    if (b.low) fill(ctx, x + 1, y + 1, f, ih, T('bar.battery.low'));
    else paintStops(ctx, x + 1, y + 1, f, ih, T('bar.battery.stops'));
    fill(ctx, r - 1, y + 1, 1, ih, 0x000000, T('bar.battery.shade_a'));
    if (light) {
      fill(ctx, x, y + bh + 1, bw - 1, 1, 0xffffff, T('bar.battery.emboss_a'));
      fill(ctx, x + bw, ny + NUB_H, NUB_W, 2, 0xffffff, T('bar.battery.emboss_nub_a'));
    }
    if (b.mode !== 3) {
      if (b.charging) env.art.bolt(ctx, x + 1, y + 1, T);
      else if (b.plugged) env.art.plug(ctx, x + 1, y + 1, T);
    }
    if (b.mode === 2) {
      const x0 = 1 + bw + NUB_W + BATT_GAP;
      env.canvasText(ctx, `${digits}%`, L.slot.x + x0, 0, L.slot.w - x0, L.rowH, b.pctPx, state);
    } else if (b.mode === 3) {
      // the digits twice with a clip: dark over the level, light past it (each flips with the half)
      const rx = L.slot.x + 2;
      const part = (cx, cw, c) => {
        if (cw <= 0) return;
        ctx.save();
        ctx.beginPath();
        ctx.rect(cx, y + 1, cw, ih);
        ctx.clip();
        env.canvasText(ctx, digits, rx, y + 1, bw - 2, ih, ih, c);
        ctx.restore();
      };
      part(rx, f, env.INK(light ? 0xffffff : 0x000000));
      part(rx + f, bw - 2 - f, env.INK(light ? 0x000000 : 0xffffff));
    }
  }

  // One of the layout's text boxes: a scrolling label, 2 px inside its box, ellipsed.
  function label(ctx, env, t) {
    if (!t || !t.text) return;
    env.label(ctx, t.text, t.x, t.y, t.w, t.h, { face: t.face, px: t.px, faux: t.faux, align: t.align, colour: t.colour });
  }

  function bar(ctx, env, state) {
    const L = layout(ctx, env, state);
    const B = env.barTheme;
    const classic = L.classic;
    const H = L.height;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, W, H);
    ctx.clip();
    paintFill(ctx, env, H);

    // the play state: the bar theme's battery painter picks the art
    if (L.play) {
      const kind = L.state.play === 'paused' ? 'pause' : 'play';
      const [iw, ih] = classic ? [18, 22] : [12, 16];
      const px = L.play.x + Math.floor((L.play.w - iw) / 2);
      const py = L.play.y + Math.floor((L.play.h - ih) / 2);
      if (classic) env.art.state(ctx, px, py, kind, B.T);
      else if (kind === 'play') env.art.barPlay(ctx, px, py);
      else env.art.barPause(ctx, px, py);
    }
    if (L.eq) env.plain(ctx, L.eq.text, L.eq.x, L.eq.y, L.eq.w, L.eq.h, { px: 16, colour: env.fg });
    if (L.bt) env.art.bt(ctx, L.bt.x, L.bt.y + Math.floor((L.bt.h - 16) / 2), L.bt.linked);
    if (L.wifi) env.art.wifi(ctx, L.wifi.x, L.wifi.y + Math.floor((L.wifi.h - 16) / 2), L.wifi.level);
    if (classic) classicBattery(ctx, env, L);
    else stockBattery(ctx, env, L);

    if (L.idle) {
      // the idle mark: Minimal's small capitals, or the label's own 18 px text
      if (L.idle.caps) env.caps(ctx, 'Q2', L.idle.x, div(H - 14, 2), 14, env.INK(0xaaaaaa), W);
      else env.plain(ctx, 'Q2', L.idle.x, L.idle.y, L.idle.w, L.idle.h, { px: 18, colour: env.fg });
    }
    label(ctx, env, L.centre);
    label(ctx, env, L.title);
    label(ctx, env, L.clock);
    ctx.restore();
    return L;
  }

  Q2Draw.bar = bar;
  Q2Draw.barLayout = layout;
  return Q2Draw;
});

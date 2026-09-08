/* Arrakis sandstorm — an interactive desert behind the archive UI.
 *
 * Four ideas make it read as weather you can touch rather than a looping
 * background:
 *
 *   1. Depth. Every grain carries a `z` in 0..1 that drives size, opacity,
 *      speed and parallax together, so the field is a volume, not a sheet.
 *   2. Gusts. Wind is a base value plus travelling envelopes at different
 *      speeds; where they overlap it spikes, so the storm breathes.
 *   3. The pointer is a physical object in the field. Grains are shoved out of
 *      the way, dragged along with the cursor's motion, curled into its wake and
 *      thrown up when it moves fast. Near grains react more than far ones, which
 *      is what sells the depth.
 *   4. State. The storm surges while an investigation runs and settles when the
 *      answer lands, so the motion is feedback rather than noise.
 *
 * It is also required to get out of the way: it honours prefers-reduced-motion,
 * sleeps on a hidden tab, caps DPR, and scales its particle count to the
 * viewport.
 */
(() => {
  "use strict";

  const canvas = document.getElementById("sandCanvas");
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext("2d", { alpha: true });
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  const CFG = {
    maxDPR: 2,
    grainsPerMegapixel: 260,
    grainCap: 620,
    baseWind: 0.5,
    surgeWind: 2.8,
    surgeRamp: 0.022,
    denseBelow: 0.34,       // grains exist above this too, just sparser
    // --- pointer physics ---
    pointerRadius: 170,     // influence radius, px
    pushStrength: 1.6,      // radial shove out of the cursor's way
    dragStrength: 0.45,     // how much cursor motion carries grains with it
    swirl: 0.6,             // tangential component, so the wake curls
    kickSpeed: 8,           // cursor px/frame above which sand is thrown up
    kickMax: 5,             // grains spawned per frame while moving fast
    sparkCap: 260,
  };

  let w = 0, h = 0, dpr = 1;
  let grains = [], streaks = [], sparks = [];
  let raf = 0, running = false;

  let wind = CFG.baseWind, target = CFG.baseWind, burst = 0;

  // Pointer state. `vx/vy` are smoothed so a jittery mouse does not produce a
  // jittery wake, and `power` decays so a disturbance lingers briefly.
  const P = {
    x: -1e4, y: -1e4, px: -1e4, py: -1e4,
    vx: 0, vy: 0, speed: 0, power: 0, active: false,
  };

  const rand = (a, b) => a + Math.random() * (b - a);

  function makeGrain(seedX, seedY) {
    const z = Math.random();
    // Density is biased toward the desert floor, but grains exist everywhere so
    // the pointer has something to disturb wherever it is on screen.
    const y = seedY !== undefined ? seedY
      : (Math.random() < 0.72 ? rand(h * CFG.denseBelow, h * 1.02)
                              : rand(-20, h * CFG.denseBelow));
    return {
      x: seedX !== undefined ? seedX : rand(-40, w + 40),
      y, z,
      r: 0.25 + z * 1.45,
      speed: 0.25 + z * 1.45,
      vx: 0, vy: 0,                       // velocity imparted by the pointer
      drift: rand(-0.5, 0.5),
      alpha: 0.05 + z * 0.30,
      phase: Math.random() * Math.PI * 2,
      wobble: 0.2 + Math.random() * 0.7,
    };
  }

  function makeStreak() {
    const z = Math.random();
    return {
      x: rand(-300, w), y: rand(h * 0.45, h * 0.99),
      len: rand(90, 320) * (0.5 + z), z,
      speed: 0.6 + z * 2.4, alpha: 0.03 + z * 0.09, tilt: rand(-4, 2),
    };
  }

  /** A short-lived grain thrown up by fast pointer motion or a click. */
  function makeSpark(x, y, vx, vy) {
    return {
      x, y,
      vx: vx * rand(0.25, 0.75) + rand(-1.4, 1.4),
      vy: vy * rand(0.25, 0.75) + rand(-1.4, 1.4),
      life: 1, decay: rand(0.012, 0.03), r: rand(0.5, 1.9),
    };
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, CFG.maxDPR);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const count = Math.min(CFG.grainCap,
      Math.max(110, Math.round((w * h) / 1e6 * CFG.grainsPerMegapixel)));
    grains = Array.from({ length: count }, () => makeGrain());
    streaks = Array.from({ length: 14 }, makeStreak);
    sparks = [];
  }

  /* ---- painting -------------------------------------------------------- */

  function paintSky(t) {
    const shimmer = Math.sin(t * 0.00007) * 0.5 + 0.5;
    const sky = ctx.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, "rgba(6,8,8,0)");
    sky.addColorStop(0.55, `rgba(14,20,20,${0.10 + shimmer * 0.05})`);
    sky.addColorStop(1, `rgba(38,26,14,${0.30 + shimmer * 0.06})`);
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, w, h);
  }

  function ridge(x, base, amp, freq, phase) {
    return base
      + Math.sin(x * freq + phase) * amp
      + Math.sin(x * freq * 0.43 + phase * 1.7) * amp * 0.45
      + Math.sin(x * freq * 2.10 + phase * 0.6) * amp * 0.12;
  }

  /** The nearest ridge dips under the cursor, so the terrain feels the pointer. */
  function ridgeNear(x, base, amp, freq, phase) {
    let y = ridge(x, base, amp, freq, phase);
    if (P.active) {
      const d = Math.abs(x - P.x);
      if (d < 230) y += (1 - d / 230) ** 2 * 14 * (0.35 + P.power);
    }
    return y;
  }

  function paintDunes(t) {
    const layers = [
      { base: 0.74, amp: 0.075, freq: 0.0034, speed: 0.000012, fill: "rgba(58,42,24,0.30)", near: false },
      { base: 0.82, amp: 0.060, freq: 0.0050, speed: -0.000021, fill: "rgba(74,52,28,0.34)", near: false },
      { base: 0.90, amp: 0.042, freq: 0.0072, speed: 0.000034, fill: "rgba(92,64,34,0.34)", near: false },
      { base: 0.97, amp: 0.028, freq: 0.0098, speed: -0.000048, fill: "rgba(108,76,40,0.32)", near: true },
    ];
    for (const l of layers) {
      const phase = t * l.speed * (1 + wind * 0.5);
      const base = h * l.base, amp = h * l.amp;
      const at = l.near ? ridgeNear : ridge;

      ctx.beginPath();
      ctx.moveTo(-10, h + 10);
      ctx.lineTo(-10, base);
      for (let x = -10; x <= w + 10; x += 6) ctx.lineTo(x, at(x, base, amp, l.freq, phase));
      ctx.lineTo(w + 10, h + 10);
      ctx.closePath();
      ctx.fillStyle = l.fill;
      ctx.fill();

      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.beginPath();
      for (let x = -10; x <= w + 10; x += 6) {
        const y = at(x, base, amp, l.freq, phase);
        x === -10 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.strokeStyle = "rgba(196,164,100,0.055)";
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.restore();
    }
  }

  function gustAt(x, t) {
    const a = Math.sin((x * 0.0016) - t * 0.00042);
    const b = Math.sin((x * 0.0007) + t * 0.00019);
    return Math.max(0, a * 0.6 + b * 0.4);
  }

  /** Shove, curl and drag a grain that is inside the pointer's influence. */
  function applyPointer(g) {
    if (!P.active) return;
    const dx = g.x - P.x, dy = g.y - P.y;
    const dist2 = dx * dx + dy * dy;
    const R = CFG.pointerRadius;
    if (dist2 > R * R) return;

    const dist = Math.sqrt(dist2) || 0.001;
    const fall = (1 - dist / R) ** 2;   // smooth falloff to the edge
    const near = 0.35 + g.z;            // near grains react more than far ones
    const nx = dx / dist, ny = dy / dist;
    const spin = P.vx >= 0 ? 1 : -1;

    g.vx += nx * fall * CFG.pushStrength * near;      // radial: out of the way
    g.vy += ny * fall * CFG.pushStrength * near;
    g.vx += -ny * fall * CFG.swirl * near * spin;     // tangential: the wake curls
    g.vy += nx * fall * CFG.swirl * near * spin;
    g.vx += P.vx * fall * CFG.dragStrength * near;    // drag: carried along
    g.vy += P.vy * fall * CFG.dragStrength * near;
  }

  function paintGrains(t) {
    for (const g of grains) {
      applyPointer(g);

      const gust = gustAt(g.x, t) * (0.5 + wind);
      const windX = (wind + gust * 0.9) * g.speed + burst * g.z * 2.2;

      g.x += windX + g.vx;
      g.y += g.drift * 0.25 + Math.sin(t * 0.0009 + g.phase) * 0.28 * g.wobble
             - wind * 0.05 + g.vy;

      // Imparted velocity bleeds off, so the field settles after a swipe.
      g.vx *= 0.90;
      g.vy *= 0.90;

      if (g.x > w + 50) { Object.assign(g, makeGrain(-40)); continue; }
      if (g.x < -50) { Object.assign(g, makeGrain(w + 40)); continue; }
      if (g.y < -30) g.y = h + 20;
      if (g.y > h + 30) g.y = -20;

      const motion = windX + g.vx;
      const smear = Math.min(12, Math.abs(motion) * 2.4);
      ctx.beginPath();
      if (smear > 1.6) {
        ctx.moveTo(g.x - motion * 2.2, g.y - g.vy * 1.4);
        ctx.lineTo(g.x, g.y);
        ctx.strokeStyle = `rgba(206,176,112,${g.alpha * (0.7 + wind * 0.15)})`;
        ctx.lineWidth = g.r;
        ctx.stroke();
      } else {
        ctx.arc(g.x, g.y, g.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(206,176,112,${g.alpha})`;
        ctx.fill();
      }
    }
  }

  function paintSparks() {
    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i];
      s.x += s.vx; s.y += s.vy;
      s.vx *= 0.95; s.vy = s.vy * 0.95 + 0.045;   // settle under a little gravity
      s.life -= s.decay;
      if (s.life <= 0) { sparks.splice(i, 1); continue; }
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r * s.life, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(226,198,140,${0.45 * s.life})`;
      ctx.fill();
    }
  }

  function paintPointerDust() {
    if (!P.active || P.power < 0.02) return;
    // A soft halo keeps the cursor's influence legible even over empty sky.
    const r = CFG.pointerRadius * (0.55 + P.power * 0.5);
    const halo = ctx.createRadialGradient(P.x, P.y, 0, P.x, P.y, r);
    halo.addColorStop(0, `rgba(206,176,112,${0.055 * P.power})`);
    halo.addColorStop(0.55, `rgba(206,176,112,${0.024 * P.power})`);
    halo.addColorStop(1, "rgba(206,176,112,0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(P.x, P.y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  function paintStreaks(t) {
    ctx.lineWidth = 1;
    for (const s of streaks) {
      s.x += (wind * 6 + gustAt(s.x, t) * 8) * s.speed * 0.5 + burst * 9;
      if (s.x - s.len > w + 60) Object.assign(s, makeStreak(), { x: -s.len - 40 });
      const grad = ctx.createLinearGradient(s.x - s.len, s.y, s.x, s.y + s.tilt);
      grad.addColorStop(0, "rgba(206,176,112,0)");
      grad.addColorStop(0.5, `rgba(206,176,112,${s.alpha * (0.6 + wind * 0.3)})`);
      grad.addColorStop(1, "rgba(206,176,112,0)");
      ctx.strokeStyle = grad;
      ctx.beginPath();
      ctx.moveTo(s.x - s.len, s.y);
      ctx.lineTo(s.x, s.y + s.tilt);
      ctx.stroke();
    }
  }

  function paintHaze() {
    const haze = ctx.createLinearGradient(0, h * 0.5, 0, h);
    const density = 0.05 + Math.min(0.22, (wind - CFG.baseWind) * 0.11);
    haze.addColorStop(0, "rgba(150,110,60,0)");
    haze.addColorStop(1, `rgba(150,110,60,${density})`);
    ctx.fillStyle = haze;
    ctx.fillRect(0, h * 0.5, w, h * 0.5);
  }

  /* ---- loop ------------------------------------------------------------ */

  function updatePointer() {
    // Smooth the cursor velocity; raw frame deltas make the wake stutter.
    const dx = P.x - P.px, dy = P.y - P.py;
    P.vx += (dx - P.vx) * 0.35;
    P.vy += (dy - P.vy) * 0.35;
    P.px = P.x; P.py = P.y;
    P.speed = Math.hypot(P.vx, P.vy);
    P.power += (Math.min(1, P.speed / 18) - P.power) * 0.12;

    // Fast movement throws sand up off the surface.
    if (P.active && P.speed > CFG.kickSpeed) {
      const n = Math.min(CFG.kickMax, Math.round((P.speed - CFG.kickSpeed) / 5) + 1);
      for (let i = 0; i < n; i++) {
        sparks.push(makeSpark(P.x + rand(-14, 14), P.y + rand(-14, 14),
                              P.vx * 0.5, P.vy * 0.5));
      }
      if (sparks.length > CFG.sparkCap) sparks.splice(0, sparks.length - CFG.sparkCap);
    }
  }

  function frame(t) {
    wind += (target - wind) * CFG.surgeRamp;
    burst *= 0.94;
    updatePointer();

    ctx.clearRect(0, 0, w, h);
    paintSky(t);
    paintDunes(t);
    paintStreaks(t);
    paintPointerDust();
    paintGrains(t);
    paintSparks();
    paintHaze();

    raf = requestAnimationFrame(frame);
  }

  function paintStatic() {
    ctx.clearRect(0, 0, w, h);
    paintSky(0);
    paintDunes(0);
    paintHaze();
  }

  const start = () => {
    if (!running && !reduced.matches) { running = true; raf = requestAnimationFrame(frame); }
  };
  const stop = () => { running = false; cancelAnimationFrame(raf); };

  /* ---- public control -------------------------------------------------- */

  window.Sandstorm = {
    surge() { target = CFG.surgeWind; },
    settle() { target = CFG.baseWind; },
    gust(strength = 1) { burst = Math.max(burst, 0.9 * strength); },
    /** Throw sand at a point — used when a question is submitted. */
    kick(x, y, n = 26) {
      for (let i = 0; i < n; i++) {
        sparks.push(makeSpark(x + rand(-26, 26), y + rand(-16, 16), rand(-5, 5), rand(-5, 2)));
      }
      if (sparks.length > CFG.sparkCap) sparks.splice(0, sparks.length - CFG.sparkCap);
    },
    /** Exposed for the UI test and for tuning from the console. */
    _state: () => ({ wind, target, pointer: { ...P }, grains: grains.length, sparks: sparks.length }),
  };

  /* ---- wiring ---------------------------------------------------------- */

  resize();
  window.addEventListener("resize", resize, { passive: true });

  function trackPointer(clientX, clientY) {
    // Seed the previous position on entry, or the first frame reads as a huge
    // velocity and flings the whole field.
    if (!P.active) { P.px = clientX; P.py = clientY; }
    P.x = clientX; P.y = clientY; P.active = true;
  }

  window.addEventListener("pointermove", (e) => trackPointer(e.clientX, e.clientY), { passive: true });
  window.addEventListener("pointerdown", (e) => {
    trackPointer(e.clientX, e.clientY);
    window.Sandstorm.gust(0.8);
    window.Sandstorm.kick(e.clientX, e.clientY, 20);
  }, { passive: true });
  window.addEventListener("pointerleave", () => { P.active = false; P.power = 0; }, { passive: true });
  // Touch drives the same field.
  window.addEventListener("touchmove", (e) => {
    const touch = e.touches[0];
    if (touch) trackPointer(touch.clientX, touch.clientY);
  }, { passive: true });

  document.addEventListener("visibilitychange", () => { document.hidden ? stop() : start(); });
  reduced.addEventListener?.("change", () => { stop(); reduced.matches ? paintStatic() : start(); });

  reduced.matches ? paintStatic() : start();
})();

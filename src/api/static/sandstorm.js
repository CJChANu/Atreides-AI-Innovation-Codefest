/* Arrakis sandstorm.
 *
 * A canvas layer behind the archive UI. Three ideas make it feel like weather
 * rather than decoration:
 *
 *   1. Depth. Grains carry a `z` in 0..1 that drives size, opacity, speed and
 *      parallax together, so the field reads as a volume rather than a sheet.
 *   2. Gusts. Wind is a base value plus travelling gust envelopes, so the storm
 *      breathes instead of scrolling uniformly.
 *   3. State. The storm answers the application: it surges while an
 *      investigation runs and settles when the answer lands, so the motion is
 *      feedback rather than noise.
 *
 * It is also required to get out of the way — it honours prefers-reduced-motion,
 * sleeps when the tab is hidden, and scales its particle count to the viewport.
 */
(() => {
  "use strict";

  const canvas = document.getElementById("sandCanvas");
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext("2d", { alpha: true });

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  // Tunables kept together so the storm can be calmed in one place.
  const CFG = {
    maxDPR: 2,
    grainsPerMegapixel: 190,
    grainCap: 420,
    baseWind: 0.55,          // horizontal drift at rest
    surgeWind: 2.9,          // horizontal drift while investigating
    surgeRamp: 0.022,        // how fast the storm builds and settles
    pointerPull: 0.55,       // how much the cursor steers the wind
    horizon: 0.60,           // where the dune field starts, as a fraction of height
  };

  let w = 0, h = 0, dpr = 1;
  let grains = [];
  let streaks = [];
  let raf = 0;
  let running = false;

  // Storm state. `target` is what the app asks for; `wind` chases it, so mode
  // changes ease instead of snapping.
  let wind = CFG.baseWind;
  let target = CFG.baseWind;
  let pointerX = 0.5, pointerY = 0.5, pointerActive = false;
  let burst = 0;   // decaying impulse from a click

  const rand = (a, b) => a + Math.random() * (b - a);

  function makeGrain(seedX) {
    const z = Math.random();                 // 0 = far, 1 = near
    return {
      x: seedX === undefined ? rand(-40, w + 40) : seedX,
      y: rand(h * (CFG.horizon - 0.12), h * 1.02),
      z,
      r: 0.25 + z * 1.5,
      speed: 0.25 + z * 1.5,
      drift: rand(-0.5, 0.5),
      alpha: 0.05 + z * 0.30,
      phase: Math.random() * Math.PI * 2,
      wobble: 0.2 + Math.random() * 0.7,
    };
  }

  function makeStreak() {
    const z = Math.random();
    return {
      x: rand(-300, w),
      y: rand(h * CFG.horizon, h * 0.99),
      len: rand(90, 320) * (0.5 + z),
      z,
      speed: 0.6 + z * 2.4,
      alpha: 0.03 + z * 0.09,
      tilt: rand(-4, 2),
    };
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, CFG.maxDPR);
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const megapixels = (w * h) / 1e6;
    const count = Math.min(CFG.grainCap, Math.max(70, Math.round(megapixels * CFG.grainsPerMegapixel)));
    grains = Array.from({ length: count }, () => makeGrain());
    streaks = Array.from({ length: 14 }, makeStreak);
  }

  /* ---- painting -------------------------------------------------------- */

  function paintSky(t) {
    // A very slow hue drift stops the backdrop reading as a flat fill.
    const shimmer = Math.sin(t * 0.00007) * 0.5 + 0.5;
    const sky = ctx.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, "rgba(6,8,8,0)");
    sky.addColorStop(0.55, `rgba(14,20,20,${0.10 + shimmer * 0.05})`);
    sky.addColorStop(1, `rgba(38,26,14,${0.30 + shimmer * 0.06})`);
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, w, h);
  }

  function paintDune(base, amp, freq, phase, colour) {
    ctx.beginPath();
    ctx.moveTo(-10, h + 10);
    ctx.lineTo(-10, base);
    for (let x = -10; x <= w + 10; x += 6) {
      const y = base
        + Math.sin(x * freq + phase) * amp
        + Math.sin(x * freq * 0.43 + phase * 1.7) * amp * 0.45
        + Math.sin(x * freq * 2.10 + phase * 0.6) * amp * 0.12;
      ctx.lineTo(x, y);
    }
    ctx.lineTo(w + 10, h + 10);
    ctx.closePath();
    ctx.fillStyle = colour;
    ctx.fill();
  }

  function paintDunes(t) {
    // Parallax: far dunes crawl, near dunes slide. Each layer also gets a faint
    // lit crest so the ridges read as three-dimensional.
    const layers = [
      { base: 0.74, amp: 0.075, freq: 0.0034, speed: 0.000012, fill: "rgba(58,42,24,0.30)" },
      { base: 0.82, amp: 0.060, freq: 0.0050, speed: -0.000021, fill: "rgba(74,52,28,0.34)" },
      { base: 0.90, amp: 0.042, freq: 0.0072, speed: 0.000034, fill: "rgba(92,64,34,0.34)" },
      { base: 0.97, amp: 0.028, freq: 0.0098, speed: -0.000048, fill: "rgba(108,76,40,0.32)" },
    ];
    for (const l of layers) {
      const phase = t * l.speed * (1 + wind * 0.5);
      paintDune(h * l.base, h * l.amp, l.freq, phase, l.fill);
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.beginPath();
      for (let x = -10; x <= w + 10; x += 6) {
        const y = h * l.base
          + Math.sin(x * l.freq + phase) * h * l.amp
          + Math.sin(x * l.freq * 0.43 + phase * 1.7) * h * l.amp * 0.45
          + Math.sin(x * l.freq * 2.10 + phase * 0.6) * h * l.amp * 0.12;
        x === -10 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.strokeStyle = "rgba(196,164,100,0.055)";
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.restore();
    }
  }

  function gustAt(x, t) {
    // Two travelling envelopes at different speeds. Where they overlap the wind
    // spikes, which is what produces irregular gusting rather than a pulse.
    const a = Math.sin((x * 0.0016) - t * 0.00042);
    const b = Math.sin((x * 0.0007) + t * 0.00019);
    return Math.max(0, a * 0.6 + b * 0.4);
  }

  function paintGrains(t) {
    const steer = pointerActive ? (pointerX - 0.5) * CFG.pointerPull : 0;
    for (const g of grains) {
      const gust = gustAt(g.x, t) * (0.5 + wind);
      const vx = (wind + gust * 0.9 + steer * (0.4 + g.z)) * g.speed + burst * g.z * 2.2;
      g.x += vx;
      g.y += g.drift * 0.25 + Math.sin(t * 0.0009 + g.phase) * 0.28 * g.wobble - wind * 0.05;

      if (g.x > w + 45) { Object.assign(g, makeGrain(-40)); continue; }
      if (g.x < -45) { Object.assign(g, makeGrain(w + 40)); continue; }
      if (g.y < h * (CFG.horizon - 0.16)) g.y = h * rand(0.72, 1.0);
      if (g.y > h * 1.04) g.y = h * rand(CFG.horizon, 0.8);

      // Faster grains smear into short streaks — the classic sand-in-motion read.
      const smear = Math.min(9, vx * 2.4);
      ctx.beginPath();
      if (smear > 1.6) {
        ctx.moveTo(g.x - smear, g.y);
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
    // Dust haze thickens with the wind, so a surge visibly obscures the horizon.
    const haze = ctx.createLinearGradient(0, h * CFG.horizon, 0, h);
    const density = 0.05 + Math.min(0.22, (wind - CFG.baseWind) * 0.11);
    haze.addColorStop(0, "rgba(150,110,60,0)");
    haze.addColorStop(1, `rgba(150,110,60,${density})`);
    ctx.fillStyle = haze;
    ctx.fillRect(0, h * CFG.horizon, w, h * (1 - CFG.horizon));
  }

  /* ---- loop ------------------------------------------------------------ */

  function frame(t) {
    wind += (target - wind) * CFG.surgeRamp;
    burst *= 0.94;

    ctx.clearRect(0, 0, w, h);
    paintSky(t);
    paintDunes(t);
    paintStreaks(t);
    paintGrains(t);
    paintHaze();

    raf = requestAnimationFrame(frame);
  }

  function paintStatic() {
    // Reduced-motion: the same desert, held still.
    ctx.clearRect(0, 0, w, h);
    paintSky(0);
    paintDunes(0);
    paintHaze();
  }

  function start() {
    if (running || reduced.matches) return;
    running = true;
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    running = false;
    cancelAnimationFrame(raf);
  }

  /* ---- public control -------------------------------------------------- */

  window.Sandstorm = {
    /** Ramp the storm up while the archive is being searched. */
    surge() { target = CFG.surgeWind; },
    /** Let the storm settle once an answer has landed. */
    settle() { target = CFG.baseWind; },
    /** A short impulse — used when a question is submitted. */
    gust(strength = 1) { burst = Math.max(burst, 0.9 * strength); },
  };

  /* ---- wiring ---------------------------------------------------------- */

  resize();
  window.addEventListener("resize", resize, { passive: true });

  window.addEventListener("pointermove", (e) => {
    pointerActive = true;
    pointerX = e.clientX / Math.max(w, 1);
    pointerY = e.clientY / Math.max(h, 1);
  }, { passive: true });
  window.addEventListener("pointerleave", () => { pointerActive = false; }, { passive: true });
  window.addEventListener("pointerdown", () => window.Sandstorm.gust(0.7), { passive: true });

  document.addEventListener("visibilitychange", () => {
    // A background tab should cost nothing.
    document.hidden ? stop() : start();
  });

  reduced.addEventListener?.("change", () => {
    stop();
    reduced.matches ? paintStatic() : start();
  });

  reduced.matches ? paintStatic() : start();
})();

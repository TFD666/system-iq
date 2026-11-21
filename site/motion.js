/* ============================================================================
   System IQ — motion.js
   Decorative motion layers. Load after script.js:
       <script src="motion.js" defer></script>

   Contains three things:
     1. Intro loader controller  (the CSS/markup live in intro.css / index.html)
     2. Hero cube field          (WebGL2, with a canvas-2D fallback)
     3. Try-it binary wave       (canvas 2D)

   Everything decorative is aria-hidden, never focusable, and is not created at
   all under prefers-reduced-motion. One requestAnimationFrame loop drives the
   whole page. Each layer pauses when offscreen and when the tab is hidden.

   No dependencies. No CDN. Plain ES5.
   ========================================================================== */
(function () {
  "use strict";

  var reduce = window.matchMedia &&
               window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var DPR = Math.min(window.devicePixelRatio || 1, 2);

  /* ── shared driver ──────────────────────────────────────────────────────
     One loop for the page. Adding a second rAF loop per animation is the
     usual way these pages end up janky.                                     */
  var layers = [], clock = 0, prev = performance.now(), started = false;

  function startLoop() {
    if (started) return;
    started = true;
    requestAnimationFrame(tick);
  }

  function tick(now) {
    requestAnimationFrame(tick);
    var dt = Math.min((now - prev) / 1000, 0.05);
    prev = now;
    if (document.hidden) return;          // no work for a tab nobody is looking at
    clock += dt;
    for (var i = 0; i < layers.length; i++) {
      if (layers[i].visible) layers[i].draw(clock);
    }
  }

  function register(el, layer) {
    layer.visible = true;
    layers.push(layer);
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) layer.visible = entries[i].isIntersecting;
      }, { rootMargin: "120px" }).observe(el);
    }
    startLoop();
  }

  function fitCanvas(c) {
    var w = Math.max(1, Math.round(c.clientWidth * DPR));
    var h = Math.max(1, Math.round(c.clientHeight * DPR));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; return true; }
    return false;
  }

  /* ========================================================================
     1 · INTRO LOADER
     Markup: <div id="intro"> ... <button class="intro__skip">Skip</button> </div>
     The page renders fully behind it from first paint. This is an overlay,
     never a gate.
     ====================================================================== */
  function initIntro() {
    var el = document.getElementById("intro");
    if (!el) return;

    // reduced motion: no intro at all
    if (reduce) { el.parentNode.removeChild(el); return; }

    var done = false, t0 = performance.now();

    function finish() {
      if (done) return;
      done = true;
      el.classList.add("is-out");
      setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 420);                                   // matches the CSS fade
    }

    // Exit as soon as the page is ready, but let the 1.6s animation read first.
    function whenReady() {
      setTimeout(finish, Math.max(0, 1600 - (performance.now() - t0)));
    }
    if (document.readyState === "complete") whenReady();
    else window.addEventListener("load", whenReady);

    setTimeout(finish, 5000);                    // hard ceiling, never a target

    ["click", "keydown", "wheel", "touchstart"].forEach(function (ev) {
      window.addEventListener(ev, finish, { once: true, passive: true });
    });
    var skip = el.querySelector(".intro__skip");
    if (skip) skip.addEventListener("click", finish);
  }

  /* ========================================================================
     2 · HERO CUBE FIELD
     Ordered lattice carved by a deterministic density mask: dense core,
     sparse tail. Every cube owns a grid slot, so they cannot intersect.

     Clearance proof — do not loosen these numbers:
       SPACING 1.4, largest cube 0.72, diagonal 0.72 * sqrt(3) = 1.247.
       Two maximum-size neighbours need 1.247 and have 1.4  -> 0.153 spare.
       Per-cube bob is 0.04, so a pair can close at most 0.08.
       The breathing scale only ever expands (1.00 -> 1.18).
     ====================================================================== */
  var LAT = { x: 6, y: 5, z: 4 };
  var SPACING = 1.4, CUBE_MIN = 0.38, CUBE_MAX = 0.72;

  function hash3(a, b, c) {
    var n = Math.sin(a * 127.1 + b * 311.7 + c * 74.7) * 43758.5453;
    return n - Math.floor(n);
  }

  function buildLattice() {
    var out = [];
    for (var ix = 0; ix < LAT.x; ix++) {
      for (var iy = 0; iy < LAT.y; iy++) {
        for (var iz = 0; iz < LAT.z; iz++) {
          var px = (ix - (LAT.x - 1) / 2) * SPACING;
          var py = (iy - (LAT.y - 1) / 2) * SPACING;
          var pz = (iz - (LAT.z - 1) / 2) * SPACING;

          var dx = px + 0.7, dy = py - 0.6, dz = pz;     // core sits up and left
          var dist = Math.sqrt(dx * dx + dy * dy * 1.15 + dz * dz * 0.95);

          var dens = 1.30 - dist / 3.9;
          var tail = dx * 0.42 - dy * 0.30;              // trail toward lower-right
          if (tail > 0) dens += tail * 0.17;

          if (hash3(ix, iy, iz) > dens) continue;        // slot stays empty

          var sz = CUBE_MIN + hash3(ix + 7.3, iy + 13.1, iz + 5.7) * (CUBE_MAX - CUBE_MIN);
          out.push(px, py, pz, sz, ix * 0.8 + iy * 1.35 + iz * 2.05);
        }
      }
    }
    return new Float32Array(out);
  }

  var VERT = [
    "#version 300 es",
    "in vec3 aPos; in vec3 aNor; in vec3 iOff; in vec2 iMeta;",
    "uniform mat4 uProj; uniform float uTime;",
    "out vec3 vN; out vec3 vLN; out vec3 vLP; out vec3 vP; out float vSeed; out float vZ;",
    "mat3 rotY(float a){float s=sin(a),c=cos(a);return mat3(c,0.,-s, 0.,1.,0., s,0.,c);}",
    "mat3 rotX(float a){float s=sin(a),c=cos(a);return mat3(1.,0.,0., 0.,c,s, 0.,-s,c);}",
    "void main(){",
    "  float sc = iMeta.x, ph = iMeta.y;",
    "  float breathe = 1.0 + 0.18 * (0.5 + 0.5 * sin(uTime * 0.085));",
    "  vec3 w = iOff * breathe;",
    "  w.y += sin(uTime * 0.33 + ph) * 0.04;",
    "  w.x += cos(uTime * 0.27 + ph * 0.8) * 0.04;",
    "  w.x += sin(uTime * 0.047) * 0.55;",            // global drift: cannot change spacing
    "  w.y += cos(uTime * 0.039) * 0.32;",
    "  mat3 R = rotY(uTime * 0.11 + ph) * rotX(uTime * 0.075 + ph * 0.7);",
    "  mat3 F = rotY(uTime * 0.058) * rotX(-0.22 + sin(uTime * 0.028) * 0.13);",
    "  vec3 p = F * (R * (aPos * sc) + w);",
    "  p.z -= 10.5;",
    "  vN = normalize(F * R * aNor); vLN = aNor; vLP = aPos; vP = p; vSeed = ph; vZ = -p.z;",
    "  gl_Position = uProj * vec4(p, 1.0);",
    "}"
  ].join("\n");

  var FRAG = [
    "#version 300 es",
    "precision highp float;",
    "in vec3 vN; in vec3 vLN; in vec3 vLP; in vec3 vP; in float vSeed; in float vZ;",
    "uniform float uTime; out vec4 frag;",
    "float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }",
    "void main(){",
    "  vec3 an = abs(vLN); vec2 uv; float faceId;",
    "  if (an.x > 0.5)      { uv = vLP.zy; faceId = vLN.x > 0.0 ? 0.0 : 1.0; }",
    "  else if (an.y > 0.5) { uv = vLP.xz; faceId = vLN.y > 0.0 ? 2.0 : 3.0; }",
    "  else                 { uv = vLP.xy; faceId = vLN.z > 0.0 ? 4.0 : 5.0; }",
    "  const float CELLS = 4.0;",
    "  vec2 g = (uv + 0.5) * CELLS; vec2 cell = floor(g); vec2 f = fract(g);",
    "  float seam = min(min(f.x, 1.0 - f.x), min(f.y, 1.0 - f.y));",
    "  float panel = smoothstep(0.0, 0.055, seam);",
    "  float h = hash(cell + faceId * 17.3 + floor(vSeed * 97.0) * 3.1);",
    "  float lit = step(0.80, h);",
    "  float pulse = 0.55 + 0.45 * sin(uTime * 1.25 + vSeed * 23.0 + h * 6.2831);",
    "  float edge = smoothstep(0.0, 0.14, 0.5 - max(abs(uv.x), abs(uv.y)));",
    "  vec3 N = normalize(vN), V = normalize(-vP), L = normalize(vec3(0.35,0.85,0.45));",
    "  vec3 H = normalize(L + V);",
    "  float ndl = max(dot(N,L),0.0);",
    "  float spec = pow(max(dot(N,H),0.0), 54.0);",
    "  float fres = pow(1.0 - max(dot(N,V),0.0), 3.2);",
    "  vec3 R = reflect(-V, N);",
    "  float env = smoothstep(-0.55, 0.95, R.y);",
    "  vec3 col = vec3(0.044,0.044,0.050) * (0.30 + ndl * 0.70);",
    "  col += vec3(0.52,0.50,0.48) * env * 0.26;",
    "  col += vec3(1.00,0.97,0.92) * spec * 0.95;",
    "  col += vec3(0.55,0.42,0.28) * fres * 0.45;",
    "  col *= mix(0.30, 1.0, panel);",
    "  col *= mix(0.50, 1.0, edge);",
    "  vec3 glow = vec3(0.98, 0.52, 0.12);",
    "  float emit = lit * panel * pulse;",
    "  col = mix(col, glow * 1.35, emit * 0.92);",
    "  col += glow * emit * 0.32;",
    "  float fog = clamp((vZ - 7.0) / 7.5, 0.0, 1.0);",
    "  frag = vec4(mix(col, vec3(0.035,0.043,0.055), fog), 1.0);",
    "}"
  ].join("\n");

  function cubeGeometry() {
    var faces = [
      [[ 1,0,0],[.5,-.5,-.5],[.5,.5,-.5],[.5,.5,.5],[.5,-.5,.5]],
      [[-1,0,0],[-.5,-.5,.5],[-.5,.5,.5],[-.5,.5,-.5],[-.5,-.5,-.5]],
      [[0, 1,0],[-.5,.5,-.5],[-.5,.5,.5],[.5,.5,.5],[.5,.5,-.5]],
      [[0,-1,0],[-.5,-.5,.5],[-.5,-.5,-.5],[.5,-.5,-.5],[.5,-.5,.5]],
      [[0,0, 1],[-.5,-.5,.5],[.5,-.5,.5],[.5,.5,.5],[-.5,.5,.5]],
      [[0,0,-1],[.5,-.5,-.5],[-.5,-.5,-.5],[-.5,.5,-.5],[.5,.5,-.5]]
    ];
    var out = [], tri = [0,1,2, 0,2,3];
    for (var i = 0; i < faces.length; i++) {
      var n = faces[i][0], q = [faces[i][1], faces[i][2], faces[i][3], faces[i][4]];
      for (var t = 0; t < tri.length; t++) {
        var v = q[tri[t]];
        out.push(v[0], v[1], v[2], n[0], n[1], n[2]);
      }
    }
    return new Float32Array(out);
  }

  function perspective(fovy, aspect, near, far) {
    var f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([
      f / aspect,0,0,0,  0,f,0,0,
      0,0,(far + near) * nf,-1,  0,0,2 * far * near * nf,0
    ]);
  }

  function initCubes() {
    var canvas = document.getElementById("hero-cubes");
    if (!canvas || reduce) return;

    var data = buildLattice(), count = data.length / 5;
    var gl = canvas.getContext("webgl2", { antialias: true, alpha: true, powerPreference: "low-power" });

    if (gl) {
      var sh = function (src, type) {
        var s = gl.createShader(type);
        gl.shaderSource(s, src); gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.warn(gl.getShaderInfoLog(s)); return null; }
        return s;
      };
      var vs = sh(VERT, gl.VERTEX_SHADER), fs = sh(FRAG, gl.FRAGMENT_SHADER);
      if (vs && fs) {
        var prog = gl.createProgram();
        gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
        if (gl.getProgramParameter(prog, gl.LINK_STATUS)) {
          var geo = cubeGeometry(), verts = geo.length / 6;
          var vao = gl.createVertexArray();
          gl.bindVertexArray(vao);

          var vb = gl.createBuffer();
          gl.bindBuffer(gl.ARRAY_BUFFER, vb);
          gl.bufferData(gl.ARRAY_BUFFER, geo, gl.STATIC_DRAW);
          var aPos = gl.getAttribLocation(prog, "aPos"), aNor = gl.getAttribLocation(prog, "aNor");
          gl.enableVertexAttribArray(aPos); gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 24, 0);
          gl.enableVertexAttribArray(aNor); gl.vertexAttribPointer(aNor, 3, gl.FLOAT, false, 24, 12);

          var ib = gl.createBuffer();
          gl.bindBuffer(gl.ARRAY_BUFFER, ib);
          gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
          var iOff = gl.getAttribLocation(prog, "iOff"), iMeta = gl.getAttribLocation(prog, "iMeta");
          gl.enableVertexAttribArray(iOff);  gl.vertexAttribPointer(iOff, 3, gl.FLOAT, false, 20, 0);  gl.vertexAttribDivisor(iOff, 1);
          gl.enableVertexAttribArray(iMeta); gl.vertexAttribPointer(iMeta, 2, gl.FLOAT, false, 20, 12); gl.vertexAttribDivisor(iMeta, 1);

          gl.bindVertexArray(null);
          var uProj = gl.getUniformLocation(prog, "uProj");
          var uTime = gl.getUniformLocation(prog, "uTime");
          gl.enable(gl.DEPTH_TEST);
          gl.clearColor(0, 0, 0, 0);

          register(canvas, { draw: function (t) {
            if (fitCanvas(canvas)) gl.viewport(0, 0, canvas.width, canvas.height);
            gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
            gl.useProgram(prog);
            gl.bindVertexArray(vao);
            gl.uniformMatrix4fv(uProj, false, perspective(0.92, canvas.width / canvas.height, 0.1, 40));
            gl.uniform1f(uTime, t);
            gl.drawArraysInstanced(gl.TRIANGLES, 0, verts, count);
            gl.bindVertexArray(null);
          }});
          return;
        }
      }
    }

    /* ── canvas-2D fallback: same lattice, flattened. Without this, a machine
       that refuses WebGL gets an empty hero.                                */
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    register(canvas, { draw: function (t) {
      fitCanvas(canvas);
      var w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      for (var i = count - 1; i >= 0; i--) {
        var px = data[i*5], py = data[i*5+1], pz = data[i*5+2],
            sz = data[i*5+3], ph = data[i*5+4];
        var depth = 1 + (pz + 3) * 0.16, sc = 1 / depth;
        var x = w * 0.5 + (px + Math.sin(t * 0.047) * 0.55) * sc * w * 0.10;
        var y = h * 0.5 + (py + Math.cos(t * 0.039) * 0.32) * sc * h * 0.15;
        var s  = sz * sc * Math.min(w, h) * 0.19;
        ctx.save();
        ctx.translate(x, y); ctx.rotate(t * 0.11 + ph);
        ctx.fillStyle = "rgba(150,150,160," + (0.10 + sc * 0.26).toFixed(3) + ")";
        ctx.fillRect(-s / 2, -s / 2, s, s);
        ctx.fillStyle = "rgba(250,133,31," + (0.20 + sc * 0.40).toFixed(3) + ")";
        ctx.fillRect(-s / 2, -s / 2, s * 0.26, s * 0.26);
        ctx.restore();
      }
    }});
  }

  /* ========================================================================
     3 · TRY-IT BINARY WAVE  (canvas 2D)
     A perspective grid of 0s and 1s on a sine-displaced surface, gliding
     forward, brightness falling off with depth.
     Kept at low alpha: the command text in front of it is the most-read
     copy on the page.
     ====================================================================== */
  var COLS = 34, ROWS = 20, FOCAL = 2.5;

  function initWave() {
    var canvas = document.getElementById("try-wave");
    if (!canvas || reduce) return;
    var ctx = canvas.getContext("2d");
    if (!ctx) return;

    var digits = [];
    for (var r = 0; r < ROWS + 2; r++) {
      digits[r] = [];
      for (var c = 0; c < COLS; c++) digits[r][c] = Math.random() < 0.5 ? "0" : "1";
    }
    var lastFlip = 0;

    register(canvas, { draw: function (t) {
      fitCanvas(canvas);
      var w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      // flip a few digits every 100ms, not every frame: per-frame churn reads
      // as static noise and costs more for a worse result
      if (t - lastFlip > 0.1) {
        lastFlip = t;
        for (var k = 0; k < 10; k++) {
          digits[(Math.random() * (ROWS + 2)) | 0][(Math.random() * COLS) | 0] =
            Math.random() < 0.5 ? "0" : "1";
        }
      }

      var cx = w * 0.30, cy = h * 0.46, glide = (t * 0.55) % 1;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      for (var r = ROWS; r >= 0; r--) {
        var depth = 1.05 + (r + glide) * 0.42;
        var sc = FOCAL / depth;
        var fade = 1 - (r + glide) / (ROWS + 1);
        if (fade <= 0.02) continue;
        var alpha = Math.pow(fade, 1.7) * 0.95;
        var fontPx = Math.max(5, 16 * DPR * sc);
        ctx.font = "600 " + fontPx.toFixed(1) + "px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

        for (var c = 0; c < COLS; c++) {
          var wx = (c - COLS / 2) * 0.62;
          var wy = Math.sin((c * 0.42) + (r + glide) * 0.30 + t * 1.15) * 0.52
                 + Math.sin((c * 0.17) - (r + glide) * 0.21 - t * 0.68) * 0.34;
          var sx = cx + wx * sc * (w * 0.19);
          var sy = cy + (wy + 1.15) * sc * (h * 0.30);
          if (sx < -40 || sx > w + 40 || sy < -40 || sy > h + 40) continue;
          var a = alpha * (0.42 + 0.58 * ((wy + 0.9) / 1.8));
          if (a <= 0.02) continue;
          ctx.fillStyle = "rgba(56,189,248," + a.toFixed(3) + ")";
          ctx.fillText(digits[r][c], sx, sy);
        }
      }
    }});
  }

  /* ── go ─────────────────────────────────────────────────────────────── */
  initIntro();
  initCubes();
  initWave();

  window.addEventListener("resize", function () {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
  });
})();

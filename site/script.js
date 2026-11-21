var API_URL                = "https://systemiq-api-pbwg.onrender.com";
var CHECK_TIMEOUT_SECONDS  = 5;
var MAX_WAIT_SECONDS       = 240;
var RETRY_FAST_SECONDS     = 5;
var RETRY_MID_SECONDS      = 10;
var RETRY_SLOW_SECONDS     = 15;
var RETRY_FAST_ATTEMPTS    = 6;
var RETRY_MID_ATTEMPTS     = 6;
var KEEPALIVE_MINUTES      = 10;
var KEEPALIVE_MAX_MINUTES  = 30;

/* First act — enables .has-js reveal rules before first paint */
document.documentElement.classList.add("has-js");

/* Scroll-reveal via IntersectionObserver */
(function initReveal() {
  var prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReduced) return;
  if (!("IntersectionObserver" in window)) return;

  var options = { threshold: 0.12, rootMargin: "0px 0px -40px 0px" };
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-in");
        observer.unobserve(entry.target);
      }
    });
  }, options);

  document.querySelectorAll(".reveal").forEach(function (el) {
    observer.observe(el);
  });
})();

/* Hero stagger — after intro exits (~1700ms) or quickly if no intro */
(function initHeroReveal() {
  var prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReduced) return;

  var intro = document.getElementById("intro");
  var delay = intro ? 1700 : 100;

  setTimeout(function () {
    document.querySelectorAll(".hero__reveal").forEach(function (el) {
      el.classList.add("is-in");
    });
  }, delay);
})();

/* Hero terminal typing — once per page load */
(function initTermAnim() {
  var prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReduced) return;
  if (!("IntersectionObserver" in window)) return;

  var term = document.querySelector(".hero__term");
  if (!term) return;

  var clip = term.querySelector(".term__cmd-clip");
  if (clip) {
    clip.addEventListener("transitionend", function () {
      term.classList.add("is-done");
    }, { once: true });
  }

  var observer = new IntersectionObserver(function (entries) {
    if (entries[0].isIntersecting) {
      term.classList.add("is-running");
      observer.disconnect();
    }
  }, { threshold: 0.3 });
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      observer.observe(term);
    });
  });
})();

/* Status line */
(function initStatus() {
  var dot = document.querySelector(".status__dot");
  var text = document.getElementById("status-text");
  if (!dot || !text) return;

  var FAIL_MSG = "The demo server is not answering right now. The samples below always work. Try again in a few minutes.";
  var WAKE_MSG = "Waking the demo server. This can take a minute or two. The samples below work meanwhile.";

  var state = "waiting";
  var attempts = 0;
  var startTime = Date.now();
  var readyTime = 0;
  var active = false;
  var retryTimer = null;
  var keepaliveTimer = null;

  function setStatus(cls, msg) {
    dot.className = "status__dot status__dot--" + cls;
    text.textContent = msg;
  }

  /* gap after attempt N: 1-6 → 5 s, 7-12 → 10 s, 13+ → 15 s */
  function retryDelay() {
    if (attempts <= RETRY_FAST_ATTEMPTS) return RETRY_FAST_SECONDS * 1000;
    if (attempts <= RETRY_FAST_ATTEMPTS + RETRY_MID_ATTEMPTS) return RETRY_MID_SECONDS * 1000;
    return RETRY_SLOW_SECONDS * 1000;
  }

  function isTimedOut() {
    return (Date.now() - startTime) >= MAX_WAIT_SECONDS * 1000;
  }

  function resetAttempts() {
    attempts = 0;
    active = false;
  }

  function clearTimers() {
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
    if (keepaliveTimer) { clearTimeout(keepaliveTimer); keepaliveTimer = null; }
  }

  function healthz(cb) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, CHECK_TIMEOUT_SECONDS * 1000);
    fetch(API_URL + "/healthz", {
      signal: controller.signal,
      credentials: "omit",
      cache: "no-store"
    })
      .then(function (r) {
        clearTimeout(timer);
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then(function (data) {
        cb(data && data.status === "ok");
      })
      .catch(function () {
        clearTimeout(timer);
        cb(false);
      });
  }

  function scheduleKeepalive() {
    if (state !== "ready") return;
    keepaliveTimer = setTimeout(function () {
      keepaliveTimer = null;
      if (state !== "ready" || document.hidden) return;
      if (Date.now() - readyTime >= KEEPALIVE_MAX_MINUTES * 60000) {
        state = "stopped";
        return;
      }
      healthz(function (ok) {
        if (state !== "ready") return;
        if (ok) {
          scheduleKeepalive();
        } else {
          state = "waiting";
          startTime = Date.now(); // fresh budget — server blip should get full retry window
          resetAttempts();
          setStatus("warn", WAKE_MSG);
          check();
        }
      });
    }, KEEPALIVE_MINUTES * 60000);
  }

  function check() {
    if (state !== "waiting" || active || document.hidden) return;
    if (isTimedOut()) {
      state = "failed";
      setStatus("muted", FAIL_MSG);
      return;
    }
    active = true;
    attempts++;

    healthz(function (ok) {
      active = false;
      if (state !== "waiting") return;
      if (ok) {
        state = "ready";
        readyTime = Date.now();
        setStatus("ok", "Demo server ready");
        scheduleKeepalive();
      } else {
        if (isTimedOut()) {
          state = "failed";
          setStatus("muted", FAIL_MSG);
          return;
        }
        setStatus("warn", WAKE_MSG);
        var delay = retryDelay();
        retryTimer = setTimeout(function () {
          retryTimer = null;
          if (isTimedOut()) {
            state = "failed";
            setStatus("muted", FAIL_MSG);
            return;
          }
          check();
        }, delay);
      }
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      clearTimers();
      return;
    }
    if (state === "waiting" || state === "failed") {
      state = "waiting";
      startTime = Date.now(); // fresh budget — tab return deserves a full retry window
      resetAttempts();
      setStatus("accent", "Checking demo server…");
      check();
    } else if (state === "ready") {
      scheduleKeepalive();
    }
  });

  setStatus("accent", "Checking demo server…");
  check();
})();

/* Copy buttons */
(function initCopy() {
  var announce = document.getElementById("copy-announce");
  var buttons = document.querySelectorAll(".copy-btn");

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var targetId = btn.getAttribute("data-target");
      var codeEl = document.getElementById(targetId);
      if (!codeEl) return;

      var codeText = codeEl.textContent.replace(/^\$\s*/, "");

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(codeText).then(function () {
          showCopied(btn);
        }).catch(function () {
          fallbackSelect(codeEl);
        });
      } else {
        fallbackSelect(codeEl);
      }
    });
  });

  function showCopied(btn) {
    var label = btn.querySelector(".copy-btn__label");
    if (label) label.textContent = "COPIED";
    btn.classList.add("copy-btn--copied");
    if (announce) announce.textContent = "Copied to clipboard";
    setTimeout(function () {
      if (label) label.textContent = "COPY";
      btn.classList.remove("copy-btn--copied");
      if (announce) announce.textContent = "";
    }, 2000);
  }

  function fallbackSelect(el) {
    var range = document.createRange();
    range.selectNodeContents(el);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    if (announce) announce.textContent = "Text selected — press Ctrl+C to copy";
  }
})();


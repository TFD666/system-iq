/* ======================================================================
   System IQ — pipeline.js
   Auto-advancing "How it works" pipeline. Hover/focus holds a stage,
   click pins it. Pauses off-screen and when tab hidden. Degrades:
   no-JS shows all stages filled; reduced-motion skips auto-run.
   Load: <script src="pipeline.js" defer></script>
   ====================================================================== */

(function initPipeline() {
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var container = document.querySelector(".pipeline");
  if (!container) return;

  var stages = Array.prototype.slice.call(container.querySelectorAll(".stage"));
  if (!stages.length) return;

  var ADVANCE_MS = 1800;
  var LOOP_PAUSE_MS = 1200;
  var current = -1;
  var timer = null;
  var pinned = -1;
  var hovered = -1;
  var inView = true;
  var tabVisible = !document.hidden;

  function clear() {
    if (timer !== null) { clearTimeout(timer); timer = null; }
  }

  function activate(i) {
    for (var j = 0; j < stages.length; j++) {
      stages[j].classList.toggle("is-active", j === i);
    }
    current = i;
  }

  function canRun() {
    return pinned < 0 && hovered < 0 && inView && tabVisible && !reduced;
  }

  function advance() {
    clear();
    if (!canRun()) return;
    var next = (current + 1) % stages.length;
    activate(next);
    var delay = next === stages.length - 1 ? ADVANCE_MS + LOOP_PAUSE_MS : ADVANCE_MS;
    timer = setTimeout(advance, delay);
  }

  function resume() {
    if (!canRun()) return;
    clear();
    timer = setTimeout(advance, 400);
  }

  stages.forEach(function (stage, i) {
    stage.addEventListener("mouseenter", function () {
      hovered = i; clear(); activate(i);
    });
    stage.addEventListener("mouseleave", function () {
      hovered = -1;
      if (pinned < 0) resume();
    });
    stage.addEventListener("focus", function () {
      hovered = i; clear(); activate(i);
    });
    stage.addEventListener("blur", function () {
      hovered = -1;
      if (pinned < 0) resume();
    });

    stage.addEventListener("click", function () {
      if (pinned === i) {
        pinned = -1;
        stage.setAttribute("aria-pressed", "false");
        resume();
      } else {
        if (pinned >= 0) stages[pinned].setAttribute("aria-pressed", "false");
        pinned = i;
        stage.setAttribute("aria-pressed", "true");
        clear(); activate(i);
      }
    });

    stage.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && pinned === i) {
        pinned = -1;
        stage.setAttribute("aria-pressed", "false");
        resume();
      }
    });
  });

  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      inView = entries[0].isIntersecting;
      if (inView) resume(); else clear();
    }, { threshold: 0.2 }).observe(container);
  }

  document.addEventListener("visibilitychange", function () {
    tabVisible = !document.hidden;
    if (tabVisible) resume(); else clear();
  });

  if (!reduced) advance();
})();

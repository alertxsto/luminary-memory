// luminary-memory — minimal interactions
(function () {
  "use strict";

  // copy-to-clipboard for [data-copy]
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    // fallback
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    return Promise.resolve();
  }

  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-copy]");
    if (!el) return;
    var text = el.getAttribute("data-copy");
    if (!text) return;
    copyText(text).then(function () {
      var original = el.innerHTML;
      el.innerHTML = "copied ✓";
      setTimeout(function () { el.innerHTML = original; }, 1400);
    });
  });

  // subtle moon glow parallax (only when the user hasn't opted out of motion)
  var glow = document.querySelector(".moon-glow");
  if (glow && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var ticking = false;
    window.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        var y = window.scrollY;
        glow.style.transform = "translateY(" + y * 0.08 + "px)";
        ticking = false;
      });
    });
  }
})();

/**
 * Luminary Memory - Moonlit Editorial Interactions
 * - 1-Click Clipboard Copy with Visual Tooltip Feedback
 * - Terminal Tab Switching (Python API vs Terminal CLI)
 * - Live GitHub Stars Fetcher with Session Storage Caching
 * - Smooth Scroll Reveal via IntersectionObserver
 * - Ambient Moon Glow Parallax via IntersectionObserver (no scroll listener)
 * - Mobile Navigation Toggle
 * - Full Accessibility & Reduced Motion Support
 */

(function () {
  "use strict";

  document.documentElement.classList.add("js-enabled");

  var isReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ============================================================
  // 1. Copy-to-Clipboard with Visual Feedback
  // ============================================================
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.top = "-9999px";
        ta.style.left = "-9999px";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        var success = document.execCommand("copy");
        document.body.removeChild(ta);
        if (success) resolve();
        else reject(new Error("Copy command failed"));
      } catch (err) {
        reject(err);
      }
    });
  }

  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-copy]");
    if (!el) return;
    var text = el.getAttribute("data-copy");
    if (!text) return;

    var copyIndicator = el.querySelector(".install-copy, .qs-copy");
    var originalIndicator = copyIndicator ? copyIndicator.innerHTML : null;

    copyText(text).then(function () {
      if (copyIndicator) {
        copyIndicator.innerHTML = "✓";
        copyIndicator.style.color = "var(--ok)";
      } else {
        var prevText = el.getAttribute("data-original-text") || el.innerText;
        el.setAttribute("data-original-text", prevText);
        el.innerText = "Copied ✓";
      }

      setTimeout(function () {
        if (copyIndicator && originalIndicator !== null) {
          copyIndicator.innerHTML = originalIndicator;
          copyIndicator.style.color = "";
        } else if (el.hasAttribute("data-original-text")) {
          el.innerText = el.getAttribute("data-original-text");
          el.removeAttribute("data-original-text");
        }
      }, 1600);
    }).catch(function (err) {
      console.warn("Could not copy text: ", err);
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") {
      var el = document.activeElement && document.activeElement.closest("[data-copy]");
      if (el) {
        e.preventDefault();
        el.click();
      }
    }
  });

  // ============================================================
  // 2. Terminal Tab Switcher (Python API vs Terminal CLI)
  // ============================================================
  var tabButtons = document.querySelectorAll(".term-tab");
  var tabPanels = document.querySelectorAll(".term-panel");

  tabButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tabTarget = this.getAttribute("data-tab");

      tabButtons.forEach(function (b) {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      tabPanels.forEach(function (p) {
        p.classList.remove("active");
      });

      this.classList.add("active");
      this.setAttribute("aria-selected", "true");

      var targetPanel = document.getElementById("panel-" + tabTarget);
      if (targetPanel) {
        targetPanel.classList.add("active");
      }
    });
  });

  // ============================================================
  // 3. Live GitHub Stars Fetcher with Session Caching
  // ============================================================
  function formatStars(count) {
    if (count >= 1000) {
      return "★ " + (count / 1000).toFixed(1) + "k";
    }
    return "★ " + count;
  }

  function updateStarBadges(count) {
    var starElements = document.querySelectorAll("#nav-star-count, #cta-star-count");
    starElements.forEach(function (el) {
      el.textContent = formatStars(count);
    });
  }

  function fetchGitHubStars() {
    var repoKey = "luminary_github_stars";
    var cacheTimeKey = "luminary_github_stars_time";
    var cachedStars = null;
    var cachedTime = null;

    try {
      cachedStars = sessionStorage.getItem(repoKey);
      cachedTime = sessionStorage.getItem(cacheTimeKey);
    } catch (e) {
      // Ignore private browsing sessionStorage restrictions
    }

    var now = Date.now();

    if (cachedStars && cachedTime && (now - parseInt(cachedTime, 10) < 15 * 60 * 1000)) {
      updateStarBadges(parseInt(cachedStars, 10));
      return;
    }

    fetch("https://api.github.com/repos/alertxsto/luminary-memory")
      .then(function (res) {
        if (!res.ok) throw new Error("GitHub API status " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (data && typeof data.stargazers_count === "number") {
          updateStarBadges(data.stargazers_count);
          try {
            sessionStorage.setItem(repoKey, data.stargazers_count.toString());
            sessionStorage.setItem(cacheTimeKey, now.toString());
          } catch (e) {}
        }
      })
      .catch(function () {
        // Retain default fallback badge
      });
  }

  fetchGitHubStars();

  // ============================================================
  // 4. Scroll Reveal Animations (IntersectionObserver)
  // ============================================================
  var revealElements = document.querySelectorAll(".reveal-on-scroll");

  function revealAll() {
    revealElements.forEach(function (el) {
      el.classList.add("is-revealed");
    });
  }

  if (isReducedMotion || !("IntersectionObserver" in window)) {
    revealAll();
  } else {
    var revealObserver = new IntersectionObserver(
      function (entries, observer) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-revealed");
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.05,
        rootMargin: "0px 0px 60px 0px"
      }
    );

    revealElements.forEach(function (el) {
      revealObserver.observe(el);
    });

    setTimeout(function () {
      revealElements.forEach(function (el) {
        var rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight + 100) {
          el.classList.add("is-revealed");
        }
      });
    }, 60);
  }

  // ============================================================
  // 5. Ambient Moon Glow Parallax via IntersectionObserver
  //    (replaces banned window.addEventListener('scroll'))
  // ============================================================
  var glow = document.querySelector(".moon-glow");
  if (glow && !isReducedMotion && "IntersectionObserver" in window) {
    var parallaxObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            var rect = entry.boundingClientRect;
            var progress = 1 - (rect.top / window.innerHeight);
            progress = Math.max(0, Math.min(1, progress));
            glow.style.transform = "translateY(" + (progress * 30) + "px)";
          }
        });
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1] }
    );
    parallaxObserver.observe(document.body);
  }

  // ============================================================
  // 6. Mobile Navigation Toggle
  // ============================================================
  var navToggle = document.getElementById("nav-toggle");
  var navLinks = document.querySelector(".nav-links");

  if (navToggle && navLinks) {
    navToggle.addEventListener("click", function () {
      var isOpen = navLinks.classList.toggle("nav-open");
      navToggle.classList.toggle("open", isOpen);
      navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });

    navLinks.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        navLinks.classList.remove("nav-open");
        navToggle.classList.remove("open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
  }
})();

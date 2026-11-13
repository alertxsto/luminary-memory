(function () {
  "use strict";

  var root = document.documentElement;
  var themeButtons = document.querySelectorAll("[data-theme-toggle]");
  var theme = "dark";
  try {
    if (window.localStorage.getItem("luminary-theme") === "light") theme = "light";
  } catch (_) { /* Storage is optional in private or file contexts. */ }

  function applyTheme(value) {
    root.dataset.theme = value;
    themeButtons.forEach(function (button) {
      var label = value === "dark" ? "Switch to light theme" : "Switch to dark theme";
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      button.setAttribute("aria-pressed", String(value === "light"));
    });
  }
  applyTheme(theme);
  themeButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      theme = root.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(theme);
      try { window.localStorage.setItem("luminary-theme", theme); } catch (_) {}
    });
  });

  var menu = document.querySelector(".primary-nav");
  var menuToggle = document.querySelector(".menu-toggle");
  var mobileMenu = window.matchMedia("(max-width: 760px)");
  function setMenu(open, restoreFocus) {
    if (!menu || !menuToggle) return;
    menu.classList.toggle("is-open", open);
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    if (restoreFocus) menuToggle.focus();
  }
  if (menu && menuToggle) {
    menuToggle.addEventListener("click", function () {
      setMenu(menuToggle.getAttribute("aria-expanded") !== "true", false);
    });
    menu.addEventListener("click", function (event) {
      if (event.target.closest("a")) setMenu(false, false);
    });
    document.addEventListener("click", function (event) {
      if (!menu.contains(event.target) && !menuToggle.contains(event.target)) setMenu(false, false);
    });
    document.addEventListener("keydown", function (event) {
      if (menuToggle.getAttribute("aria-expanded") !== "true") return;
      if (event.key === "Escape") {
        setMenu(false, true);
      } else if (event.key === "Tab") {
        var links = menu.querySelectorAll("a");
        var first = links[0], last = links[links.length - 1];
        if (!first) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault(); menuToggle.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); menuToggle.focus();
        } else if (document.activeElement === menuToggle) {
          event.preventDefault(); (event.shiftKey ? last : first).focus();
        }
      }
    });
    mobileMenu.addEventListener("change", function () {
      if (!mobileMenu.matches) setMenu(false, false);
    });
  }

  var status = document.getElementById("toast") || document.createElement("div");
  if (!status.parentNode) {
    status.className = "site-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    document.body.appendChild(status);
  }
  var statusTimer;
  function announce(message) {
    status.textContent = message;
    status.classList.add("is-visible");
    window.clearTimeout(statusTimer);
    statusTimer = window.setTimeout(function () { status.classList.remove("is-visible"); }, 2200);
  }
  function fallbackCopy(value) {
    var area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var copied;
    try { copied = document.execCommand("copy"); } finally { area.remove(); }
    if (!copied) throw new Error("Clipboard unavailable");
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-site-copy]");
    if (!button) return;
    var value = button.getAttribute("data-site-copy") || "";
    var label = button.querySelector(".copy-label") || button;
    var original = button.getAttribute("data-copy-label") || label.textContent;
    button.setAttribute("data-copy-label", original);
    var operation = navigator.clipboard && window.isSecureContext
      ? navigator.clipboard.writeText(value).catch(function () { fallbackCopy(value); })
      : Promise.resolve().then(function () { fallbackCopy(value); });
    operation.then(function () {
      label.textContent = "Copied";
      button.classList.add("is-copied");
      announce("Copied to clipboard");
      window.clearTimeout(button.copyTimer);
      button.copyTimer = window.setTimeout(function () {
        label.textContent = original;
        button.classList.remove("is-copied");
      }, 1800);
    }).catch(function () { announce("Clipboard unavailable. Select and copy the code."); });
  });

  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-code-tab]"));
  function selectTab(tab, focus) {
    var selected = tab.getAttribute("data-code-tab");
    tabs.forEach(function (item) {
      var active = item === tab;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-selected", String(active));
      item.tabIndex = active ? 0 : -1;
    });
    document.querySelectorAll(".code-panel").forEach(function (panel) {
      var active = panel.id === "code-" + selected;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
    if (focus) tab.focus();
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () { selectTab(tab, false); });
    tab.addEventListener("keydown", function (event) {
      var target;
      if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") target = (index + tabs.length - 1) % tabs.length;
      if (event.key === "Home") target = 0;
      if (event.key === "End") target = tabs.length - 1;
      if (target === undefined) return;
      event.preventDefault();
      selectTab(tabs[target], true);
    });
  });

}());

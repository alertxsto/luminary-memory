(function () {
  "use strict";

  document.documentElement.classList.add("js-enabled");

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var toast = document.getElementById("toast");

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("is-visible");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(function () {
      toast.classList.remove("is-visible");
    }, 1800);
  }

  function copyText(value) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value);
    }

    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      try {
        if (!document.execCommand("copy")) {
          reject(new Error("Copy command failed"));
        } else {
          resolve();
        }
      } catch (error) {
        reject(error);
      } finally {
        document.body.removeChild(area);
      }
    });
  }

  document.addEventListener("click", function (event) {
    var copyButton = event.target.closest("[data-copy]");
    if (!copyButton) return;

    var label = copyButton.querySelector(".copy-label");
    var originalLabel = copyButton.getAttribute("data-default-label") || (label ? label.textContent : copyButton.textContent);
    copyButton.setAttribute("data-default-label", originalLabel);
    window.clearTimeout(copyButton.copyTimer);

    copyText(copyButton.getAttribute("data-copy")).then(function () {
      if (label) label.textContent = "Copied";
      copyButton.classList.add("is-copied");
      showToast("Copied to clipboard");
      copyButton.copyTimer = window.setTimeout(function () {
        if (label) label.textContent = originalLabel;
        copyButton.classList.remove("is-copied");
      }, 1500);
    }).catch(function () {
      showToast("Copy unavailable. Select the text manually.");
    });
  });

  var menuToggle = document.querySelector(".menu-toggle");
  var primaryNav = document.querySelector(".primary-nav");

  function setMenu(open, returnFocus) {
    if (!menuToggle || !primaryNav) return;
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    primaryNav.classList.toggle("is-open", open);
    if (!open && returnFocus) menuToggle.focus();
  }

  if (menuToggle && primaryNav) {
    menuToggle.addEventListener("click", function () {
      setMenu(menuToggle.getAttribute("aria-expanded") !== "true", false);
    });

    primaryNav.addEventListener("click", function (event) {
      if (event.target.closest("a")) setMenu(false, false);
    });

    document.addEventListener("click", function (event) {
      if (menuToggle.getAttribute("aria-expanded") !== "true") return;
      if (primaryNav.contains(event.target) || menuToggle.contains(event.target)) return;
      setMenu(false, false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || menuToggle.getAttribute("aria-expanded") !== "true") return;
      setMenu(false, true);
    });
  }

  var proofSteps = Array.prototype.slice.call(document.querySelectorAll(".proof-step"));
  var proofMessage = document.getElementById("proof-message");
  var proofCount = document.getElementById("proof-count");
  var proofState = document.getElementById("proof-state");
  var proofNext = document.getElementById("proof-next");
  var proofMessages = [
    "Observation is accepted as evidence-bearing input.",
    "Identity filters narrow the memory boundary before search.",
    "Four ranked signals meet in one fused candidate list.",
    "Weak, conflicting, or unsupported context is held back.",
    "Supported context returns with provenance, or the system abstains."
  ];
  var proofStates = [
    "Evidence-bearing input",
    "Ownership boundary applied",
    "Candidates fused by signal",
    "Evidence gate passed",
    "Context or abstention returned"
  ];
  var currentProofStep = 0;

  function selectProofStep(index, focusButton) {
    if (!proofSteps.length) return;
    currentProofStep = (index + proofSteps.length) % proofSteps.length;
    proofSteps.forEach(function (step, stepIndex) {
      var button = step.querySelector("button");
      var detail = step.querySelector(".proof-detail");
      var active = stepIndex === currentProofStep;
      step.classList.toggle("is-current", active);
      button.setAttribute("aria-expanded", String(active));
      detail.hidden = !active;
      if (active && focusButton) button.focus();
    });
    if (proofMessage) proofMessage.textContent = proofMessages[currentProofStep];
    if (proofCount) proofCount.textContent = String(currentProofStep + 1).padStart(2, "0") + " / 05";
    if (proofState) proofState.textContent = proofStates[currentProofStep];
  }

  proofSteps.forEach(function (step, index) {
    var button = step.querySelector("button");
    button.addEventListener("click", function () {
      selectProofStep(index, false);
    });
  });

  if (proofNext) {
    proofNext.addEventListener("click", function () {
      selectProofStep(currentProofStep + 1, false);
    });
  }

  var codeTabs = Array.prototype.slice.call(document.querySelectorAll("[data-code-tab]"));

  function selectCodeTab(tab, moveFocus) {
    var name = tab.getAttribute("data-code-tab");
    codeTabs.forEach(function (item) {
      var selected = item === tab;
      item.classList.toggle("is-active", selected);
      item.setAttribute("aria-selected", String(selected));
      item.setAttribute("tabindex", selected ? "0" : "-1");
    });
    document.querySelectorAll(".code-panel").forEach(function (panel) {
      var active = panel.id === "code-" + name;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    });
    if (moveFocus) tab.focus();
  }

  codeTabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      selectCodeTab(tab, false);
    });

    tab.addEventListener("keydown", function (event) {
      var nextIndex = index;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % codeTabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + codeTabs.length) % codeTabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = codeTabs.length - 1;
      if (nextIndex === index) return;
      event.preventDefault();
      selectCodeTab(codeTabs[nextIndex], true);
    });
  });

  var docs = Array.isArray(window.LUMINARY_DOCS) ? window.LUMINARY_DOCS : [];
  var docsGrid = document.getElementById("docs-grid");
  var docsEmpty = document.getElementById("docs-empty");
  var docsCount = document.getElementById("docs-count");
  var docsSearch = document.getElementById("docs-search");
  var activeFilter = "all";
  var trackedReferenceCount = docs.reduce(function (total, doc) {
    return total + 1 + (doc.related ? doc.related.length : 0);
  }, 0);

  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, function (character) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#039;"
      }[character];
    });
  }

  function renderDocs() {
    if (!docsGrid) return;
    var query = docsSearch ? docsSearch.value.trim().toLowerCase() : "";
    var visible = docs.filter(function (doc) {
      var haystack = [doc.title, doc.label, doc.blurb, doc.source].concat(doc.facts || []).join(" ").toLowerCase();
      var categoryMatch = activeFilter === "all" || doc.category === activeFilter;
      return categoryMatch && (!query || haystack.indexOf(query) !== -1);
    });

    docsGrid.innerHTML = visible.map(function (doc) {
      var facts = (doc.facts || []).map(function (fact) {
        return "<li>" + escapeHTML(fact) + "</li>";
      }).join("");
      if (doc.related && doc.related.length) {
        facts += "<li>" + doc.related.length + " related reference" + (doc.related.length === 1 ? "" : "s") + "</li>";
      }
      return [
        "<article class=\"doc-row\" data-doc-id=\"" + escapeHTML(doc.id) + "\">",
        "<span class=\"doc-label\">" + escapeHTML(doc.label) + "</span>",
        "<div><h3>" + escapeHTML(doc.title) + "</h3><p>" + escapeHTML(doc.blurb) + "</p></div>",
        "<ul class=\"doc-facts\">" + facts + "</ul>",
        "<a class=\"doc-open\" href=\"" + escapeHTML(doc.href) + "\"><span>Open note</span><span aria-hidden=\"true\">↗</span></a>",
        "</article>"
      ].join("");
    }).join("");

    if (docsCount) {
      var countLabel = visible.length === 1 ? "1 field note" : visible.length + " field notes";
      var filterLabel = activeFilter === "all" ? "" : " in " + activeFilter;
      var queryLabel = query ? " matching \"" + query + "\"" : "";
      docsCount.textContent = countLabel + filterLabel + queryLabel + " · " + trackedReferenceCount + " tracked references";
    }
    if (docsEmpty) docsEmpty.hidden = visible.length !== 0;
  }

  if (docsGrid) {
    renderDocs();
    if (docsSearch) docsSearch.addEventListener("input", renderDocs);
    document.querySelectorAll("[data-doc-filter]").forEach(function (filterButton) {
      filterButton.addEventListener("click", function () {
        activeFilter = filterButton.getAttribute("data-doc-filter") || "all";
        document.querySelectorAll("[data-doc-filter]").forEach(function (item) {
          var active = item === filterButton;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", String(active));
        });
        renderDocs();
      });
    });
  }

  var revealItems = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reducedMotion) {
    var revealObserver = new IntersectionObserver(function (entries, observer) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: .04 });
    revealItems.forEach(function (item) {
      revealObserver.observe(item);
    });
  } else {
    revealItems.forEach(function (item) {
      item.classList.add("is-visible");
    });
  }
}());

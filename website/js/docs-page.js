(function () {
  "use strict";

  var docs = Array.isArray(window.LUMINARY_DOCS) ? window.LUMINARY_DOCS : [];
  var guides = window.LUMINARY_GUIDES || {};
  var nav = document.getElementById("docs-page-nav");
  var reader = document.getElementById("docs-reader");
  var search = document.getElementById("docs-page-search");
  var count = document.getElementById("docs-page-count");
  var copyStatus = document.getElementById("docs-copy-status");
  var docsIndex = document.getElementById("docs-index");
  var menuToggle = document.getElementById("docs-menu-toggle");
  var backdrop = document.getElementById("docs-drawer-backdrop");
  var selectedLabel = document.getElementById("docs-selected-label");
  var tocRail = document.getElementById("docs-toc");
  var drawerBackground = document.querySelectorAll(".site-header, .skip-link, .docs-mobile-bar, .docs-reader, .docs-toc, .site-footer");
  var requestedId = new URLSearchParams(window.location.search).get("doc");
  var selectedId = docs.some(function (doc) { return doc.id === requestedId; }) ? requestedId : (docs[0] && docs[0].id);
  var drawerOpen = false;
  var drawerReturnFocus = null;
  var tocObserver = null;

  function isMobile() {
    return window.matchMedia("(max-width: 860px)").matches;
  }

  function reducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function syncDrawerAccessibility() {
    if (!docsIndex) return;
    var mobile = isMobile();
    drawerBackground.forEach(function (element) { element.inert = mobile && drawerOpen; });
    if (mobile && !drawerOpen && docsIndex.contains(document.activeElement) && menuToggle) {
      menuToggle.focus({ preventScroll: true });
    }
    docsIndex.inert = mobile && !drawerOpen;
    if (mobile && !drawerOpen) docsIndex.setAttribute("aria-hidden", "true");
    else docsIndex.removeAttribute("aria-hidden");
    if (mobile && drawerOpen) {
      docsIndex.setAttribute("role", "dialog");
      docsIndex.setAttribute("aria-modal", "true");
    } else {
      docsIndex.removeAttribute("role");
      docsIndex.removeAttribute("aria-modal");
    }
  }

  function setDrawerState(open, restoreFocus) {
    if (!docsIndex) return;
    drawerOpen = open;
    docsIndex.classList.toggle("is-open", open);
    document.body.classList.toggle("docs-drawer-open", open);
    if (menuToggle) {
      menuToggle.setAttribute("aria-expanded", String(open));
      menuToggle.setAttribute("aria-label", open ? "Close documentation navigation" : "Open documentation navigation");
    }
    if (backdrop) backdrop.classList.toggle("is-visible", open);
    syncDrawerAccessibility();
    if (open && search) search.focus({ preventScroll: true });
    if (restoreFocus && drawerReturnFocus && drawerReturnFocus.isConnected) {
      var returnTarget = docsIndex.contains(drawerReturnFocus) ? menuToggle : drawerReturnFocus;
      if (returnTarget) returnTarget.focus({ preventScroll: true });
    }
  }

  function openDrawer() {
    if (!isMobile() || drawerOpen) return;
    drawerReturnFocus = document.activeElement;
    setDrawerState(true, false);
  }

  function closeDrawer(restoreFocus) {
    if (!drawerOpen) return;
    setDrawerState(false, restoreFocus !== false);
    drawerReturnFocus = null;
  }

  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;" }[character];
    });
  }

  function getDoc(id) {
    return docs.find(function (doc) { return doc.id === id; }) || docs[0];
  }

  function getGuide(doc) {
    return (doc && guides[doc.id]) || { kicker: doc ? doc.category : "reference", lead: doc ? doc.blurb : "", sections: [] };
  }

  function ordinal(index) {
    return String(index + 1).padStart(2, "0");
  }

  function visibleDocs() {
    var query = search ? search.value.trim().toLowerCase() : "";
    return docs.filter(function (doc) {
      var guide = guides[doc.id] || {};
      var haystack = [doc.title, doc.label, doc.blurb, doc.source].concat(doc.facts || [], doc.keywords || [], [JSON.stringify(guide)]).join(" ").toLowerCase();
      return !query || haystack.indexOf(query) !== -1;
    });
  }

  function sourceURL(path) {
    return "https://github.com/alertxsto/luminary-memory/blob/main/" + String(path || "").split("/").map(encodeURIComponent).join("/");
  }

  function sourceLink(path, className) {
    return "<a class=\"" + (className || "reader-source-link") + "\" href=\"" + escapeHTML(sourceURL(path)) + "\" target=\"_blank\" rel=\"noopener\"><strong>" + escapeHTML(path) + "</strong></a>";
  }

  function renderNav() {
    if (!nav) return;
    var visible = visibleDocs();
    nav.innerHTML = visible.length ? ["build", "operate", "integrate"].map(function (category) {
      var group = visible.filter(function (doc) { return doc.category === category; });
      if (!group.length) return "";
      return "<section class=\"docs-nav-group\"><h2>" + category.charAt(0).toUpperCase() + category.slice(1) + "</h2>" +
        group.map(function (doc) {
          var active = doc.id === selectedId;
          return "<a class=\"docs-nav-item" + (active ? " is-active" : "") + "\" href=\"docs.html?doc=" + encodeURIComponent(doc.id) + "\" data-doc-page-id=\"" + escapeHTML(doc.id) + "\"" + (active ? " aria-current=\"page\"" : "") + ">" + escapeHTML(doc.title) + "</a>";
        }).join("") + "</section>";
    }).join("") : "<p class=\"docs-empty-page\"><strong>No matching guides.</strong>Try another term, command, or setting.</p>";
    if (count) {
      var query = search ? search.value.trim() : "";
      count.textContent = visible.length + " of " + docs.length + " guides" + (query ? " matching “" + query + "”" : "");
    }
  }

  function renderList(items, className) {
    if (!Array.isArray(items) || !items.length) return "";
    return "<ul" + (className ? " class=\"" + escapeHTML(className) + "\"" : "") + ">" + items.map(function (item) {
      return "<li>" + escapeHTML(item) + "</li>";
    }).join("") + "</ul>";
  }

  function renderParagraphs(section) {
    return (section.paragraphs || []).map(function (paragraph) {
      return "<p>" + escapeHTML(paragraph) + "</p>";
    }).join("");
  }

  function renderTable(table) {
    if (!table || !Array.isArray(table.columns) || !Array.isArray(table.rows) || !table.rows.length) return "";
    var caption = table.caption ? "<caption>" + escapeHTML(table.caption) + "</caption>" : "";
    var head = "<thead><tr>" + table.columns.map(function (column) {
      return "<th scope=\"col\">" + escapeHTML(column) + "</th>";
    }).join("") + "</tr></thead>";
    var body = "<tbody>" + table.rows.map(function (row) {
      return "<tr>" + table.columns.map(function (_, index) {
        return "<td>" + escapeHTML(row[index] === undefined ? "not set" : row[index]) + "</td>";
      }).join("") + "</tr>";
    }).join("") + "</tbody>";
    var tableClass = "reader-table" + (table.className ? " " + escapeHTML(table.className) : "");
    return "<div class=\"reader-table-wrap\" tabindex=\"0\" role=\"region\" aria-label=\"" + escapeHTML(table.caption || "Reference table") + "\"><table class=\"" + tableClass + "\">" + caption + head + body + "</table></div>";
  }

  function renderParameters(parameters) {
    if (!Array.isArray(parameters) || !parameters.length) return "";
    var hasInputs = parameters.some(function (parameter) {
      return parameter.input && parameter.input !== "—" && parameter.input !== "not set";
    });
    return renderTable({
      caption: "Parameters and defaults",
      className: hasInputs ? "reader-parameter-table has-input" : "reader-parameter-table",
      columns: hasInputs ? ["Name", "Type", "Default", "Input", "What it controls"] : ["Name", "Type", "Default", "What it controls"],
      rows: parameters.map(function (parameter) {
        return hasInputs
          ? [parameter.name, parameter.type, parameter.defaultValue, parameter.input, parameter.description]
          : [parameter.name, parameter.type, parameter.defaultValue, parameter.description];
      })
    });
  }

  function renderCode(value, kind, label) {
    if (!value) return "";
    var code = String(value);
    return "<div class=\"reader-code" + (kind === "output" ? " reader-output" : "") + "\"><div class=\"reader-code-head\"><span class=\"reader-code-label\">" + escapeHTML(label) + "</span><button class=\"reader-code-copy\" type=\"button\" data-copy=\"" + escapeHTML(code) + "\" aria-label=\"Copy " + escapeHTML(label.toLowerCase()) + "\">Copy</button></div><pre tabindex=\"0\" aria-label=\"" + escapeHTML(label) + "\"><code>" + escapeHTML(code) + "</code></pre></div>";
  }

  function renderCallout(kind, title, content) {
    if (!content || (Array.isArray(content) && !content.length)) return "";
    var body = Array.isArray(content) ? renderList(content, "reader-callout-list") : "<p>" + escapeHTML(content) + "</p>";
    return "<aside class=\"reader-callout reader-callout-" + escapeHTML(kind) + "\"><p class=\"reader-callout-title\">" + escapeHTML(title) + "</p>" + body + "</aside>";
  }

  function renderSection(section, index) {
    var sectionId = "reader-section-" + (index + 1);
    return "<section class=\"reader-section\" id=\"" + sectionId + "\" data-toc-index=\"" + index + "\" tabindex=\"-1\"><div class=\"reader-section-heading\"><span class=\"reader-section-number\" aria-hidden=\"true\">" + ordinal(index) + "</span><h2>" + escapeHTML(section.title) + "</h2></div>" +
      renderParagraphs(section) + renderList(section.bullets) + renderParameters(section.parameters) + renderTable(section.table) +
      renderCode(section.output, "output", "Observed output") + renderCode(section.code, "code", "Example") +
      renderCallout("returns", "Returns", section.returns) + renderCallout("tip", "Tip", section.tips) +
      renderCallout("warning", "Boundary", section.warnings) + renderCallout("note", "Note", section.notes) + "</section>";
  }

  function buildTOC() {
    if (!reader || !tocRail) return;
    if (tocObserver) tocObserver.disconnect();
    var sections = reader.querySelectorAll(".reader-section");
    var links = Array.from(sections).map(function (section, index) {
      var heading = section.querySelector("h2");
      return "<li><a class=\"reader-toc-link\" href=\"#" + section.id + "\" data-toc-target=\"" + index + "\">" + escapeHTML(heading.textContent) + "</a></li>";
    }).join("");
    var outline = "<nav class=\"reader-toc\" aria-label=\"On this page\"><p class=\"reader-toc-heading\">On this page</p><ol class=\"reader-toc-list\">" + links + "</ol></nav>";
    tocRail.innerHTML = outline + "<a class=\"reader-toc-source\" href=\"" + escapeHTML(sourceURL(getDoc(selectedId).source)) + "\" target=\"_blank\" rel=\"noopener\">View source <span aria-hidden=\"true\">↗</span></a>";
    var header = reader.querySelector(".reader-header");
    if (header) header.insertAdjacentHTML("afterend", "<details class=\"reader-toc-inline\"><summary>On this page</summary>" + outline + "</details>");
    if ("IntersectionObserver" in window) {
      tocObserver = new IntersectionObserver(function (entries) {
        var visible = entries.filter(function (entry) { return entry.isIntersecting; });
        if (!visible.length) return;
        var active = visible[0].target.dataset.tocIndex;
        document.querySelectorAll("[data-toc-target]").forEach(function (link) {
          if (link.dataset.tocTarget === active) link.setAttribute("aria-current", "location");
          else link.removeAttribute("aria-current");
        });
      }, { rootMargin: "-100px 0px -65% 0px" });
      sections.forEach(function (section) { tocObserver.observe(section); });
    }
  }

  function renderReader() {
    var doc = getDoc(selectedId);
    if (!doc || !reader) return;
    selectedId = doc.id;
    var guide = getGuide(doc);
    var guideSections = (guide.sections || []).map(renderSection).join("");
    var docIndex = docs.findIndex(function (item) { return item.id === doc.id; });
    var facts = doc.facts && doc.facts.length ? "<ul class=\"reader-facts\" aria-label=\"Document facts\">" + doc.facts.map(function (fact) {
      return "<li>" + escapeHTML(fact) + "</li>";
    }).join("") + "</ul>" : "";
    var related = doc.related && doc.related.length ? "<p class=\"reader-related\">Related tracked references: " + doc.related.map(function (path) { return sourceLink(path, "reader-related-link"); }).join(" / ") + "</p>" : "";
    var previous = docIndex > 0 ? docs[docIndex - 1] : null;
    var next = docIndex < docs.length - 1 ? docs[docIndex + 1] : null;
    var navigation = "<footer class=\"reader-footer\">" +
      (previous ? "<a class=\"reader-nav-link\" href=\"docs.html?doc=" + encodeURIComponent(previous.id) + "\" data-doc-page-id=\"" + escapeHTML(previous.id) + "\"><span class=\"reader-nav-label\">← Previous</span>" + escapeHTML(previous.title) + "</a>" : "<span></span>") +
      (next ? "<a class=\"reader-nav-link\" href=\"docs.html?doc=" + encodeURIComponent(next.id) + "\" data-doc-page-id=\"" + escapeHTML(next.id) + "\"><span class=\"reader-nav-label\">Next →</span>" + escapeHTML(next.title) + "</a>" : "<span></span>") +
      "</footer>";
    reader.dataset.docId = doc.id;
    reader.innerHTML = "<figure class=\"reader-banner\"><img class=\"raster-art art-dark\" src=\"assets/art/lunar-docs-dark.png\" width=\"1080\" height=\"300\" alt=\"\"><img class=\"raster-art art-light\" src=\"assets/art/lunar-docs-light.png\" width=\"1080\" height=\"300\" alt=\"\"><figcaption class=\"reader-banner-label\">Knowledge, kept in orbit</figcaption></figure><header class=\"reader-header\"><div class=\"reader-header-top\"><p class=\"reader-kicker\">" + escapeHTML(guide.kicker) + "</p><span class=\"reader-sequence\">" + ordinal(docIndex) + " / " + String(docs.length).padStart(2, "0") + "</span></div><h1>" + escapeHTML(doc.title) + "</h1><p class=\"reader-lead\">" + escapeHTML(guide.lead) + "</p>" + facts + "<div class=\"reader-meta\"><span>Source " + sourceLink(doc.source) + "</span><span>" + escapeHTML(doc.category) + " / " + String((guide.sections || []).length) + " sections</span></div></header><div class=\"reader-body\">" + guideSections + related + navigation + "</div>";
    document.title = doc.title + " | Luminary Memory";
    if (selectedLabel) selectedLabel.textContent = doc.title;
    buildTOC();
  }

  function scrollToReader() {
    if (!reader) return;
    var top = reader.getBoundingClientRect().top + window.scrollY - 100;
    window.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? "auto" : "smooth" });
  }

  function selectDoc(id, updateUrl, moveToArticle) {
    var doc = getDoc(id);
    if (!doc) return;
    selectedId = doc.id;
    if (updateUrl && new URLSearchParams(window.location.search).get("doc") !== selectedId) {
      var url = new URL(window.location.href);
      url.searchParams.set("doc", selectedId);
      url.hash = "";
      window.history.pushState({}, "", url);
    }
    if (drawerOpen) closeDrawer(false);
    renderNav();
    renderReader();
    if (moveToArticle) scrollToReader();
    if (reader) reader.focus({ preventScroll: true });
  }

  function showCopyStatus(message, button) {
    if (copyStatus) copyStatus.textContent = message;
    if (!button) return;
    button.textContent = "Copied";
    button.classList.add("is-copied");
    window.clearTimeout(button.copyResetTimer);
    button.copyResetTimer = window.setTimeout(function () {
      button.textContent = "Copy";
      button.classList.remove("is-copied");
    }, 2200);
  }

  function copyTextFallback(value, button) {
    var textarea = document.createElement("textarea");
    var previousFocus = document.activeElement;
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    var copied = false;
    try { copied = document.execCommand("copy"); } catch (error) { copied = false; }
    textarea.remove();
    if (previousFocus && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    showCopyStatus(copied ? "Copied to clipboard" : "Select and copy the code", copied ? button : null);
  }

  function copyText(value, button) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(value).then(function () {
        showCopyStatus("Copied to clipboard", button);
      }).catch(function () { copyTextFallback(value, button); });
    } else {
      copyTextFallback(value, button);
    }
  }

  function scrollToHash() {
    if (!window.location.hash || !reader) return;
    var target = document.getElementById(window.location.hash.slice(1));
    if (target && reader.contains(target)) target.scrollIntoView({ block: "start" });
  }

  document.addEventListener("click", function (event) {
    var copyControl = event.target.closest("[data-copy]");
    if (copyControl && reader.contains(copyControl)) {
      copyText(copyControl.getAttribute("data-copy") || "", copyControl);
      return;
    }
    var tocTarget = event.target.closest("[data-toc-target]");
    if (tocTarget) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      var section = reader.querySelector("[data-toc-index=\"" + tocTarget.dataset.tocTarget + "\"]");
      if (section) {
        section.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
        section.focus({ preventScroll: true });
        var url = new URL(window.location.href);
        url.hash = section.id;
        window.history.replaceState({}, "", url);
      }
      return;
    }
    var docControl = event.target.closest("[data-doc-page-id]");
    if (docControl) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      selectDoc(docControl.getAttribute("data-doc-page-id"), true, true);
      return;
    }
    if (event.target.closest("#docs-menu-toggle")) {
      if (drawerOpen) closeDrawer(true); else openDrawer();
      return;
    }
    if (event.target.closest("#docs-index-close") || event.target.closest("#docs-drawer-backdrop")) closeDrawer(true);
  });

  if (search) search.addEventListener("input", renderNav);

  window.addEventListener("popstate", function () {
    selectedId = new URLSearchParams(window.location.search).get("doc") || (docs[0] && docs[0].id);
    if (drawerOpen) closeDrawer(false);
    renderReader();
    renderNav();
    scrollToHash();
  });

  window.addEventListener("resize", function () {
    if (!isMobile() && drawerOpen) closeDrawer(false);
    syncDrawerAccessibility();
  });

  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (isMobile()) openDrawer();
      if (search) {
        search.focus({ preventScroll: true });
        search.select();
      }
      return;
    }
    if (event.key === "Tab" && drawerOpen && docsIndex) {
      var controls = Array.from(docsIndex.querySelectorAll("a[href], button, input, [tabindex]:not([tabindex='-1'])")).filter(function (element) {
        return !element.disabled && element.getClientRects().length > 0;
      });
      var first = controls[0];
      var last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || !docsIndex.contains(document.activeElement))) {
        event.preventDefault();
        if (last) last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !docsIndex.contains(document.activeElement))) {
        event.preventDefault();
        if (first) first.focus();
      }
    }
    if (event.key === "Escape" && drawerOpen) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeDrawer(true);
      return;
    }
    if (event.key === "Escape" && search && document.activeElement === search && search.value) {
      search.value = "";
      renderNav();
    }
  }, true);

  syncDrawerAccessibility();
  renderNav();
  renderReader();
  scrollToHash();
}());

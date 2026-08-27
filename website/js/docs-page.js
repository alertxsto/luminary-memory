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
  var closeButton = document.getElementById("docs-index-close");
  var backdrop = document.getElementById("docs-drawer-backdrop");
  var selectedLabel = document.getElementById("docs-selected-label");
  var activeFilter = "all";
  var requestedId = new URLSearchParams(window.location.search).get("doc");
  var selectedId = docs.some(function (doc) { return doc.id === requestedId; }) ? requestedId : (docs[0] && docs[0].id);
  var drawerOpen = false;
  var drawerReturnFocus = null;
  var copyResetTimer = null;

  function isMobile() {
    return window.matchMedia("(max-width: 680px)").matches;
  }

  function reducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function setDrawerState(open, restoreFocus) {
    if (!docsIndex) return;
    drawerOpen = open;
    docsIndex.classList.toggle("is-open", open);
    document.body.classList.toggle("docs-drawer-open", open);
    if (menuToggle) {
      menuToggle.setAttribute("aria-expanded", String(open));
      menuToggle.setAttribute("aria-label", open ? "Close source index" : "Open source index");
    }
    if (backdrop) {
      backdrop.classList.toggle("is-visible", open);
      backdrop.setAttribute("aria-hidden", String(!open));
    }
    if (restoreFocus && drawerReturnFocus && typeof drawerReturnFocus.focus === "function") {
      drawerReturnFocus.focus();
    }
    if (open) {
      var firstItem = nav && nav.querySelector("[data-doc-page-id]");
      if (firstItem) firstItem.focus({ preventScroll: true });
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
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#039;"
      }[character];
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
      var categoryMatch = activeFilter === "all" || doc.category === activeFilter;
      return categoryMatch && (!query || haystack.indexOf(query) !== -1);
    });
  }

  function updateInventory() {
    var categories = { build: 0, operate: 0, integrate: 0 };
    docs.forEach(function (doc) {
      if (Object.prototype.hasOwnProperty.call(categories, doc.category)) categories[doc.category] += 1;
    });
    var totals = {
      "docs-total-count": docs.length + " notes",
      "docs-build-count": categories.build,
      "docs-operate-count": categories.operate,
      "docs-integrate-count": categories.integrate
    };
    Object.keys(totals).forEach(function (id) {
      var element = document.getElementById(id);
      if (element) element.textContent = String(totals[id]);
    });
  }

  function updateSelectedLabel(doc) {
    if (selectedLabel) selectedLabel.textContent = doc ? doc.title : "Select a note";
  }

  function sourceLink(path, className) {
    var safePath = String(path || "");
    return "<a class=\"" + (className || "reader-source-link") + "\" href=\"../" + escapeHTML(safePath) + "\" target=\"_blank\" rel=\"noopener\"><strong>" + escapeHTML(safePath) + "</strong></a>";
  }

  function renderNav() {
    var visible = visibleDocs();
    if (!nav) return;
    nav.innerHTML = visible.length ? visible.map(function (doc) {
      var active = doc.id === selectedId;
      var docIndex = docs.findIndex(function (item) { return item.id === doc.id; });
      return "<button class=\"docs-nav-item" + (active ? " is-active" : "") + "\" type=\"button\" data-doc-page-id=\"" + escapeHTML(doc.id) + "\"" + (active ? " aria-current=\"page\"" : "") + ">" +
        "<span class=\"docs-nav-index\">" + ordinal(docIndex) + "</span>" +
        "<span class=\"docs-nav-copy\"><span class=\"docs-nav-label\">" + escapeHTML(doc.label) + "</span><span class=\"docs-nav-title\">" + escapeHTML(doc.title) + "</span><span class=\"docs-nav-source\">" + escapeHTML(doc.source) + "</span></span>" +
        "<span class=\"docs-nav-category\">" + escapeHTML(doc.category) + "</span></button>";
    }).join("") : "<p class=\"docs-empty-page\">No notes match this filter.</p>";
    if (count) {
      var query = search ? search.value.trim() : "";
      count.textContent = visible.length + " of " + docs.length + " source notes" + (query ? " / matching \"" + query + "\"" : "");
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
    return "<div class=\"reader-table-wrap\"><table class=\"" + tableClass + "\">" + caption + head + body + "</table></div>";
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
    return "<div class=\"reader-code" + (kind === "output" ? " reader-output" : "") + "\"><div class=\"reader-code-head\"><span class=\"reader-code-label\">" + escapeHTML(label) + "</span><button class=\"reader-code-copy\" type=\"button\" data-copy=\"" + escapeHTML(code) + "\">Copy</button></div><pre><code>" + escapeHTML(code) + "</code></pre></div>";
  }

  function renderCallout(kind, title, content) {
    if (!content || (Array.isArray(content) && !content.length)) return "";
    var body = Array.isArray(content) ? renderList(content, "reader-callout-list") : "<p>" + escapeHTML(content) + "</p>";
    return "<aside class=\"reader-callout reader-callout-" + escapeHTML(kind) + "\"><p class=\"reader-callout-title\">" + escapeHTML(title) + "</p>" + body + "</aside>";
  }

  function renderSection(section, index) {
    var sectionId = "reader-section-" + (index + 1);
    var bullets = renderList(section.bullets);
    var parameters = renderParameters(section.parameters);
    var table = renderTable(section.table);
    var output = renderCode(section.output, "output", "Observed output");
    var code = renderCode(section.code, "code", "Example");
    var returns = renderCallout("returns", "Returns", section.returns);
    var tips = renderCallout("tip", "Tip", section.tips);
    var warnings = renderCallout("warning", "Boundary", section.warnings);
    var notes = renderCallout("note", "Note", section.notes);
    return "<section class=\"reader-section\" id=\"" + sectionId + "\" data-toc-index=\"" + index + "\"><div class=\"reader-section-heading\"><span class=\"reader-section-number\">" + ordinal(index) + "</span><h3>" + escapeHTML(section.title) + "</h3></div>" + renderParagraphs(section) + bullets + parameters + table + output + code + returns + tips + warnings + notes + "</section>";
  }

  function buildTOC() {
    if (!reader) return;
    var sections = reader.querySelectorAll(".reader-section");
    if (sections.length < 2) return;
    var items = [];
    sections.forEach(function (section, index) {
      var heading = section.querySelector("h3");
      if (heading) items.push({ index: index, text: heading.textContent });
    });
    if (!items.length) return;
    var toc = document.createElement("nav");
    toc.className = "reader-toc";
    toc.setAttribute("aria-label", "On this page");
    var title = document.createElement("p");
    title.className = "reader-toc-heading";
    title.textContent = "On this page";
    toc.appendChild(title);
    var list = document.createElement("ol");
    list.className = "reader-toc-list";
    items.forEach(function (item) {
      var listItem = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "reader-toc-link";
      button.setAttribute("data-toc-target", String(item.index));
      button.textContent = item.text;
      listItem.appendChild(button);
      list.appendChild(listItem);
    });
    toc.appendChild(list);
    var header = reader.querySelector(".reader-header");
    if (header) header.insertAdjacentElement("afterend", toc);
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
      (previous ? "<a class=\"reader-nav-link\" href=\"docs.html?doc=" + encodeURIComponent(previous.id) + "\" data-doc-page-id=\"" + escapeHTML(previous.id) + "\"><span class=\"reader-nav-label\">Previous note</span>" + escapeHTML(previous.title) + "</a>" : "<span></span>") +
      (next ? "<a class=\"reader-nav-link\" href=\"docs.html?doc=" + encodeURIComponent(next.id) + "\" data-doc-page-id=\"" + escapeHTML(next.id) + "\"><span class=\"reader-nav-label\">Next note</span>" + escapeHTML(next.title) + "</a>" : "<span></span>") +
      "</footer>";
    reader.dataset.docId = doc.id;
    reader.innerHTML = "<header class=\"reader-header\"><div class=\"reader-header-top\"><p class=\"reader-kicker\">" + escapeHTML(guide.kicker) + "</p><span class=\"reader-sequence\">" + ordinal(docIndex) + " / " + String(docs.length).padStart(2, "0") + " note</span></div><h2>" + escapeHTML(doc.title) + "</h2><p class=\"reader-lead\">" + escapeHTML(guide.lead) + "</p>" + facts + "<div class=\"reader-meta\"><span>source of record " + sourceLink(doc.source) + "</span><span>job <strong>" + escapeHTML(doc.category) + "</strong></span><span>sections <strong>" + String((guide.sections || []).length) + "</strong></span></div></header><div class=\"reader-body\">" + guideSections + related + navigation + "</div>";
    document.title = doc.title + " | Luminary Memory";
    updateSelectedLabel(doc);
    buildTOC();
  }

  function scrollToReader() {
    if (!reader) return;
    var top = reader.getBoundingClientRect().top + window.scrollY - (isMobile() ? 78 : 110);
    window.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? "auto" : "smooth" });
  }

  function selectDoc(id, updateUrl, moveToArticle) {
    var doc = getDoc(id);
    if (!doc) return;
    selectedId = doc.id;
    if (updateUrl) window.history.pushState({}, "", "docs.html?doc=" + encodeURIComponent(selectedId));
    renderNav();
    renderReader();
    if (isMobile() && drawerOpen) closeDrawer(false);
    if (moveToArticle) scrollToReader();
    if (reader) reader.focus({ preventScroll: true });
  }

  function showCopyStatus(message, button) {
    if (copyStatus) copyStatus.textContent = message;
    if (button) {
      button.textContent = "Copied";
      button.classList.add("is-copied");
    }
    window.clearTimeout(copyResetTimer);
    copyResetTimer = window.setTimeout(function () {
      if (copyStatus) copyStatus.textContent = "";
      if (button) {
        button.textContent = "Copy";
        button.classList.remove("is-copied");
      }
    }, 2200);
  }

  function copyText(value, button) {
    var done = function () { showCopyStatus("Copied to clipboard", button); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(value).then(done).catch(function () { copyTextFallback(value, button); });
      return;
    }
    copyTextFallback(value, button);
  }

  function copyTextFallback(value, button) {
    var textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    var copied = false;
    try { copied = document.execCommand("copy"); } catch (error) { copied = false; }
    textarea.remove();
    showCopyStatus(copied ? "Copied to clipboard" : "Select and copy the code", copied ? button : null);
  }

  document.addEventListener("click", function (event) {
    var copyControl = event.target.closest("[data-copy]");
    if (copyControl) {
      copyText(copyControl.getAttribute("data-copy") || "", copyControl);
      return;
    }
    var tocTarget = event.target.closest("[data-toc-target]");
    if (tocTarget) {
      var section = reader && reader.querySelector("[data-toc-index=\"" + tocTarget.getAttribute("data-toc-target") + "\"]");
      if (section) section.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
      return;
    }
    var docControl = event.target.closest("[data-doc-page-id]");
    if (docControl) {
      event.preventDefault();
      selectDoc(docControl.getAttribute("data-doc-page-id"), true, true);
      return;
    }
    var filterControl = event.target.closest("[data-doc-page-filter]");
    if (filterControl) {
      activeFilter = filterControl.getAttribute("data-doc-page-filter");
      document.querySelectorAll("[data-doc-page-filter]").forEach(function (button) {
        var active = button === filterControl;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      renderNav();
      return;
    }
    if (event.target.closest("#docs-menu-toggle")) {
      if (drawerOpen) closeDrawer(true); else openDrawer();
      return;
    }
    if (event.target.closest("#docs-index-close") || event.target.closest("#docs-drawer-backdrop")) {
      closeDrawer(true);
    }
  });

  if (search) search.addEventListener("input", renderNav);

  window.addEventListener("popstate", function () {
    selectedId = new URLSearchParams(window.location.search).get("doc") || (docs[0] && docs[0].id);
    if (!getDoc(selectedId)) selectedId = docs[0] && docs[0].id;
    renderNav();
    renderReader();
  });

  window.addEventListener("resize", function () {
    if (!isMobile() && drawerOpen) closeDrawer(false);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && drawerOpen) {
      closeDrawer(true);
      return;
    }
    if (event.key === "Escape" && search && document.activeElement === search && search.value) {
      search.value = "";
      renderNav();
    }
  });

  updateInventory();
  renderNav();
  renderReader();
}());

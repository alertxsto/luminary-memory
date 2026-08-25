(function () {
  "use strict";

  var docs = Array.isArray(window.LUMINARY_DOCS) ? window.LUMINARY_DOCS : [];
  var guides = window.LUMINARY_GUIDES || {};
  var nav = document.getElementById("docs-page-nav");
  var reader = document.getElementById("docs-reader");
  var search = document.getElementById("docs-page-search");
  var count = document.getElementById("docs-page-count");
  var docsIndex = document.getElementById("docs-index");
  var menuToggle = document.getElementById("docs-menu-toggle");
  var backdrop = document.getElementById("docs-drawer-backdrop");
  var activeFilter = "all";
  var selectedId = new URLSearchParams(window.location.search).get("doc") || "quickstart";
  var drawerOpen = false;

  /* ── Drawer helpers ─────────────────────────────────────────────────────── */

  function isMobile() {
    return window.matchMedia("(max-width: 680px)").matches;
  }

  function openDrawer() {
    if (!docsIndex) return;
    drawerOpen = true;
    docsIndex.classList.add("is-open");
    if (menuToggle) {
      menuToggle.setAttribute("aria-expanded", "true");
      menuToggle.setAttribute("aria-label", "Close reading index");
    }
    if (backdrop) backdrop.classList.add("is-visible");
    document.body.classList.add("docs-drawer-open");
  }

  function closeDrawer() {
    if (!docsIndex) return;
    drawerOpen = false;
    docsIndex.classList.remove("is-open");
    if (menuToggle) {
      menuToggle.setAttribute("aria-expanded", "false");
      menuToggle.setAttribute("aria-label", "Open reading index");
    }
    if (backdrop) backdrop.classList.remove("is-visible");
    document.body.classList.remove("docs-drawer-open");
  }

  function toggleDrawer() {
    if (drawerOpen) {
      closeDrawer();
    } else {
      openDrawer();
    }
  }

  /* ── Escape HTML ────────────────────────────────────────────────────────── */

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

  /* ── Doc lookup ─────────────────────────────────────────────────────────── */

  function getDoc(id) {
    return docs.find(function (doc) {
      return doc.id === id;
    }) || docs[0];
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

  /* ── Nav render ─────────────────────────────────────────────────────────── */

  function renderNav() {
    var visible = visibleDocs();
    if (!nav) return;
    nav.innerHTML = visible.length ? visible.map(function (doc) {
      var active = doc.id === selectedId;
      return "<button class=\"docs-nav-item" + (active ? " is-active" : "") + "\" type=\"button\" data-doc-page-id=\"" + escapeHTML(doc.id) + "\"" + (active ? " aria-current=\"page\"" : "") + ">" +
        "<span><span class=\"docs-nav-label\">" + escapeHTML(doc.label) + "</span><span class=\"docs-nav-title\">" + escapeHTML(doc.title) + "</span></span>" +
        "<span class=\"docs-nav-category\">" + escapeHTML(doc.category) + "</span></button>";
    }).join("") : "<p class=\"docs-empty-page\">No notes match that filter.</p>";
    if (count) {
      count.textContent = visible.length + " field notes" + (search && search.value.trim() ? " matching \"" + search.value.trim() + "\"" : "") + " / " + docs.length + " total";
    }
  }

  /* ── Article renderers ──────────────────────────────────────────────────── */

  function renderParagraphs(section) {
    return (section.paragraphs || []).map(function (paragraph) {
      return "<p>" + escapeHTML(paragraph) + "</p>";
    }).join("");
  }

  function renderList(items, className) {
    if (!Array.isArray(items) || !items.length) return "";
    return "<ul" + (className ? " class=\"" + escapeHTML(className) + "\"" : "") + ">" + items.map(function (item) {
      return "<li>" + escapeHTML(item) + "</li>";
    }).join("") + "</ul>";
  }

  function renderTable(table) {
    if (!table || !Array.isArray(table.columns) || !Array.isArray(table.rows) || !table.rows.length) return "";
    var caption = table.caption ? "<caption>" + escapeHTML(table.caption) + "</caption>" : "";
    var head = "<thead><tr>" + table.columns.map(function (column) {
      return "<th scope=\"col\">" + escapeHTML(column) + "</th>";
    }).join("") + "</tr></thead>";
    var body = "<tbody>" + table.rows.map(function (row) {
      return "<tr>" + table.columns.map(function (_, index) {
        return "<td>" + escapeHTML(row[index] === undefined ? "—" : row[index]) + "</td>";
      }).join("") + "</tr>";
    }).join("") + "</tbody>";
    var tableClass = "reader-table" + (table.className ? " " + escapeHTML(table.className) : "");
    return "<div class=\"reader-table-wrap\"><table class=\"" + tableClass + "\">" + caption + head + body + "</table></div>";
  }

  function renderParameters(parameters) {
    if (!Array.isArray(parameters) || !parameters.length) return "";
    var hasInputs = parameters.some(function (parameter) {
      return parameter.input && parameter.input !== "—";
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

  function renderCallout(kind, title, content) {
    if (!content || (Array.isArray(content) && !content.length)) return "";
    var body = Array.isArray(content) ? renderList(content, "reader-callout-list") : "<p>" + escapeHTML(content) + "</p>";
    return "<aside class=\"reader-callout reader-callout-" + escapeHTML(kind) + "\"><p class=\"reader-callout-title\">" + escapeHTML(title) + "</p>" + body + "</aside>";
  }

  function renderSection(section) {
    var bullets = renderList(section.bullets);
    var parameters = renderParameters(section.parameters);
    var table = renderTable(section.table);
    var output = section.output ? "<pre class=\"reader-output\"><code>" + escapeHTML(section.output) + "</code></pre>" : "";
    var code = section.code ? "<pre><code>" + escapeHTML(section.code) + "</code></pre>" : "";
    var returns = renderCallout("returns", "Returns", section.returns);
    var tips = renderCallout("tip", "Tip", section.tips);
    var warnings = renderCallout("warning", "Boundary", section.warnings);
    var notes = renderCallout("note", "Note", section.notes);
    return "<section class=\"reader-section\"><h3>" + escapeHTML(section.title) + "</h3>" + renderParagraphs(section) + bullets + parameters + table + output + code + returns + tips + warnings + notes + "</section>";
  }

  /* ── In-article TOC ─────────────────────────────────────────────────────── */
  /* Scans .reader-section h3 elements after the reader renders, builds a     */
  /* .reader-toc nav with scroll-to links, inserts after .reader-header.      */

  function buildTOC() {
    if (!reader) return;
    var sections = reader.querySelectorAll(".reader-section");
    if (sections.length < 2) return; // not worth a TOC for a single section

    var items = [];
    sections.forEach(function (section, index) {
      var h3 = section.querySelector("h3");
      if (!h3) return;
      // Assign a data attribute index so the click handler can find the element
      section.setAttribute("data-toc-index", String(index));
      items.push({ index: index, text: h3.textContent });
    });

    if (!items.length) return;

    var toc = document.createElement("nav");
    toc.className = "reader-toc";
    toc.setAttribute("aria-label", "On this page");

    var heading = document.createElement("p");
    heading.className = "reader-toc-heading";
    heading.textContent = "On this page";
    toc.appendChild(heading);

    var list = document.createElement("ol");
    list.className = "reader-toc-list";
    items.forEach(function (item) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "reader-toc-link";
      btn.setAttribute("data-toc-target", String(item.index));
      btn.textContent = item.text;
      li.appendChild(btn);
      list.appendChild(li);
    });
    toc.appendChild(list);

    var header = reader.querySelector(".reader-header");
    if (header && header.nextSibling) {
      header.parentNode.insertBefore(toc, header.nextSibling);
    } else if (header) {
      header.parentNode.appendChild(toc);
    }
  }

  /* ── Main reader render ─────────────────────────────────────────────────── */

  function renderReader() {
    var doc = getDoc(selectedId);
    if (!doc || !reader) return;
    selectedId = doc.id;
    var guide = guides[doc.id] || { kicker: doc.category, lead: doc.blurb, sections: [] };
    var guideSections = (guide.sections || []).map(renderSection).join("");
    var related = doc.related && doc.related.length ? "<p class=\"reader-related\">Related tracked references: " + escapeHTML(doc.related.join(" / ")) + "</p>" : "";
    var facts = doc.facts && doc.facts.length ? "<ul class=\"reader-facts\" aria-label=\"Document facts\">" + doc.facts.map(function (fact) {
      return "<li>" + escapeHTML(fact) + "</li>";
    }).join("") + "</ul>" : "";
    var currentIndex = docs.findIndex(function (item) { return item.id === doc.id; });
    var previous = currentIndex > 0 ? docs[currentIndex - 1] : null;
    var next = currentIndex < docs.length - 1 ? docs[currentIndex + 1] : null;
    var navigation = "<footer class=\"reader-footer\">" +
      (previous ? "<a class=\"reader-nav-link\" href=\"docs.html?doc=" + encodeURIComponent(previous.id) + "\" data-doc-page-id=\"" + escapeHTML(previous.id) + "\"><span class=\"reader-nav-label\">Previous note</span>" + escapeHTML(previous.title) + "</a>" : "<span></span>") +
      (next ? "<a class=\"reader-nav-link\" href=\"docs.html?doc=" + encodeURIComponent(next.id) + "\" data-doc-page-id=\"" + escapeHTML(next.id) + "\"><span class=\"reader-nav-label\">Next note</span>" + escapeHTML(next.title) + "</a>" : "<span></span>") +
      "</footer>";
    reader.innerHTML = "<header class=\"reader-header\"><p class=\"reader-kicker\">" + escapeHTML(guide.kicker) + "</p><h2>" + escapeHTML(doc.title) + "</h2><p class=\"reader-lead\">" + escapeHTML(guide.lead) + "</p>" + facts + "<div class=\"reader-meta\"><span>tracked source <strong>" + escapeHTML(doc.source) + "</strong></span><span>surface <strong>" + escapeHTML(doc.category) + "</strong></span></div></header><div class=\"reader-body\">" + guideSections + related + navigation + "</div>";
    document.title = doc.title + " | Luminary Memory";
    // Build TOC after DOM is populated
    buildTOC();
  }

  /* ── Doc selection ──────────────────────────────────────────────────────── */

  function selectDoc(id, updateUrl) {
    var doc = getDoc(id);
    if (!doc) return;
    selectedId = doc.id;
    if (updateUrl) {
      window.history.replaceState({}, "", "docs.html?doc=" + encodeURIComponent(selectedId));
    }
    renderNav();
    renderReader();
    // Auto-close drawer on mobile after selecting a doc
    if (isMobile() && drawerOpen) {
      closeDrawer();
    }
    if (reader) {
      reader.focus({ preventScroll: true });
    }
  }

  /* ── Event delegation ───────────────────────────────────────────────────── */

  document.addEventListener("click", function (event) {
    // TOC scroll-to link
    var tocTarget = event.target.closest("[data-toc-target]");
    if (tocTarget) {
      var idx = tocTarget.getAttribute("data-toc-target");
      var section = reader && reader.querySelector("[data-toc-index=\"" + idx + "\"]");
      if (section) {
        section.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return;
    }

    // Doc nav item
    var docControl = event.target.closest("[data-doc-page-id]");
    if (docControl) {
      event.preventDefault();
      selectDoc(docControl.getAttribute("data-doc-page-id"), true);
      return;
    }

    // Category filter
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

    // Drawer toggle button
    if (event.target.closest("#docs-menu-toggle")) {
      toggleDrawer();
      return;
    }

    // Backdrop click — close drawer
    if (event.target.closest("#docs-drawer-backdrop")) {
      closeDrawer();
      return;
    }
  });

  if (search) {
    search.addEventListener("input", renderNav);
  }

  window.addEventListener("popstate", function () {
    selectedId = new URLSearchParams(window.location.search).get("doc") || "quickstart";
    renderNav();
    renderReader();
  });

  // Close drawer with Escape key
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && drawerOpen) {
      closeDrawer();
      if (menuToggle) menuToggle.focus();
    }
  });

  renderNav();
  renderReader();
}());

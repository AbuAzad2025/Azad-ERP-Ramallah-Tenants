(function (window, document) {
  "use strict";

  var SKIP_LABELS = /^(#|id|checkbox|تحديد|اختيار|actions?|إجراء|عمليات)$/i;

  function isCompact() {
    if (window.GMLayout && typeof window.GMLayout.isCompactLayout === "function") {
      return window.GMLayout.isCompactLayout();
    }
    var mode = (document.documentElement.getAttribute("data-ui-mode") || "").toLowerCase();
    if (mode === "mobile" || mode === "tablet") return true;
    if (mode === "desktop") return false;
    try {
      return window.matchMedia("(max-width: 991.98px)").matches;
    } catch (_) {
      return false;
    }
  }

  function syncCompactBodyClass() {
    if (!document.body) return;
    document.body.classList.toggle("gm-compact-app", isCompact());
  }

  function cleanLabel(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  function getHeaderLabels(table) {
    var headers = [];
    var thead = table.querySelector("thead");
    if (!thead) return headers;
    var ths = thead.querySelectorAll("th");
    for (var i = 0; i < ths.length; i++) {
      var th = ths[i];
      if (th.classList.contains("d-none") || th.classList.contains("hide-mobile") || th.classList.contains("gm-mobile-skip")) {
        headers.push(null);
        continue;
      }
      var text = cleanLabel(th.textContent);
      if (!text || SKIP_LABELS.test(text)) text = null;
      headers.push(text || "—");
    }
    return headers;
  }

  function cellIsEmpty(td) {
    var text = cleanLabel(td.textContent);
    if (!text || text === "—" || text === "-") return true;
    if (td.querySelector("input[type=checkbox]") && !text.replace(/\s/g, "")) return true;
    return false;
  }

  function shouldSkipTable(table) {
    if (!table || !table.querySelector("tbody")) return true;
    if (table.classList.contains("no-mobile-cards")) return true;
    if (table.getAttribute("data-mobile-cards") === "off") return true;
    if (table.closest(".no-mobile-cards")) return true;
    if (table.closest(".gm-pos-terminal")) return true;
    if (table.closest(".gm-ledger-scroll")) return true;
    var headers = getHeaderLabels(table).filter(Boolean);
    if (headers.length === 0 || headers.length > 12) return true;
    if (table.rows.length > 500) return true;
    return false;
  }

  function findPrimaryCell(tr, headers) {
    var cells = tr.cells;
    for (var i = 0; i < cells.length; i++) {
      var td = cells[i];
      if (td.classList.contains("gm-mobile-skip") || td.classList.contains("d-none")) continue;
      if (td.querySelector(".btn, .btn-group, input[type=checkbox]")) continue;
      var label = headers[i];
      if (label && !SKIP_LABELS.test(label) && !cellIsEmpty(td)) return td;
    }
    return cells[0] || null;
  }

  function enhanceTable(table) {
    if (shouldSkipTable(table)) return;
    var headers = getHeaderLabels(table);
  if (!headers.some(Boolean)) return;

    table.classList.add("table-mobile-cards");

    var rows = table.querySelectorAll("tbody tr");
    for (var r = 0; r < rows.length; r++) {
      var tr = rows[r];
      if (tr.classList.contains("gm-mobile-card-ready")) continue;
      if (tr.classList.contains("child") || tr.classList.contains("dataTables_empty")) continue;

      var primary = findPrimaryCell(tr, headers);
      if (primary) {
        primary.classList.add("gm-mobile-primary");
        var title = cleanLabel(primary.textContent);
        if (title) tr.setAttribute("data-mobile-title", title);
      }

      var rowLink = tr.querySelector("a[href]:not([href='#'])");
      if (rowLink && !tr.querySelector(".gm-mobile-actions")) {
        tr.classList.add("gm-mobile-card-tappable");
        tr.addEventListener("click", function (e) {
          if (e.target.closest(".btn, .dropdown, input, select, textarea, a.btn, label")) return;
          var link = this.querySelector("a[href]:not([href='#'])");
          if (link) {
            if (link.target === "_blank") window.open(link.href, "_blank");
            else window.location.href = link.href;
          }
        });
      }

      var cells = tr.cells;
      for (var c = 0; c < cells.length; c++) {
        var td = cells[c];
        if (td.classList.contains("gm-mobile-skip") || td.classList.contains("d-none") || td.classList.contains("hide-mobile")) {
          td.classList.add("gm-mobile-skip");
          continue;
        }
        if (td.querySelector('input[type="checkbox"]') && !cleanLabel(td.textContent)) {
          td.classList.add("gm-mobile-skip");
          continue;
        }
        if (cellIsEmpty(td) && !td.querySelector(".btn, .badge, .dropdown")) {
          td.classList.add("gm-mobile-skip");
          continue;
        }
        if (headers[c] && !td.getAttribute("data-label")) {
          td.setAttribute("data-label", headers[c]);
        }
        if (td.querySelector(".btn-group, .btn, .dropdown, a.btn")) {
          td.classList.add("gm-mobile-actions");
        }
      }
      tr.classList.add("gm-mobile-card-ready");
    }
  }

  function enhanceTables(root) {
    if (!isCompact()) return;
    var scope = root && root.querySelectorAll ? root : document;
    var tables = scope.querySelectorAll ? scope.querySelectorAll(".content-wrapper table.table") : [];
    for (var i = 0; i < tables.length; i++) {
      if (!tables[i].classList.contains("table-mobile-cards")) {
        enhanceTable(tables[i]);
      } else {
        enhanceTable(tables[i]);
      }
    }
  }

  function enhanceModals() {
    if (!isCompact()) return;
    document.querySelectorAll(".modal").forEach(function (modal) {
      if (modal.id === "gmMobileMoreSheet") {
        modal.classList.add("gm-mobile-sheet-ready");
        return;
      }
      if (!modal.classList.contains("gm-mobile-sheet-ready")) {
        modal.classList.add("gm-mobile-sheet", "gm-mobile-sheet-ready");
      }
    });
  }

  function enhancePageHeader() {
    if (!isCompact()) return;
    var header = document.querySelector(".content-header");
    if (!header || header.dataset.gmEnhanced === "1") return;
    var crumb = header.querySelector(".breadcrumb .breadcrumb-item.active");
    var h1 = header.querySelector("h1");
    if (crumb && h1 && !header.querySelector(".gm-page-subtitle")) {
      var sub = document.createElement("p");
      sub.className = "gm-page-subtitle text-muted mb-0 small";
      sub.textContent = cleanLabel(crumb.textContent);
      h1.insertAdjacentElement("afterend", sub);
    }
    header.dataset.gmEnhanced = "1";
  }

  function enhanceFilterCards() {
    if (!isCompact()) return;
    document.querySelectorAll(".content .card.gm-mobile-filter-card, .content .card[data-mobile-filter='1']").forEach(function (card) {
      if (card.dataset.gmFilterEnhanced === "1") return;
      applyFilterCollapse(card);
    });
    var cards = document.querySelectorAll(".content .card");
    for (var i = 0; i < Math.min(cards.length, 3); i++) {
      var card = cards[i];
      if (card.dataset.gmFilterEnhanced === "1") continue;
      if (card.querySelector("table")) continue;
      var headerText = cleanLabel((card.querySelector(".card-header") || {}).textContent || "");
      if (!/فلتر|بحث|filter|search/i.test(headerText) && !card.querySelector(".card-body form")) continue;
      if (!card.querySelector(".card-body .form-control, .card-body select")) continue;
      applyFilterCollapse(card);
    }
  }

  function applyFilterCollapse(card) {
    if (card.dataset.gmFilterEnhanced === "1") return;
    var header = card.querySelector(".card-header");
    var body = card.querySelector(".card-body");
    if (!body) return;

    if (!header) {
      header = document.createElement("div");
      header.className = "card-header d-flex align-items-center justify-content-between py-2";
      header.innerHTML = '<h3 class="card-title mb-0"><i class="fas fa-filter ml-2"></i> فلاتر البحث</h3>';
      card.insertBefore(header, card.firstChild);
    }

    if (header.querySelector(".gm-filter-toggle")) {
      card.dataset.gmFilterEnhanced = "1";
      return;
    }

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "btn btn-sm btn-outline-secondary gm-filter-toggle";
    toggle.innerHTML = '<i class="fas fa-chevron-down"></i>';
    toggle.setAttribute("aria-expanded", "false");
    header.classList.add("d-flex", "align-items-center", "justify-content-between");
    header.appendChild(toggle);

    body.classList.add("gm-filter-body");
    body.style.display = "none";

    toggle.addEventListener("click", function () {
      var open = body.style.display !== "none";
      body.style.display = open ? "none" : "block";
      toggle.setAttribute("aria-expanded", open ? "false" : "true");
      toggle.querySelector("i").className = open ? "fas fa-chevron-down" : "fas fa-chevron-up";
    });

    card.classList.add("gm-mobile-filter-card");
    card.dataset.gmFilterEnhanced = "1";
  }

  function enhanceSelect2() {
    if (!isCompact() || !window.jQuery) return;
    window.jQuery(document).off("select2:open.gmMobile").on("select2:open.gmMobile", function () {
      var dd = document.querySelector(".select2-container--open .select2-dropdown");
      if (dd) dd.style.zIndex = "9999";
    });
  }

  function wrapPageActions() {
    if (!isCompact()) return;
    document.querySelectorAll(".content .container-fluid > .row").forEach(function (row, idx) {
      if (idx > 2 || row.dataset.gmActionBar === "1") return;
      if (row.classList.contains("gm-mobile-action-bar")) return;
      var hasButtons = row.querySelector(".btn, .btn-group");
      if (!hasButtons) return;
      row.classList.add("gm-mobile-action-bar");
      row.dataset.gmActionBar = "1";
    });
  }

  function markFilterRows() {
    document.querySelectorAll(".content form.row, .content .card-body > .row, .content .gm-filter-panel-body .row").forEach(function (row) {
      if (row.querySelector(".form-control, select, .custom-select") && !row.classList.contains("gm-filter-row")) {
        row.classList.add("gm-filter-row");
      }
    });
  }

  function initMoreSheet() {
    var btn = document.getElementById("gm-mobile-more-btn");
    var sheet = document.getElementById("gmMobileMoreSheet");
    if (!btn || !sheet || btn.dataset.gmBound === "1") return;
    btn.dataset.gmBound = "1";

    btn.addEventListener("click", function (e) {
      e.preventDefault();
      if (window.jQuery && typeof window.jQuery(sheet).modal === "function") {
        window.jQuery(sheet).modal("show");
      }
      btn.classList.add("active");
    });

    if (window.jQuery) {
      window.jQuery(sheet).on("hidden.bs.modal", function () {
        btn.classList.remove("active");
      });
    }

    sheet.querySelectorAll(".gm-more-tile[href]").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.jQuery) window.jQuery(sheet).modal("hide");
      });
    });
  }

  function initDataTablesHook() {
    if (!window.jQuery) return;
    window.jQuery(document).on("draw.dt", function (_e, settings) {
      if (!isCompact()) return;
      if (settings && settings.nTable) enhanceTable(settings.nTable);
      else enhanceTables(document);
    });
  }

  function initAjaxHook() {
    if (!window.jQuery) return;
    window.jQuery(document).ajaxComplete(function () {
      setTimeout(refresh, 80);
    });
  }

  function initMutationObserver() {
    if (!window.MutationObserver) return;
    var timer;
    var observer = new MutationObserver(function () {
      clearTimeout(timer);
      timer = setTimeout(refresh, 150);
    });
    var content = document.querySelector(".content-wrapper");
    if (content) observer.observe(content, { childList: true, subtree: true });
  }

  function refresh() {
    syncCompactBodyClass();
    if (window.GMScrollFilters && typeof window.GMScrollFilters.init === "function") {
      window.GMScrollFilters.init(document);
    }
    markFilterRows();
    if (!isCompact()) return;
    enhancePageHeader();
    enhanceTables(document);
    enhanceModals();
    wrapPageActions();
    enhanceSelect2();
  }

  window.GMMobileApp = {
    isCompact: isCompact,
    syncCompactBodyClass: syncCompactBodyClass,
    enhanceTables: enhanceTables,
    enhanceTable: enhanceTable,
    refresh: refresh,
    init: function () {
      syncCompactBodyClass();
      initMoreSheet();
      initDataTablesHook();
      initAjaxHook();
      initMutationObserver();
      refresh();
    },
  };

  document.addEventListener("DOMContentLoaded", function () {
    window.GMMobileApp.init();
  });

  window.addEventListener("gm:layout-change", function () {
    window.GMMobileApp.refresh();
  });
})(window, document);

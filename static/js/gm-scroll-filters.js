(function (window, document) {
  "use strict";

  var DEFAULT_HINT = "اسحب أفقياً أو استخدم الأسهم لعرض كل الأعمدة";
  var MIN_COLS_AUTO = 4;

  function isRtl(el) {
    var node = el || document.documentElement;
    return (window.getComputedStyle(node).direction || "rtl") === "rtl";
  }

  function getScrollEl(card) {
    return (
      card.querySelector(".gm-ledger-scroll-inner") ||
      card.querySelector(".gm-ledger-scroll") ||
      card.querySelector(".table-responsive")
    );
  }

  function scrollMetrics(el) {
    var max = Math.max(0, el.scrollWidth - el.clientWidth);
    var sl = Math.abs(el.scrollLeft);
    return { max: max, sl: sl, needs: max > 4 };
  }

  function scrollStep(el) {
    return Math.min(240, Math.max(120, el.clientWidth * 0.55));
  }

  function scrollToward(el, towardEnd) {
    var step = scrollStep(el);
    var rtl = isRtl(el);
    var delta = towardEnd ? (rtl ? -step : step) : rtl ? step : -step;
    el.scrollBy({ left: delta, behavior: "smooth" });
  }

  function scrollToEdge(el, towardEnd) {
    var m = scrollMetrics(el);
    var rtl = isRtl(el);
    var target = towardEnd ? m.max : 0;
    el.scrollTo({ left: rtl && el.scrollLeft <= 0 ? -target : target, behavior: "smooth" });
  }

  function updatePositionLabel(card, el) {
    var m = scrollMetrics(el);
    var text = m.needs ? Math.round((m.sl / (m.max || 1)) * 100) + "%" : "كامل";
    card.querySelectorAll(".gm-scroll-position").forEach(function (lab) {
      lab.textContent = text;
    });
  }

  function updateScrollCard(card) {
    var el = getScrollEl(card);
    if (!el) return;
    var m = scrollMetrics(el);
    card.classList.toggle("gm-scroll-ok", !m.needs);
    card.classList.toggle("gm-scrolled-start", m.needs && m.sl > 8);
    card.classList.toggle("gm-scrolled-end", m.needs && m.sl >= m.max - 8);
    card.querySelectorAll('[data-gm-scroll-dir="start"]').forEach(function (btn) {
      btn.disabled = !m.needs || m.sl <= 4;
    });
    card.querySelectorAll('[data-gm-scroll-dir="end"]').forEach(function (btn) {
      btn.disabled = !m.needs || m.sl >= m.max - 4;
    });
    updatePositionLabel(card, el);
  }

  function bindScrollCard(card) {
    if (!card || card.dataset.gmScrollBound === "1") return;
    var el = getScrollEl(card);
    if (!el) return;
    var hint = card.getAttribute("data-gm-scroll-hint") || DEFAULT_HINT;
    card.querySelectorAll(".gm-scroll-hint-text").forEach(function (span) {
      if (!span.textContent.trim()) span.textContent = hint;
    });
    card.querySelectorAll("[data-gm-scroll-dir]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var dir = btn.getAttribute("data-gm-scroll-dir");
        if (e.shiftKey) scrollToEdge(el, dir === "end");
        else scrollToward(el, dir === "end");
      });
    });
    el.addEventListener("scroll", function () { updateScrollCard(card); }, { passive: true });
    window.addEventListener("resize", function () { updateScrollCard(card); });
    updateScrollCard(card);
    card.dataset.gmScrollBound = "1";
  }

  function createRail(position, hint) {
    var rail = document.createElement("div");
    rail.className = "gm-scroll-rail gm-scroll-rail-" + position;
    rail.setAttribute("role", "toolbar");
    rail.innerHTML =
      '<button type="button" class="gm-scroll-btn" data-gm-scroll-dir="start" title="بداية الجدول"><i class="fas fa-chevron-right"></i></button>' +
      '<div class="gm-scroll-rail-center"><i class="fas fa-arrows-alt-h gm-scroll-rail-icon"></i>' +
      '<span class="gm-scroll-hint-text">' + hint + '</span><span class="gm-scroll-position"></span></div>' +
      '<button type="button" class="gm-scroll-btn" data-gm-scroll-dir="end" title="نهاية الجدول"><i class="fas fa-chevron-left"></i></button>';
    return rail;
  }

  function shouldAutoWrap(wrap) {
    if (wrap.closest("[data-gm-scroll-table]")) return false;
    if (wrap.classList.contains("gm-ledger-scroll-inner")) return false;
    if (wrap.closest(".no-gm-scroll, .modal, .dropdown-menu, .gm-pos-terminal")) return false;
    if (wrap.getAttribute("data-gm-no-scroll") === "1") return false;
    var table = wrap.querySelector("table");
    if (!table || table.getAttribute("data-gm-no-scroll") === "1") return false;
    if (wrap.getAttribute("data-gm-force-scroll") === "1") return true;
    if (table.querySelectorAll("thead th").length >= MIN_COLS_AUTO) return true;
    return wrap.scrollWidth > wrap.clientWidth + 8;
  }

  function wrapResponsive(wrap) {
    if (wrap.dataset.gmScrollEnhanced === "1" || !shouldAutoWrap(wrap)) return;
    var hint = wrap.getAttribute("data-gm-scroll-hint") || DEFAULT_HINT;
    var card = document.createElement("div");
    card.className = "gm-ledger-scroll-card";
    card.setAttribute("data-gm-scroll-table", "");
    card.setAttribute("data-gm-scroll-hint", hint);
    card.setAttribute("data-gm-auto-wrap", "1");
    wrap.parentNode.insertBefore(card, wrap);
    card.appendChild(createRail("top", hint));
    card.appendChild(wrap);
    card.appendChild(createRail("bottom", hint));
    wrap.classList.add("gm-ledger-scroll", "gm-ledger-scroll-inner");
    wrap.dataset.gmScrollEnhanced = "1";
    bindScrollCard(card);
  }

  function enhanceFilterPanel(panel) {
    if (!panel || panel.dataset.gmFilterBound === "1") return;
    var header = panel.querySelector(".gm-filter-panel-header, .card-header");
    var body = panel.querySelector(".gm-filter-panel-body, .card-body");
    if (!header || !body) return;
    header.classList.add("gm-filter-panel-header");
    body.classList.add("gm-filter-panel-body");
    var toggle = header.querySelector(".gm-filter-toggle");
    if (!toggle) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "btn btn-sm btn-outline-primary gm-filter-toggle";
      toggle.innerHTML = '<span class="gm-filter-toggle-label">إخفاء الفلاتر</span><i class="fas fa-chevron-up ml-1"></i>';
      header.classList.add("d-flex", "align-items-center", "justify-content-between");
      header.appendChild(toggle);
    }
    var label = toggle.querySelector(".gm-filter-toggle-label");
    var icon = toggle.querySelector("i.fas");
    function collapsed() { return body.style.display === "none"; }
    function setCollapsed(c) {
      body.style.display = c ? "none" : "";
      toggle.setAttribute("aria-expanded", c ? "false" : "true");
      if (label) label.textContent = c ? "إظهار الفلاتر" : "إخفاء الفلاتر";
      if (icon) icon.className = c ? "fas fa-chevron-down ml-1" : "fas fa-chevron-up ml-1";
      panel.setAttribute("data-gm-filter-collapsed", c ? "1" : "0");
    }
    if (panel.getAttribute("data-gm-filter-collapsed") === "1") setCollapsed(true);
    toggle.addEventListener("click", function (e) { e.stopPropagation(); setCollapsed(!collapsed()); });
    header.addEventListener("click", function (e) {
      if (e.target === toggle || toggle.contains(e.target)) return;
      if (e.target.closest("a, input, select, button:not(.gm-filter-toggle)")) return;
      setCollapsed(!collapsed());
    });
    function syncActive() {
      var active = false;
      body.querySelectorAll("input, select, textarea").forEach(function (f) {
        if (f.type === "hidden" || f.type === "submit" || f.type === "button") return;
        if (f.name === "page" || f.name === "csrf_token") return;
        var v = (f.value || "").trim();
        if (v && v !== "all") active = true;
      });
      panel.classList.toggle("gm-filter-has-active", active);
    }
    body.addEventListener("change", syncActive);
    body.addEventListener("input", syncActive);
    syncActive();
    panel.dataset.gmFilterBound = "1";
  }

  function enhanceLegacyFilterCards(root) {
    (root || document).querySelectorAll(".content .card").forEach(function (card) {
      if (card.dataset.gmFilterBound === "1" || card.classList.contains("gm-filter-panel")) return;
      if (card.querySelector("table")) return;
      var body = card.querySelector(".card-body");
      if (!body || !body.querySelector(".form-control, select")) return;
      var inputs = body.querySelectorAll(".form-control, select");
      if (inputs.length < 2) return;
      card.classList.add("gm-filter-panel");
      if (!card.hasAttribute("data-gm-filter-collapsed")) {
        var compact = window.GMLayout && window.GMLayout.isCompactLayout && window.GMLayout.isCompactLayout();
        card.setAttribute("data-gm-filter-collapsed", compact ? "1" : "0");
      }
      enhanceFilterPanel(card);
    });
  }

  function initVerticalHints() {
    var box = document.querySelector("[data-gm-vscroll-hints]");
    if (!box) {
      box = document.createElement("div");
      box.className = "gm-vscroll-hints";
      box.setAttribute("data-gm-vscroll-hints", "");
      box.innerHTML =
        '<button type="button" class="gm-vscroll-btn gm-vscroll-up" data-gm-vscroll="up"><i class="fas fa-chevron-up"></i><span>أعلى</span></button>' +
        '<button type="button" class="gm-vscroll-btn gm-vscroll-down" data-gm-vscroll="down"><i class="fas fa-chevron-down"></i><span>أسفل</span></button>';
      document.body.appendChild(box);
    }
    if (box.dataset.gmVscrollBound === "1") return;
    var root = document.querySelector(".content-wrapper") || window;
    function sync() {
      var st = root === window ? window.scrollY : root.scrollTop;
      var max = root === window
        ? document.documentElement.scrollHeight - window.innerHeight
        : root.scrollHeight - root.clientHeight;
      var up = box.querySelector('[data-gm-vscroll="up"]');
      var down = box.querySelector('[data-gm-vscroll="down"]');
      if (max < 80) {
        up && up.classList.add("gm-vscroll-hidden");
        down && down.classList.add("gm-vscroll-hidden");
        return;
      }
      up && up.classList.toggle("gm-vscroll-hidden", st < 40);
      down && down.classList.toggle("gm-vscroll-hidden", st >= max - 40);
    }
    box.querySelectorAll("[data-gm-vscroll]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var n = Math.min(480, window.innerHeight * 0.7);
        var d = btn.getAttribute("data-gm-vscroll") === "up" ? -n : n;
        if (root === window) window.scrollBy({ top: d, behavior: "smooth" });
        else root.scrollBy({ top: d, behavior: "smooth" });
      });
    });
    if (root === window) window.addEventListener("scroll", sync, { passive: true });
    else root.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    sync();
    box.dataset.gmVscrollBound = "1";
  }

  function init(root) {
    var scope = root || document;
    scope.querySelectorAll("[data-gm-scroll-table]").forEach(bindScrollCard);
    scope.querySelectorAll(".content .table-responsive").forEach(wrapResponsive);
    scope.querySelectorAll("[data-gm-filter-panel]").forEach(enhanceFilterPanel);
    enhanceLegacyFilterCards(scope);
    initVerticalHints();
  }

  window.GMScrollFilters = { init: init, bind: bindScrollCard, wrap: wrapResponsive, refresh: init };
  window.GMFinancialScroll = window.GMFinancialScroll || { init: init, bind: bindScrollCard };

  document.addEventListener("DOMContentLoaded", init);
  window.addEventListener("gm:layout-change", function () {
    document.querySelectorAll("[data-gm-scroll-table]").forEach(updateScrollCard);
    init(document);
  });
  if (window.jQuery) {
    window.jQuery(document).on("draw.dt", function () { setTimeout(init, 60); });
  }
})(window, document);

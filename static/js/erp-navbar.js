(function (window, document) {
  "use strict";

  var outsideClickBound = false;
  var escapeBound = false;

  function isCompactLayout() {
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

  function updateNavbarHeight() {
    var navbar = document.querySelector(".main-header.navbar");
    if (navbar) {
      var h = Math.ceil(navbar.getBoundingClientRect().height) + "px";
      document.documentElement.style.setProperty("--gm-navbar-height", h);
      document.documentElement.style.setProperty("--erp-header-h", h);
    }
  }

  function bindNavbarResizeObserver() {
    var navbar = document.querySelector(".main-header.navbar");
    if (!navbar || typeof ResizeObserver === "undefined") return;
    if (navbar.dataset.erpNavbarRoBound === "1") return;
    var ro = new ResizeObserver(function () {
      updateNavbarHeight();
    });
    ro.observe(navbar);
    navbar.dataset.erpNavbarRoBound = "1";
  }

  function updateFooterHeight() {
    var footer = document.querySelector(".main-footer.erp-footer");
    if (footer) {
      var h = Math.ceil(footer.getBoundingClientRect().height) + "px";
      document.documentElement.style.setProperty("--erp-footer-height", h);
    }
  }

  function bindFooterResizeObserver() {
    var footer = document.querySelector(".main-footer.erp-footer");
    if (!footer || typeof ResizeObserver === "undefined") return;
    if (footer.dataset.erpFooterRoBound === "1") return;
    var ro = new ResizeObserver(function () {
      updateFooterHeight();
    });
    ro.observe(footer);
    footer.dataset.erpFooterRoBound = "1";
  }

  function setDrawerOpen(open) {
    var body = document.body;
    body.classList.toggle("erp-sidebar-drawer-open", !!open);
    document.documentElement.classList.toggle("erp-sidebar-drawer-open", !!open);
    if (open && isCompactLayout()) {
      body.style.overflow = "hidden";
      body.style.touchAction = "none";
    } else if (!body.classList.contains("sidebar-open")) {
      body.style.overflow = "";
      body.style.touchAction = "";
    }
  }

  function syncPushmenuState() {
    var body = document.body;
    var collapsed = body.classList.contains("sidebar-collapse");
    var open = body.classList.contains("sidebar-open");
    var hidden = body.classList.contains("sidebar-hidden");
    document.querySelectorAll("[data-erp-pushmenu]").forEach(function (btn) {
      var expanded = isCompactLayout() ? open && !hidden : !collapsed && !hidden;
      btn.setAttribute("aria-expanded", expanded ? "true" : "false");
      btn.classList.toggle("erp-pushmenu-active", expanded);
      btn.setAttribute(
        "title",
        isCompactLayout()
          ? expanded
            ? "إغلاق القائمة"
            : "فتح القائمة"
          : expanded
            ? "توسيع القائمة"
            : "تصغير القائمة"
      );
    });
  }

  function ensureBackdrop() {
    var el = document.getElementById("gm-sidebar-backdrop");
    if (el) return el;
    el = document.createElement("div");
    el.id = "gm-sidebar-backdrop";
    el.setAttribute("aria-hidden", "true");
    document.body.appendChild(el);
    el.addEventListener("click", function (e) {
      if (!isCompactLayout()) return;
      try {
        e.preventDefault();
      } catch (_) {}
      closeCompactSidebar();
    });
    return el;
  }

  function closeCompactSidebar() {
    document.body.classList.remove("sidebar-open");
    var backdrop = document.getElementById("gm-sidebar-backdrop");
    if (backdrop) backdrop.style.display = "none";
    setDrawerOpen(false);
    syncPushmenuState();
  }

  function handlePushmenuClick(e) {
    var body = document.body;
    if (body.classList.contains("sidebar-hidden")) {
      try {
        e.preventDefault();
      } catch (_) {}
      return;
    }

    try {
      e.preventDefault();
    } catch (_) {}
    try {
      e.stopImmediatePropagation();
    } catch (_) {}
    try {
      e.stopPropagation();
    } catch (_) {}

    if (isCompactLayout()) {
      body.classList.remove("sidebar-collapse");
      body.classList.toggle("sidebar-open");
      var backdrop = ensureBackdrop();
      var isOpen = body.classList.contains("sidebar-open");
      backdrop.style.display = isOpen ? "block" : "none";
      setDrawerOpen(isOpen);
    } else {
      body.classList.toggle("sidebar-collapse");
      if (typeof window.applySidebarPosition === "function") {
        var pos = "left";
        try {
          pos = localStorage.getItem("sidebarPosition") || "left";
        } catch (_) {}
        window.applySidebarPosition(pos);
      }
      try {
        window.dispatchEvent(new Event("resize"));
      } catch (_) {}
    }
    syncPushmenuState();
  }

  function bindOutsideClick() {
    if (outsideClickBound) return;
    outsideClickBound = true;
    document.body.addEventListener("click", function (e) {
      if (!isCompactLayout() || !document.body.classList.contains("sidebar-open")) {
        return;
      }
      var btns = Array.from(document.querySelectorAll("[data-erp-pushmenu]"));
      var clickedPush = btns.some(function (btn) {
        return btn && btn.contains(e.target);
      });
      var sidebar = document.querySelector(".main-sidebar");
      if (sidebar && !sidebar.contains(e.target) && !clickedPush) {
        closeCompactSidebar();
      }
    });
  }

  function bindEscapeKey() {
    if (escapeBound) return;
    escapeBound = true;
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape" && e.key !== "Esc") return;
      if (!isCompactLayout() || !document.body.classList.contains("sidebar-open")) return;
      closeCompactSidebar();
    });
  }

  function bindPushmenu() {
    document.querySelectorAll("[data-erp-pushmenu]").forEach(function (btn) {
      if (!btn || btn.dataset.erpPushmenuBound === "1") return;
      btn.addEventListener("click", handlePushmenuClick, true);
      btn.dataset.erpPushmenuBound = "1";
    });
    syncPushmenuState();
  }

  function initCompactLayout() {
    if (!isCompactLayout()) {
      document.body.classList.remove("erp-sidebar-drawer-open");
      document.documentElement.classList.remove("erp-sidebar-drawer-open");
      document.body.style.overflow = "";
      document.body.style.touchAction = "";
      return;
    }
    updateNavbarHeight();
    document.body.classList.add("gm-mobile");
    document.body.classList.remove("sidebar-collapse");
    var backdrop = ensureBackdrop();
    if (!document.body.classList.contains("sidebar-open")) {
      backdrop.style.display = "none";
      setDrawerOpen(false);
    } else {
      backdrop.style.display = "block";
      setDrawerOpen(true);
    }
    bindPushmenu();
    bindOutsideClick();
    bindEscapeKey();
    syncPushmenuState();
  }

  function normalizeFxPayload(data, code) {
    if (!data) return null;
    var block = data[code];
    if (block && typeof block === "object") {
      if (block.source === "default") return null;
      var r = block.rate != null ? Number(block.rate) : NaN;
      if (!isNaN(r) && r > 0) return block;
      if (block.success === false) return null;
      if (block.rate != null) return block;
    }
    var flat = data[code + "_rate"] != null ? data[code + "_rate"] : data[code];
    if (flat != null && typeof flat !== "object") {
      return { rate: Number(flat), source: data.source || "legacy" };
    }
    return null;
  }

  function formatRange(low, high) {
    if (low == null || high == null || isNaN(low) || isNaN(high)) return "";
    return Number(low).toFixed(2) + "–" + Number(high).toFixed(2);
  }

  function applyFxBlock(code, block) {
    if (!block || block.rate == null || block.rate === undefined) {
      document.querySelectorAll('.erp-fx-chip[data-fx="' + code + '"]').forEach(function (chip) {
        chip.classList.remove("erp-fx-rates--loading");
        chip.setAttribute("title", "سعر غير متوفر — فعّل الأونلاين أو أدخل سعراً يدوياً لليوم");
      });
      return;
    }
    var rate = Number(block.rate);
    if (isNaN(rate) || rate <= 0) return;
    var rateText = rate.toFixed(2);
    var id = code === "USD" ? "#usd-rate" : code === "JOD" ? "#jod-rate" : null;
    var navClass = code === "USD" ? ".gm-nav-usd-rate" : ".gm-nav-jod-rate";
    var rangeClass = code === "USD" ? ".gm-nav-usd-range" : ".gm-nav-jod-range";
    if (id) {
      document.querySelectorAll(id).forEach(function (el) {
        el.textContent = rateText;
      });
    }
    document.querySelectorAll(navClass).forEach(function (el) {
      el.textContent = rateText;
    });
    var dayR = formatRange(block.day_low, block.day_high);
    var weekR = formatRange(block.week_low, block.week_high);
    var srcLabel =
      block.source === "investing"
        ? "Investing"
        : block.source === "online"
          ? "أونلاين"
          : block.source === "manual" || block.source === "online_cached"
            ? "يدوي"
            : block.source === "database_stored"
              ? "من السجل"
              : block.source || "";
    var tip =
      (srcLabel ? "مصدر: " + srcLabel + " · " : "") +
      (dayR ? "يوم " + dayR : "") +
      (weekR ? (dayR ? " · " : "") + "أسبوع " + weekR : "");
    document.querySelectorAll('.erp-fx-chip[data-fx="' + code + '"]').forEach(function (chip) {
      chip.classList.remove("erp-fx-rates--loading");
      chip.classList.toggle("erp-fx-rates--live", block.source === "investing" || block.source === "online");
      chip.classList.toggle(
        "erp-fx-rates--manual",
        block.source === "manual" || block.source === "online_cached" || block.source === "database_stored"
      );
      if (tip) chip.setAttribute("title", tip);
    });
    document.querySelectorAll('[data-fx-day="' + code + '"]').forEach(function (el) {
      el.textContent = dayR ? "ي" + dayR : "";
    });
    document.querySelectorAll('[data-fx-week="' + code + '"]').forEach(function (el) {
      el.textContent = weekR ? "أ" + weekR : "";
    });
    document.querySelectorAll(rangeClass).forEach(function (el) {
      var parts = [];
      if (dayR) parts.push("يوم " + dayR);
      if (weekR) parts.push("أسبوع " + weekR);
      el.textContent = parts.join(" · ");
    });
  }

  var fxRefreshTimer = null;
  var fxRefreshFallbackMs = 5 * 60 * 1000;

  function scheduleFxRefresh(intervalMs) {
    var ms = Number(intervalMs);
    if (isNaN(ms) || ms < 300000) {
      ms = fxRefreshFallbackMs;
    }
    if (fxRefreshTimer) {
      clearInterval(fxRefreshTimer);
    }
    fxRefreshTimer = window.setInterval(updateExchangeRates, ms);
  }

  function updateExchangeRates() {
    return fetch("/api/exchange-rates", {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        applyFxBlock(
          "USD",
          normalizeFxPayload(data, "USD") ||
            (data.USD_rate > 0 ? { rate: data.USD_rate, source: data.source } : null)
        );
        applyFxBlock(
          "JOD",
          normalizeFxPayload(data, "JOD") ||
            (data.JOD_rate > 0 ? { rate: data.JOD_rate, source: data.source } : null)
        );
        if (data.refresh_interval_seconds) {
          scheduleFxRefresh(Number(data.refresh_interval_seconds) * 1000);
        }
        try {
          window.dispatchEvent(new CustomEvent("erp:fx-rates-updated", { detail: data }));
        } catch (_) {}
      })
      .catch(function () {
        document.querySelectorAll(".erp-fx-rates").forEach(function (wrap) {
          wrap.classList.remove("erp-fx-rates--loading");
        });
      });
  }

  var resizeTimer;
  function onLayoutChange() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      updateNavbarHeight();
      updateFooterHeight();
      if (isCompactLayout()) {
        initCompactLayout();
      } else {
        closeCompactSidebar();
        document.body.classList.remove("gm-mobile");
        syncPushmenuState();
      }
    }, 120);
  }

  window.ErpNavbar = {
    bindPushmenu: bindPushmenu,
    syncPushmenuState: syncPushmenuState,
    updateExchangeRates: updateExchangeRates,
    isCompactLayout: isCompactLayout,
    handlePushmenuClick: handlePushmenuClick,
    initCompactLayout: initCompactLayout,
    closeCompactSidebar: closeCompactSidebar,
    updateNavbarHeight: updateNavbarHeight,
    updateFooterHeight: updateFooterHeight,
  };

  document.addEventListener("DOMContentLoaded", function () {
    bindPushmenu();
    updateNavbarHeight();
    updateFooterHeight();
    bindNavbarResizeObserver();
    bindFooterResizeObserver();
    initCompactLayout();
    updateExchangeRates();
    window.addEventListener("resize", onLayoutChange);
    window.addEventListener("orientationchange", function () {
      setTimeout(onLayoutChange, 200);
    });
    window.addEventListener("gm:layout-change", onLayoutChange);
  });
})(window, document);

(function (window, document) {
  "use strict";

  var BP = {
    mobile: "(max-width: 575.98px)",
    tablet: "(min-width: 576px) and (max-width: 991.98px)",
    desktop: "(min-width: 992px)",
  };

  function detectNaturalMode() {
    try {
      if (window.matchMedia(BP.mobile).matches) return "mobile";
      if (window.matchMedia(BP.tablet).matches) return "tablet";
      return "desktop";
    } catch (_) {
      return "desktop";
    }
  }

  function getStoredUIMode() {
    try {
      var v = localStorage.getItem("ui_mode") || "auto";
      return v === "mobile" || v === "tablet" || v === "desktop" ? v : "auto";
    } catch (_) {
      return "auto";
    }
  }

  function isCompactLayout() {
    var mode = (document.documentElement.getAttribute("data-ui-mode") || "").toLowerCase();
    if (mode === "mobile" || mode === "tablet") return true;
    if (mode === "desktop") return false;
    try {
      return window.matchMedia("(max-width: 991.98px)").matches;
    } catch (_) {
      return false;
    }
  }

  function setMobileStylesheetEnabled(enabled) {
    var link = document.getElementById("mobile-css");
    if (!link) return;
    link.media = enabled ? "all" : link.getAttribute("data-default-media") || "(max-width: 575.98px)";
  }

  function cleanupCompactLayout() {
    var body = document.body;
    if (!body) return;
    body.classList.remove("sidebar-open", "gm-mobile");
    var backdrop = document.getElementById("gm-sidebar-backdrop");
    if (backdrop) backdrop.style.display = "none";
  }

  function reconcileUIModeOnResize() {
    var stored = getStoredUIMode();
    if (stored === "auto") {
      if (typeof window.applyUIMode === "function") window.applyUIMode("auto", true);
      return;
    }
    var natural = detectNaturalMode();
    if (stored !== natural) {
      try {
        localStorage.setItem("ui_mode", "auto");
      } catch (_) {}
      if (typeof window.applyUIMode === "function") window.applyUIMode("auto", true);
    }
  }

  function bindBreakpointWatchers() {
    [BP.mobile, BP.tablet, BP.desktop].forEach(function (q) {
      try {
        var mq = window.matchMedia(q);
        var fn = function () {
          reconcileUIModeOnResize();
          if (typeof window.applySidebarPosition === "function") {
            var pos = "left";
            try {
              pos = localStorage.getItem("sidebarPosition") || "left";
            } catch (_) {}
            window.applySidebarPosition(pos);
          }
          if (!isCompactLayout()) cleanupCompactLayout();
        };
        if (mq.addEventListener) mq.addEventListener("change", fn);
        else if (mq.addListener) mq.addListener(fn);
      } catch (_) {}
    });
  }

  window.GMLayout = {
    detectNaturalMode: detectNaturalMode,
    getStoredUIMode: getStoredUIMode,
    isCompactLayout: isCompactLayout,
    reconcileUIModeOnResize: reconcileUIModeOnResize,
    cleanupCompactLayout: cleanupCompactLayout,
    setMobileStylesheetEnabled: setMobileStylesheetEnabled,
    bindBreakpointWatchers: bindBreakpointWatchers,
  };

  document.addEventListener("DOMContentLoaded", function () {
    bindBreakpointWatchers();
  });

  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(reconcileUIModeOnResize, 120);
  });

  window.addEventListener("orientationchange", function () {
    setTimeout(reconcileUIModeOnResize, 200);
  });
})(window, document);

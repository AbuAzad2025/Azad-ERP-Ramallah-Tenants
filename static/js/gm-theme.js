/**
 * نظام الثيم: فاتح/ليلي + فلسطيني/خليجي
 */
(function () {
  if (window.__GM_THEME_INIT__) return;
  window.__GM_THEME_INIT__ = true;

  const THEME_KEY = "gmTheme";
  const VARIANT_KEY = "gmVariant";
  const LEGACY_KEY = "securityDarkMode";

  function isDarkEnabled() {
    return document.documentElement.getAttribute("data-gm-theme") === "dark";
  }

  function getVariant() {
    try {
      var v = localStorage.getItem(VARIANT_KEY);
      if (v === "gulf" || v === "palestinian") return v;
    } catch (e) {}
    return "palestinian";
  }

  function updateIcons(isDark) {
    [
      document.getElementById("darkModeToggleNavbar"),
      document.getElementById("darkModeToggle"),
    ]
      .filter(Boolean)
      .forEach(function (el) {
        if (el.tagName === "INPUT" && el.type === "checkbox") {
          el.checked = !!isDark;
          return;
        }
        var icon = el.querySelector("i");
        if (icon) {
          icon.className = isDark ? "fas fa-sun" : "fas fa-moon";
        }
        el.title = isDark ? "الوضع النهاري" : "الوضع الليلي";
        el.setAttribute("aria-label", el.title);
      });
  }

  function updateVariantButton(variant) {
    var btn = document.getElementById("gmVariantToggleNavbar");
    if (!btn) return;
    var icon = btn.querySelector("i");
    if (icon) {
      icon.className = variant === "gulf" ? "fas fa-mosque" : "fas fa-flag";
    }
    btn.title = variant === "gulf" ? "الستايل الخليجي — اضغط للفلسطيني" : "الستايل الفلسطيني — اضغط للخليجي";
    btn.setAttribute("aria-label", btn.title);
  }

  function applyTheme(isDark, persist) {
    var root = document.documentElement;
    root.setAttribute("data-gm-theme", isDark ? "dark" : "light");
    document.body.classList.toggle("dark-mode", !!isDark);
    if (persist !== false) {
      try {
        localStorage.setItem(THEME_KEY, isDark ? "dark" : "light");
        localStorage.removeItem(LEGACY_KEY);
      } catch (e) {}
    }
    updateIcons(isDark);
  }

  function applyVariant(variant, persist) {
    var v = variant === "gulf" ? "gulf" : "palestinian";
    var root = document.documentElement;
    root.setAttribute("data-gm-variant", v);
    root.setAttribute("data-gm-pattern", v);
    if (persist !== false) {
      try {
        localStorage.setItem(VARIANT_KEY, v);
      } catch (e) {}
    }
    updateVariantButton(v);
  }

  function loadThemePreference() {
    var saved = null;
    try {
      saved = localStorage.getItem(THEME_KEY);
      if (!saved) {
        var leg = localStorage.getItem(LEGACY_KEY);
        if (leg === "true") saved = "dark";
        if (leg === "false") saved = "light";
      }
    } catch (e) {}
    if (saved === "dark") return true;
    if (saved === "light") return false;
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    } catch (e) {
      return false;
    }
  }

  function applyAll(persist) {
    applyVariant(getVariant(), persist);
    applyTheme(loadThemePreference(), persist);
  }

  window.toggleDarkMode = function () {
    applyTheme(!isDarkEnabled());
  };

  window.gmSetTheme = function (mode) {
    applyTheme(mode === "dark");
  };

  window.gmSetVariant = function (variant) {
    applyVariant(variant);
  };

  window.gmToggleVariant = function () {
    applyVariant(getVariant() === "gulf" ? "palestinian" : "gulf");
  };

  applyAll(false);

  document.addEventListener("DOMContentLoaded", function () {
    applyAll(false);
    var cb = document.getElementById("darkModeToggle");
    if (cb && cb.type === "checkbox") {
      cb.addEventListener("change", function () {
        applyTheme(!!cb.checked);
      });
    }
    try {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function (ev) {
        if (localStorage.getItem(THEME_KEY)) return;
        applyTheme(ev.matches, false);
      });
    } catch (e) {}
  });
})();

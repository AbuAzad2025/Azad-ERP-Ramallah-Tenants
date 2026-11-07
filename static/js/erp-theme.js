/**
 * ERP Theme System — variant (palestinian|gulf) + mode (light|dark)
 */
(function (global) {
  "use strict";

  var KEY_VARIANT = "erp_theme_variant";
  var KEY_MODE = "erp_theme_mode";
  var DEFAULT_VARIANT = "palestinian";
  var DEFAULT_MODE = "light";

  function read(key, fallback) {
    try {
      var v = localStorage.getItem(key);
      return v || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function write(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (e) {}
  }

  function apply(variant, mode) {
    var html = document.documentElement;
    var body = document.body;
    if (!html) return;

    variant = variant === "gulf" ? "gulf" : "palestinian";
    mode = mode === "dark" ? "dark" : "light";

    html.setAttribute("data-erp-variant", variant);
    html.setAttribute("data-erp-mode", mode);
    html.setAttribute("data-theme", mode);

    if (body) {
      body.classList.toggle("dark-mode", mode === "dark");
      body.classList.toggle("erp-dark", mode === "dark");
    }

    write(KEY_VARIANT, variant);
    write(KEY_MODE, mode);

    global.dispatchEvent(
      new CustomEvent("erp-theme-change", { detail: { variant: variant, mode: mode } })
    );

    updateSwitcherUI();
    updateNprogressColor();
  }

  function getTheme() {
    return {
      variant: read(KEY_VARIANT, DEFAULT_VARIANT),
      mode: read(KEY_MODE, DEFAULT_MODE),
    };
  }

  function updateNprogressColor() {
    if (typeof NProgress === "undefined") return;
    var primary = getComputedStyle(document.documentElement).getPropertyValue("--erp-primary").trim();
    if (!primary) return;
    var bar = document.querySelector("#nprogress .bar");
    if (bar) bar.style.background = primary;
  }

  function updateSwitcherUI() {
    var t = getTheme();
    document.querySelectorAll("[data-erp-theme-variant]").forEach(function (btn) {
      var on = btn.getAttribute("data-erp-theme-variant") === t.variant;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    document.querySelectorAll("[data-erp-theme-mode]").forEach(function (btn) {
      var on = btn.getAttribute("data-erp-theme-mode") === t.mode;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    var moon = document.querySelector("#darkModeToggleNavbar i");
    if (moon) {
      moon.className = t.mode === "dark" ? "fas fa-sun" : "fas fa-moon";
    }
  }

  function initEarly() {
    apply(read(KEY_VARIANT, DEFAULT_VARIANT), read(KEY_MODE, DEFAULT_MODE));
  }

  if (document.documentElement) {
    initEarly();
  } else {
    document.addEventListener("DOMContentLoaded", initEarly);
  }

  global.setErpTheme = function (variant, mode) {
    apply(variant || read(KEY_VARIANT, DEFAULT_VARIANT), mode || read(KEY_MODE, DEFAULT_MODE));
  };

  global.toggleErpThemeMode = function () {
    var t = getTheme();
    apply(t.variant, t.mode === "dark" ? "light" : "dark");
  };

  global.setErpThemeVariant = function (variant) {
    var t = getTheme();
    apply(variant, t.mode);
  };

  global.toggleDarkMode = function () {
    global.toggleErpThemeMode();
  };

  document.addEventListener("DOMContentLoaded", function () {
    updateSwitcherUI();
    document.querySelectorAll("[data-erp-theme-variant]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        global.setErpThemeVariant(btn.getAttribute("data-erp-theme-variant"));
      });
    });
    document.querySelectorAll("[data-erp-theme-mode]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        var t = getTheme();
        global.setErpTheme(t.variant, btn.getAttribute("data-erp-theme-mode"));
      });
    });
  });
})(window);

/**
 * حاسبة النافبار — عادي / مالي / علمي
 */
(function (window, document) {
  "use strict";

  if (window.__ERP_CALC_INIT__) return;
  window.__ERP_CALC_INIT__ = true;

  var MODE = "standard";
  var display = "0";
  var expr = "";
  var std = { acc: null, op: null, fresh: true };
  var sciDeg = true;

  var STANDARD_KEYS = [
    ["C", "CE", "⌫", "/"],
    ["7", "8", "9", "*"],
    ["4", "5", "6", "-"],
    ["1", "2", "3", "+"],
    ["±", "0", ".", "="],
  ];

  var SCI_KEYS = [
    ["2nd", "(", ")", "⌫", "C"],
    ["sin", "cos", "tan", "π", "/"],
    ["x²", "xʸ", "√", "log", "*"],
    ["7", "8", "9", "-", "ln"],
    ["4", "5", "6", "+", "e"],
    ["1", "2", "3", "=", "%"],
    ["±", "0", ".", "Ans", "Deg"],
  ];

  function $(id) {
    return document.getElementById(id);
  }

  function fmtNum(n, dec) {
    if (!isFinite(n)) return "خطأ";
    var d = dec == null ? 10 : dec;
    var s = Number(n).toPrecision(12);
    var x = parseFloat(s);
    if (Math.abs(x) >= 1e9 || (Math.abs(x) < 1e-6 && x !== 0)) {
      return x.toExponential(6);
    }
    return x.toLocaleString("en-US", {
      maximumFractionDigits: d,
      minimumFractionDigits: 0,
    });
  }

  function parseDisplay() {
    return parseFloat(String(display).replace(/,/g, "")) || 0;
  }

  function setDisplay(val, sub) {
    display = val;
    var el = $("erpCalcDisplay");
    var ex = $("erpCalcExpr");
    var hint = $("erpCalcHint");
    if (el) el.textContent = display;
    if (ex) ex.textContent = sub || expr || "";
    if (hint) {
      if (MODE === "financial") hint.textContent = "الوضع المالي: صرف، ض.ق.م، هامش";
      else if (MODE === "scientific") hint.textContent = sciDeg ? "زاوية: درجات" : "زاوية: راديان";
      else hint.textContent = "";
    }
  }

  function syncFxRatesFromNavbar() {
    var usdEl = $("usd-rate") || document.querySelector('.erp-fx-chip[data-fx="USD"] .erp-fx-rate');
    var jodEl = $("jod-rate") || document.querySelector('.erp-fx-chip[data-fx="JOD"] .erp-fx-rate');
    var usd = usdEl ? parseFloat(String(usdEl.textContent).replace(/[^\d.]/g, "")) : NaN;
    var jod = jodEl ? parseFloat(String(jodEl.textContent).replace(/[^\d.]/g, "")) : NaN;
    var u = $("erpCalcFxUsd");
    var j = $("erpCalcFxJod");
    if (u) u.textContent = isFinite(usd) ? fmtNum(usd, 4) : "--";
    if (j) j.textContent = isFinite(jod) ? fmtNum(jod, 4) : "--";
    return { USD: usd, JOD: jod, ILS: 1 };
  }

  function getRateMap() {
    var r = syncFxRatesFromNavbar();
    return {
      USD: isFinite(r.USD) ? r.USD : null,
      JOD: isFinite(r.JOD) ? r.JOD : null,
      ILS: 1,
    };
  }

  function convertFx(amount, from, to) {
    var rates = getRateMap();
    if (!isFinite(amount)) return null;
    var ils = amount;
    if (from === "USD") {
      if (!rates.USD) return null;
      ils = amount * rates.USD;
    } else if (from === "JOD") {
      if (!rates.JOD) return null;
      ils = amount * rates.JOD;
    }
    if (to === "ILS") return ils;
    if (to === "USD") {
      if (!rates.USD) return null;
      return ils / rates.USD;
    }
    if (to === "JOD") {
      if (!rates.JOD) return null;
      return ils / rates.JOD;
    }
    return ils;
  }

  function updateFxResult() {
    var amtIn = $("erpCalcFxAmount");
    var from = $("erpCalcFxFrom");
    var to = $("erpCalcFxTo");
    var out = $("erpCalcFxResult");
    if (!amtIn || !from || !to || !out) return;
    var amount = parseFloat(String(amtIn.value).replace(/,/g, "")) || 0;
    var res = convertFx(amount, from.value, to.value);
    if (res == null) {
      out.textContent = "سعر غير متوفر — انتظر تحميل الصرف";
      out.classList.add("text-danger");
      return;
    }
    out.classList.remove("text-danger");
    var sym = to.value === "ILS" ? "₪" : to.value === "USD" ? "USD" : "JOD";
    out.textContent = fmtNum(res, 4) + " " + sym;
    setDisplay(fmtNum(res, 6), amount + " " + from.value + " → " + to.value);
  }

  function stdClear(all) {
    if (all) {
      std.acc = null;
      std.op = null;
    }
    display = "0";
    std.fresh = true;
    setDisplay(display);
  }

  function stdInputDigit(d) {
    if (std.fresh || display === "0") {
      display = d;
      std.fresh = false;
    } else {
      display += d;
    }
    setDisplay(display);
  }

  function stdInputDot() {
    if (std.fresh) {
      display = "0.";
      std.fresh = false;
    } else if (display.indexOf(".") === -1) {
      display += ".";
    }
    setDisplay(display);
  }

  function stdApplyOp(op) {
    var cur = parseDisplay();
    if (std.acc == null) {
      std.acc = cur;
    } else if (!std.fresh && std.op) {
      std.acc = stdCompute(std.acc, cur, std.op);
      display = fmtNum(std.acc, 10);
    }
    std.op = op;
    std.fresh = true;
    expr = fmtNum(std.acc, 8) + " " + op;
    setDisplay(display, expr);
  }

  function stdCompute(a, b, op) {
    switch (op) {
      case "+":
        return a + b;
      case "-":
        return a - b;
      case "*":
        return a * b;
      case "/":
        return b === 0 ? NaN : a / b;
      default:
        return b;
    }
  }

  function stdEquals() {
    var cur = parseDisplay();
    if (std.op && std.acc != null) {
      var r = stdCompute(std.acc, cur, std.op);
      expr = fmtNum(std.acc, 8) + " " + std.op + " " + cur + " =";
      display = fmtNum(r, 10);
      std.acc = null;
      std.op = null;
      std.fresh = true;
      setDisplay(display, expr);
    }
  }

  function stdPercent() {
    var cur = parseDisplay();
    display = fmtNum(cur / 100, 10);
    setDisplay(display);
  }

  function stdToggleSign() {
    var cur = parseDisplay();
    display = fmtNum(-cur, 10);
    setDisplay(display);
  }

  function sciToExpr() {
    var s = expr || display;
    s = s.replace(/×/g, "*").replace(/÷/g, "/").replace(/π/g, "PI").replace(/√\(/g, "sqrt(");
    s = s.replace(/(\d+)xʸ/g, "pow($1,").replace(/x²/g, "**2");
    return s;
  }

  function sciEval() {
    try {
      var s = sciToExpr();
      if (!s.trim()) s = display;
      var fn = sciDeg ? "DEG" : "RAD";
      var PI = Math.PI;
      var DEG = Math.PI / 180;
      var sin = function (x) {
        return Math.sin(fn === "DEG" ? x * DEG : x);
      };
      var cos = function (x) {
        return Math.cos(fn === "DEG" ? x * DEG : x);
      };
      var tan = function (x) {
        return Math.tan(fn === "DEG" ? x * DEG : x);
      };
      var sqrt = Math.sqrt;
      var log = Math.log10;
      var ln = Math.log;
      var pow = Math.pow;
      var e = Math.E;
      // eslint-disable-next-line no-new-func
      var result = Function(
        "sin",
        "cos",
        "tan",
        "sqrt",
        "log",
        "ln",
        "pow",
        "PI",
        "e",
        "return (" + s + ")"
      )(sin, cos, tan, sqrt, log, ln, pow, PI, e);
      if (!isFinite(result)) throw new Error("nan");
      display = fmtNum(result, 10);
      expr = s + " =";
      setDisplay(display, expr);
    } catch (err) {
      display = "خطأ";
      setDisplay(display, "تعبير غير صالح");
    }
  }

  function appendSci(tok) {
    if (tok === "C") {
      expr = "";
      display = "0";
      setDisplay(display);
      return;
    }
    if (tok === "⌫") {
      if (expr.length) expr = expr.slice(0, -1);
      else display = display.length > 1 ? display.slice(0, -1) : "0";
      setDisplay(expr || display, expr);
      return;
    }
    if (tok === "=") {
      sciEval();
      return;
    }
    if (tok === "Deg") {
      sciDeg = !sciDeg;
      setDisplay(display);
      return;
    }
    if (tok === "2nd") return;
    if (tok === "Ans") {
      expr += display;
      setDisplay(display, expr);
      return;
    }
    var map = {
      "×": "*",
      "÷": "/",
      "x²": "**2",
      "xʸ": "**",
      "√": "sqrt(",
      "π": "PI",
    };
    var t = map[tok] || tok;
    if (tok === "sin" || tok === "cos" || tok === "tan" || tok === "log" || tok === "ln") {
      t = tok + "(";
    }
    expr += t;
    setDisplay(expr, expr);
  }

  function onKey(key) {
    if (MODE === "financial" && ["+", "-", "*", "/", "="].indexOf(key) >= 0) {
      /* fall through to standard for keypad under financial */
    }
    if (MODE === "scientific") {
      appendSci(key);
      return;
    }
    if (key === "C") stdClear(true);
    else if (key === "CE") stdClear(false);
    else if (key === "⌫") {
      if (display.length > 1) display = display.slice(0, -1);
      else display = "0";
      setDisplay(display);
    } else if (key === "=") stdEquals();
    else if (key === "±") stdToggleSign();
    else if (key === "%") stdPercent();
    else if (key === ".") stdInputDot();
    else if ("+-*/".indexOf(key) >= 0) stdApplyOp(key);
    else if (/^\d$/.test(key)) stdInputDigit(key);
  }

  function renderKeypad() {
    var pad = $("erpCalcKeypad");
    if (!pad) return;
    var keys = MODE === "scientific" ? SCI_KEYS : STANDARD_KEYS;
    pad.className =
      "erp-calc-keypad " +
      (MODE === "scientific" ? "erp-calc-keypad--scientific" : "erp-calc-keypad--standard");
    pad.innerHTML = "";
    keys.forEach(function (row) {
      row.forEach(function (k) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "erp-calc-key";
        btn.textContent = k;
        if ("+-*/=⌫".indexOf(k) >= 0 || k === "C" || k === "CE") btn.classList.add("erp-calc-key--op");
        if (k === "=") btn.classList.add("erp-calc-key--eq");
        if (
          [
            "sin",
            "cos",
            "tan",
            "log",
            "ln",
            "√",
            "x²",
            "xʸ",
            "π",
            "2nd",
            "Deg",
            "Ans",
          ].indexOf(k) >= 0
        ) {
          btn.classList.add("erp-calc-key--fn");
        }
        btn.setAttribute("data-erp-calc-key", k);
        btn.addEventListener("click", function () {
          onKey(k);
        });
        pad.appendChild(btn);
      });
    });
  }

  function setMode(m) {
    MODE = m;
    document.querySelectorAll("[data-erp-calc-mode]").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-erp-calc-mode") === m);
    });
    var fin = $("erpCalcFinancial");
    if (fin) fin.classList.toggle("d-none", m !== "financial");
    stdClear(true);
    expr = "";
    renderKeypad();
    if (m === "financial") {
      syncFxRatesFromNavbar();
      updateFxResult();
    }
    setDisplay("0");
  }

  function bindPanel(root) {
    if (!root || root.__erpCalcBound) return;
    root.__erpCalcBound = true;

    root.querySelectorAll("[data-erp-calc-mode]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setMode(btn.getAttribute("data-erp-calc-mode"));
      });
    });

    var amt = root.querySelector("#erpCalcFxAmount");
    var from = root.querySelector("#erpCalcFxFrom");
    var to = root.querySelector("#erpCalcFxTo");
    if (amt) {
      amt.addEventListener("input", updateFxResult);
    }
    if (from) from.addEventListener("change", updateFxResult);
    if (to) to.addEventListener("change", updateFxResult);

    root.querySelectorAll("[data-erp-calc-fx-quick]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (amt) amt.value = btn.getAttribute("data-erp-calc-fx-quick");
        updateFxResult();
      });
    });

    root.querySelectorAll("[data-erp-calc-vat]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var v = parseFloat(btn.getAttribute("data-erp-calc-vat")) || 16;
        var base = parseFloat(String(amt && amt.value).replace(/,/g, "")) || parseDisplay();
        var tax = base * (v / 100);
        var total = base + tax;
        var resEl = $("erpCalcFxResult");
        if (resEl) {
          resEl.textContent =
            "أساس " + fmtNum(base, 2) + " + ض.ق.م " + fmtNum(tax, 2) + " = " + fmtNum(total, 2);
        }
        setDisplay(fmtNum(total, 4), "ض.ق.م " + v + "%");
      });
    });

    root.querySelectorAll("[data-erp-calc-margin]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var m = parseFloat(btn.getAttribute("data-erp-calc-margin")) || 20;
        var cost = parseFloat(String(amt && amt.value).replace(/,/g, "")) || parseDisplay();
        var sell = cost * (1 + m / 100);
        var resEl = $("erpCalcFxResult");
        if (resEl) {
          resEl.textContent =
            "تكلفة " + fmtNum(cost, 2) + " + هامش " + m + "% → بيع " + fmtNum(sell, 2);
        }
        setDisplay(fmtNum(sell, 4), "هامش " + m + "%");
      });
    });
  }

  function openMobileCalc() {
    var panel = $("erpCalcPanel");
    var body = $("erpCalcModalBody");
    var modal = $("erpCalcModal");
    if (!panel || !body || !modal) return;
    body.appendChild(panel);
    panel.classList.add("erp-calc-panel--in-modal");
    panel.classList.remove("dropdown-menu");
    if (window.jQuery && window.$ && $.fn.modal) {
      $(modal).modal("show");
      $(modal).on("hidden.bs.modal", function () {
        var wrap = $("erpCalcDropdownWrap");
        if (wrap) wrap.appendChild(panel);
        panel.classList.remove("erp-calc-panel--in-modal");
        panel.classList.add("dropdown-menu");
      });
    }
  }

  function init() {
    var wrap = $("erpCalcDropdownWrap");
    var panel = $("erpCalcPanel");
    if (!wrap || !panel) return;

    bindPanel(panel);
    renderKeypad();
    setMode("standard");

    wrap.addEventListener("show.bs.dropdown", function () {
      syncFxRatesFromNavbar();
      if (MODE === "financial") updateFxResult();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var open =
          wrap.querySelector(".dropdown-menu.show") || document.querySelector(".erp-calc-panel.show");
        if (open && window.jQuery) {
          $(wrap).find(".dropdown-toggle").dropdown("hide");
        }
      }
    });

    var mobileBtn = document.querySelector("[data-erp-calc-mobile-open]");
    if (mobileBtn) {
      mobileBtn.addEventListener("click", function (e) {
        e.preventDefault();
        openMobileCalc();
      });
    }

    window.addEventListener("erp:fx-rates-updated", function () {
      syncFxRatesFromNavbar();
      if (MODE === "financial") updateFxResult();
    });

    setInterval(function () {
      if (document.querySelector(".erp-calc-panel.show") || $("erpCalcModal")?.classList.contains("show")) {
        syncFxRatesFromNavbar();
      }
    }, 15000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.ErpCalculator = {
    setMode: setMode,
    syncFxRates: syncFxRatesFromNavbar,
    openMobile: openMobileCalc,
  };
})(window, document);

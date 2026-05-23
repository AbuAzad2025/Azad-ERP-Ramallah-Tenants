(function () {
  if (window.__VENDORS_INIT__) return;
  window.__VENDORS_INIT__ = true;
  "use strict";

  function fmt(n) {
    var x = Number(n || 0);
    if (!isFinite(x)) x = 0;
    return x.toFixed(2);
  }

  function directionBadge(dir) {
    if (dir === "IN") return '<span class="badge bg-success">وارد</span>';
    if (dir === "OUT") return '<span class="badge bg-danger">صادر</span>';
    if (dir === "INCOMING") return '<span class="badge bg-success">وارد</span>'; // Legacy support
    if (dir === "OUTGOING") return '<span class="badge bg-danger">صادر</span>'; // Legacy support
    return '<span class="badge bg-secondary">—</span>';
  }

  function showMethodSection(method) {
    var ids = ["sec-cheque","sec-bank","sec-card","sec-online"];
    ids.forEach(function(id){ var el=document.getElementById(id); if(el) el.classList.add("d-none"); });
    if (!method) return;
    if (method === "cheque") document.getElementById("sec-cheque")?.classList.remove("d-none");
    else if (method === "bank") document.getElementById("sec-bank")?.classList.remove("d-none");
    else if (method === "card") document.getElementById("sec-card")?.classList.remove("d-none");
    else if (method === "online") document.getElementById("sec-online")?.classList.remove("d-none");
  }

  function normalizeArabicDigits(str) {
    if (!str) return "";
    var arabicDigits = "٠١٢٣٤٥٦٧٨٩";
    return String(str)
      .replace(/[٠-٩]/g, function(d){ 
        var idx = arabicDigits.indexOf(d);
        return idx >= 0 ? idx.toString() : d;
      })
      .replace(/[٬،\s]/g, "")
      .replace("٫", ".")
      .replace(",", ".");
  }

  function sanitizeAmountInput(raw) {
    var s = normalizeArabicDigits(raw);
    s = s.replace(/[^0-9.]/g, "");
    var firstDot = s.indexOf(".");
    if (firstDot !== -1) s = s.slice(0, firstDot + 1) + s.slice(firstDot + 1).replace(/\./g, "");
    return s;
  }

  function toNumber(val) {
    var s = sanitizeAmountInput(val);
    var n = parseFloat(s);
    return isNaN(n) ? 0 : n;
  }

var suppliersRequestSeq = 0;
var partnersRequestSeq = 0;

  function formatTwoDecimals(val) {
    var num = Number(val);
    if (!isFinite(num)) num = 0;
    return num.toFixed(2);
  }

  function updateBalanceCardClass(card, value) {
    if (!card) return;
    card.classList.remove("bg-success", "bg-danger", "bg-secondary");
    card.classList.add("text-white");
    if (value > 0) card.classList.add("bg-success");
    else if (value < 0) card.classList.add("bg-danger");
    else card.classList.add("bg-secondary");
  }

  function initSuppliersAjax() {
    var searchInput = document.getElementById("suppliers-search");
    var tableWrapper = document.getElementById("suppliers-table-wrapper");
    var searchSummary = document.getElementById("suppliers-search-summary");
    if (!searchInput || !tableWrapper || !searchSummary) return false;
    var totalCountEls = [
      document.getElementById("suppliers-total-count"),
      document.getElementById("suppliers-total-count-secondary")
    ];
    var totalBalanceEl = document.getElementById("suppliers-total-balance");
    var balanceCard = document.getElementById("suppliers-total-balance-card");
    var averageEls = [
      document.getElementById("suppliers-average-balance"),
      document.getElementById("suppliers-average-balance-secondary")
    ];
    var debtEl = document.getElementById("suppliers-with-debt");
    var creditEl = document.getElementById("suppliers-with-credit");

    function applySummary(data) {
      var totalSuppliers = Number(data.total_suppliers || 0);
      totalCountEls.forEach(function (el) { if (el) el.textContent = totalSuppliers; });
      var totalBalance = Number(data.total_balance || 0);
      if (totalBalanceEl) totalBalanceEl.textContent = formatTwoDecimals(totalBalance);
      updateBalanceCardClass(balanceCard, totalBalance);
      var avg = Number(data.average_balance || 0);
      averageEls.forEach(function (el) { if (el) el.textContent = formatTwoDecimals(avg); });
      if (debtEl) debtEl.textContent = Number(data.suppliers_with_debt || 0);
      if (creditEl) creditEl.textContent = Number(data.suppliers_with_credit || 0);
      if (searchSummary) searchSummary.textContent = "إجمالي النتائج: " + Number(data.total_filtered || 0);
    }

    function requestSuppliers(url) {
      var requestId = ++suppliersRequestSeq;
      var previous = tableWrapper.innerHTML;
      tableWrapper.innerHTML = '<div class="text-center py-4 text-muted"><div class="spinner-border spinner-border-sm me-2"></div>جارِ التحميل…</div>';
      var fetchUrl = new URL(url);
      fetchUrl.searchParams.set("ajax", "1");
      fetchWithTimeout(fetchUrl.toString(), { headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" } }, 20000)
        .then(function (res) {
          if (!res.ok) throw res;
          return res.json();
        })
        .then(function (data) {
          if (requestId !== suppliersRequestSeq) return;
          if (typeof data.table_html === "string") {
            tableWrapper.innerHTML = stripScripts(data.table_html);
          } else {
            tableWrapper.innerHTML = previous;
          }
          applySummary(data);
          if (typeof window !== "undefined" && typeof window.enableTableSorting === "function") {
            window.enableTableSorting("#suppliersTable");
          }
          attachSettleButtons();
          attachSupplierServiceButtons();
          attachPartnerServiceButtons();
          if (window.jQuery && typeof window.jQuery === "function") {
            window.jQuery('[data-toggle="tooltip"]').tooltip();
          }
        })
        .catch(function (err) {
          if (requestId !== suppliersRequestSeq) return;
          tableWrapper.innerHTML = previous;
          attachSupplierServiceButtons();
          if (err && err.name === "AbortError") {
            notify("انتهت مهلة الاتصال بالخادم.", "warning");
          }
        });
    }

    function updateFromInput() {
      var baseUrl = new URL(window.location.href);
      var term = searchInput.value.trim();
      if (term) {
        baseUrl.searchParams.set("q", term);
      } else {
        baseUrl.searchParams.delete("q");
        baseUrl.searchParams.delete("search");
      }
      baseUrl.searchParams.delete("ajax");
      var next = baseUrl.pathname + (baseUrl.searchParams.toString() ? "?" + baseUrl.searchParams.toString() : "");
      window.history.replaceState(null, "", next);
      requestSuppliers(baseUrl);
    }

    var debouncedUpdate = typeof debounce === "function" ? debounce(updateFromInput, 300) : updateFromInput;
    searchInput.addEventListener("input", function () { debouncedUpdate(); }, { passive: true });

    function syncFromLocation() {
      var current = new URL(window.location.href);
      var term = current.searchParams.get("q") || current.searchParams.get("search") || "";
      if (searchInput.value !== term) searchInput.value = term;
      requestSuppliers(current);
    }

    window.addEventListener("popstate", function () { syncFromLocation(); });
    syncFromLocation();
    return true;
  }

  function initPartnersAjax() {
    var searchInput = document.getElementById("partners-search");
    var tableWrapper = document.getElementById("partners-table-wrapper");
    var searchSummary = document.getElementById("partners-search-summary");
    if (!tableWrapper) return false;

    var totalCountEls = [
      document.getElementById("partners-total-count"),
      document.getElementById("partners-total-count-secondary")
    ];
    var totalBalanceWrapper = document.getElementById("partners-total-balance-wrapper");
    var totalBalanceValue = document.getElementById("partners-total-balance");
    var averageBalanceEl = document.getElementById("partners-average-balance");
    var debtEl = document.getElementById("partners-with-debt");
    var creditEl = document.getElementById("partners-with-credit");
    var balanceFilter = document.getElementById("balanceFilter");

    function adjustBalanceClass(value) {
      if (!totalBalanceWrapper) return;
      totalBalanceWrapper.classList.remove("text-success", "text-danger", "text-secondary");
      if (value > 0) {
        totalBalanceWrapper.classList.add("text-success");
      } else if (value < 0) {
        totalBalanceWrapper.classList.add("text-danger");
      } else {
        totalBalanceWrapper.classList.add("text-secondary");
      }
    }

    function applySummary(summary) {
      var totalPartners = Number(summary && summary.total_partners || 0);
      totalCountEls.forEach(function (el) { if (el) el.textContent = totalPartners; });
      if (totalBalanceValue) {
        var totalBalance = Number(summary && summary.total_balance || 0);
        totalBalanceValue.textContent = formatTwoDecimals(totalBalance);
        adjustBalanceClass(totalBalance);
      }
      if (averageBalanceEl) {
        averageBalanceEl.textContent = formatTwoDecimals(Number(summary && summary.average_balance || 0));
      }
      if (debtEl) debtEl.textContent = Number(summary && summary.partners_with_debt || 0);
      if (creditEl) creditEl.textContent = Number(summary && summary.partners_with_credit || 0);
      if (searchSummary) {
        searchSummary.textContent = "إجمالي النتائج: " + Number(summary && summary.total_filtered || totalPartners || 0);
      }
    }

    function applyBalanceFilter() {
      if (!balanceFilter) return;
      var mode = balanceFilter.value || "all";
      var rows = tableWrapper.querySelectorAll("tbody tr");
      rows.forEach(function (row) {
        var cell = row.querySelector("td[data-sort-value]");
        if (!cell) {
          row.style.display = "";
          return;
        }
        var balance = parseFloat(cell.getAttribute("data-sort-value") || "0");
        var show = true;
        if (mode === "positive") show = balance > 0;
        else if (mode === "negative") show = balance < 0;
        else if (mode === "zero") show = balance === 0;
        row.style.display = show ? "" : "none";
      });
    }

    function fetchPartners(target) {
      var requestId = ++partnersRequestSeq;
      var previous = tableWrapper.innerHTML;
      tableWrapper.innerHTML = '<div class="text-center py-4 text-muted"><div class="spinner-border spinner-border-sm me-2"></div>جارِ التحميل…</div>';
      var urlObj = target instanceof URL ? target : new URL(target, window.location.origin);
      urlObj.searchParams.set("ajax", "1");
      fetchWithTimeout(urlObj.toString(), { headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" } }, 20000)
        .then(function (res) {
          if (!res.ok) throw res;
          return res.json();
        })
        .then(function (data) {
          if (requestId !== partnersRequestSeq) return;
          if (typeof data.table_html === "string") {
            tableWrapper.innerHTML = stripScripts(data.table_html);
          } else {
            tableWrapper.innerHTML = previous;
          }
          applySummary({
            total_partners: data.total_partners,
            total_balance: data.total_balance,
            average_balance: data.average_balance,
            partners_with_debt: data.partners_with_debt,
            partners_with_credit: data.partners_with_credit,
            total_filtered: data.total_filtered
          });
          if (typeof window !== "undefined" && typeof window.enableTableSorting === "function") {
            window.enableTableSorting("#partnersTable");
          }
          attachSettleButtons();
          attachSupplierServiceButtons();
          attachPartnerServiceButtons();
          if (balanceFilter) applyBalanceFilter();
          urlObj.searchParams.delete("ajax");
          var nextSearch = urlObj.searchParams.toString();
          var nextUrl = urlObj.pathname + (nextSearch ? "?" + nextSearch : "");
          window.history.replaceState(null, "", nextUrl);
        })
        .catch(function (err) {
          if (requestId !== partnersRequestSeq) return;
          tableWrapper.innerHTML = previous;
          if (typeof window !== "undefined" && typeof window.enableTableSorting === "function") {
            window.enableTableSorting("#partnersTable");
          }
          attachSettleButtons();
          attachSupplierServiceButtons();
          if (err && err.name === "AbortError") {
            notify("انتهت مهلة الاتصال بالخادم.", "warning");
          }
        });
    }

    function updateFromInputs() {
      var baseUrl = new URL(window.location.href);
      var term = searchInput ? searchInput.value.trim() : "";
      if (term) {
        baseUrl.searchParams.set("q", term);
      } else {
        baseUrl.searchParams.delete("q");
        baseUrl.searchParams.delete("search");
      }
      baseUrl.searchParams.delete("ajax");
      fetchPartners(baseUrl);
    }

    if (searchInput) {
      var debouncedSearch = typeof debounce === "function" ? debounce(updateFromInputs, 300) : updateFromInputs;
      searchInput.addEventListener("input", function () {
        debouncedSearch();
      }, { passive: true });
    }

    if (balanceFilter) {
      balanceFilter.addEventListener("change", function () {
        applyBalanceFilter();
      });
    }

    function syncFromLocation() {
      var current = new URL(window.location.href);
      var term = current.searchParams.get("q") || current.searchParams.get("search") || "";
      if (searchInput && searchInput.value !== term) {
        searchInput.value = term;
      }
      fetchPartners(current);
    }

    window.addEventListener("popstate", function () {
      syncFromLocation();
    });

    syncFromLocation();
    return true;
  }

  function openSettlementModal(payload) {
    var modalEl = document.getElementById("settlementModal");
    if (!modalEl) return;

    var dom = {
      name: document.getElementById("stlName"),
      balance: document.getElementById("stlBalance"),
      amount: document.getElementById("stlAmount"),
      currency: document.getElementById("stlCurrency"),
      currencyBadge: document.getElementById("stlCurrencyBadge"),
      method: document.getElementById("stlMethod"),
      direction: document.getElementById("stlDirectionBadge"),
      entityId: document.getElementById("stlEntityId"),
      entityType: document.getElementById("stlEntityType"),
      confirm: document.getElementById("stlConfirm"),
      print: document.getElementById("stlPrint")
    };

    var balance = Number(payload.balance || 0);
    if (!isFinite(balance)) balance = 0;
    var amount = Math.abs(balance);
    var dir = balance > 0 ? "OUT" : (balance < 0 ? "IN" : "OUT");

    dom.name.textContent = payload.name || "";
    dom.balance.textContent = fmt(balance) + " " + (payload.currency || "");
    dom.amount.value = amount ? (Number.isInteger(amount) ? String(amount) : amount.toFixed(2)) : "";
    dom.amount.setAttribute("inputmode", "numeric");
    dom.amount.setAttribute("autocomplete", "off");
    dom.amount.setAttribute("dir", "ltr");
    dom.currency.value = String(payload.currency || "ILS").toUpperCase();
    if (dom.currencyBadge) dom.currencyBadge.textContent = dom.currency.value;
    dom.entityId.value = payload.id || "";
    dom.entityType.value = String(payload.entityType || "").toUpperCase();
    dom.direction.innerHTML = directionBadge(dir);
    dom.direction.dataset.dir = dir;
    dom.confirm.disabled = !(amount > 0);

    dom.amount.addEventListener("input", function () {
      var cur = dom.amount.value;
      var clean = sanitizeAmountInput(cur);
      if (clean !== cur) dom.amount.value = clean;
      dom.confirm.disabled = !(toNumber(dom.amount.value) > 0);
    });

    dom.amount.addEventListener("blur", function () {
      var n = toNumber(dom.amount.value);
      dom.amount.value = n ? (Number.isInteger(n) ? String(n) : n.toFixed(2)) : "";
    });

    if (dom.method) {
      showMethodSection(String(dom.method.value || "").toLowerCase());
      dom.method.addEventListener("change", function () {
        showMethodSection(String(dom.method.value || "").toLowerCase());
      }, { passive: true });
    }

    dom.confirm.onclick = function () {
      var cfg = document.getElementById("vendors-config");
      var base = (cfg && cfg.dataset && cfg.dataset.payUrl) ? cfg.dataset.payUrl : "/payments/create";
      var amountNum = toNumber(dom.amount.value);
      if (!(amountNum > 0)) return;

      var et = dom.entityType.value;
      var referenceBase = (et === "SUPPLIER") ? "SupplierSettle" : (et === "PARTNER" ? "PartnerSettle" : "Settlement");
      var noteText = (et === "SUPPLIER") ? "تسوية رصيد مورد" : (et === "PARTNER" ? "تسوية رصيد شريك" : "تسوية رصيد");

      var method = String(dom.method.value || "cash").toLowerCase();
      var params = new URLSearchParams({
        entity_type: et,
        entity_id: dom.entityId.value,
        direction: dom.direction.dataset.dir || dir,
        total_amount: amountNum.toString(),
        currency: dom.currency.value,
        method: method,
        reference: referenceBase,
        notes: noteText,
        status: "COMPLETED"
      });

      if (method === "cheque") {
        var cn = document.getElementById("mf_check_number")?.value || "";
        var cb = document.getElementById("mf_check_bank")?.value || "";
        var cd = document.getElementById("mf_check_due_date")?.value || "";
        if (cn) params.append("check_number", cn);
        if (cb) params.append("check_bank", cb);
        if (cd) params.append("check_due_date", cd);
      } else if (method === "bank") {
        var br = document.getElementById("mf_bank_transfer_ref")?.value || "";
        if (br) params.append("bank_transfer_ref", br);
      } else if (method === "card") {
        var ch = document.getElementById("mf_card_holder")?.value || "";
        var ce = document.getElementById("mf_card_expiry")?.value || "";
        var cc = (document.getElementById("mf_card_number")?.value || "").replace(/\D/g, "");
        if (ch) params.append("card_holder", ch);
        if (ce) params.append("card_expiry", ce);
        if (cc) params.append("card_number", cc);
      } else if (method === "online") {
        var og = document.getElementById("mf_online_gateway")?.value || "";
        var orf = document.getElementById("mf_online_ref")?.value || "";
        if (og) params.append("online_gateway", og);
        if (orf) params.append("online_ref", orf);
      }

      window.location.href = base + "?" + params.toString();
    };

    dom.print.onclick = function () {
      var w = window.open("", "printWin");
      if (!w || !w.document) return;
      var now = new Date().toLocaleString('en-US');
      var methodText = (dom.method && dom.method.options && dom.method.selectedIndex >= 0)
        ? dom.method.options[dom.method.selectedIndex].text
        : "";
      var dirText = (dom.direction.dataset.dir || dir) === "IN" ? "وارد" : "صادر";
      var d = w.document;
      d.documentElement.setAttribute("dir", "rtl");
      d.documentElement.setAttribute("lang", "ar");
      d.title = "كشف تسوية";
      d.head.textContent = "";
      d.body.textContent = "";

      var meta = d.createElement("meta");
      meta.setAttribute("charset", "utf-8");
      d.head.appendChild(meta);

      var style = d.createElement("style");
      style.textContent = "body{font-family:sans-serif;padding:20px} .row{margin:6px 0} .h{color:#666}";
      d.head.appendChild(style);

      var h3 = d.createElement("h3");
      h3.textContent = "كشف تسوية مختصر";
      d.body.appendChild(h3);

      function addRow(labelText, valueText) {
        var row = d.createElement("div");
        row.className = "row";
        var label = d.createElement("span");
        label.className = "h";
        label.textContent = String(labelText || "");
        var value = d.createElement("span");
        value.textContent = String(valueText || "");
        row.appendChild(label);
        row.appendChild(d.createTextNode(" "));
        row.appendChild(value);
        d.body.appendChild(row);
      }

      addRow("الجهة:", String(payload && payload.name || ""));
      addRow("النوع:", dom.entityType.value === "PARTNER" ? "شريك" : "مورد");
      addRow("الرصيد الحالي:", fmt(payload && payload.balance) + " " + String(payload && payload.currency || ""));
      addRow("المبلغ للتسوية:", String(dom.amount.value || "0") + " " + String(dom.currency.value || ""));
      addRow("الاتجاه:", dirText);
      addRow("الطريقة:", String(methodText || ""));

      var hr = d.createElement("hr");
      d.body.appendChild(hr);
      var small = d.createElement("small");
      small.textContent = String(now || "");
      d.body.appendChild(small);

      var printed = false;
      var doPrint = function () {
        if (printed) return;
        printed = true;
        try { w.focus(); } catch (_) {}
        try { w.print(); } catch (_) {}
        setTimeout(function () { try { w.close(); } catch (_) {} }, 300);
      };
      try {
        if (w.document && w.document.readyState === "complete") {
          setTimeout(doPrint, 50);
        } else if (typeof w.addEventListener === "function") {
          w.addEventListener("load", function () { setTimeout(doPrint, 50); }, { once: true });
          setTimeout(doPrint, 400);
        } else {
          setTimeout(doPrint, 50);
        }
      } catch (_) {
        setTimeout(doPrint, 50);
      }
    };

    $(modalEl).modal('show');
  }

  function attachSettleButtons() {
    document.querySelectorAll(".btn-settle").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openSettlementModal({
          entityType: btn.dataset.entityType,
          id: btn.dataset.id,
          name: btn.dataset.name,
          balance: Number(btn.dataset.balance || 0),
          currency: btn.dataset.currency || "ILS"
        });
      });
    });
  }

  var stripScripts = window.stripScripts || function(html) {
    return String(html || '').replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '');
  };

  var getCsrfToken = window.getCSRFToken || function() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
      || document.getElementById("csrf_token")?.value
      || document.querySelector('input[name="csrf_token"]')?.value
      || "";
  };

  var fetchWithTimeout = window.fetchWithTimeout || function(url, options, timeoutMs) {
    var ms = Number(timeoutMs || 20000);
    if (!(ms > 0)) ms = 20000;
    if (typeof AbortController === "undefined") return fetch(url, options);
    var controller = new AbortController();
    var timer = setTimeout(function () { try { controller.abort(); } catch (_) {} }, ms);
    var opts = options ? Object.assign({}, options) : {};
    opts.signal = controller.signal;
    return fetch(url, opts).finally(function () { clearTimeout(timer); });
  };

  function notify(msg, level) {
    if (typeof window.showNotification === "function") {
      window.showNotification(msg, level || "info");
    } else {
      alert(msg);
    }
  }

  var quickServiceEl = document.getElementById("supplier-service-config");
  var quickServiceCfg = null;
  if (quickServiceEl) {
    try {
      quickServiceCfg = {
        branchId: quickServiceEl.getAttribute("data-branch-id"),
        createUrl: quickServiceEl.getAttribute("data-create-url"),
        payUrl: quickServiceEl.getAttribute("data-pay-url"),
        currencies: JSON.parse(quickServiceEl.getAttribute("data-currencies") || "[]"),
        defaultCurrency: quickServiceEl.getAttribute("data-default-currency") || "ILS",
        today: quickServiceEl.getAttribute("data-today") || ""
      };
    } catch (err) {
      quickServiceCfg = null;
    }
  }

  var serviceModalEl = document.getElementById("supplierServiceModal");
  var serviceForm = document.getElementById("supplierServiceForm");
  var serviceSupplierNameEl = document.getElementById("serviceSupplierName");
  var serviceSupplierIdInput = document.getElementById("serviceSupplierId");
  var serviceAmountInput = document.getElementById("serviceAmount");
  var serviceCurrencyInput = document.getElementById("serviceCurrency");
  var serviceDescriptionInput = document.getElementById("serviceDescription");
  var serviceDateEl = document.getElementById("serviceInvoiceDate");
  var serviceErrorEl = document.getElementById("serviceFormError");
  var serviceSubmitBtn = document.getElementById("serviceSubmitBtn");
  var serviceSubmitSpinner = document.getElementById("serviceSubmitSpinner");

  var payModalEl = document.getElementById("supplierServicePayModal");
  var payForm = document.getElementById("supplierServicePayForm");
  var payExpenseIdInput = document.getElementById("payExpenseId");
  var paySupplierNameEl = document.getElementById("paySupplierName");
  var payExpenseCodeEl = document.getElementById("payExpenseCode");
  var payAmountInput = document.getElementById("payAmount");
  var payCurrencyInput = document.getElementById("payCurrency");
  var payMethodInput = document.getElementById("payMethod");
  var payReferenceInput = document.getElementById("payReference");
  var payNotesInput = document.getElementById("payNotes");
  var payErrorEl = document.getElementById("payFormError");
  var paySubmitBtn = document.getElementById("paySubmitBtn");
  var paySubmitSpinner = document.getElementById("paySubmitSpinner");
  var lastCreatedExpense = null;

  var partnerCfgEl = document.getElementById("partner-service-config");
  var partnerCfg = null;
  if (partnerCfgEl) {
    try {
      partnerCfg = {
        branchId: partnerCfgEl.getAttribute("data-branch-id"),
        createUrl: partnerCfgEl.getAttribute("data-create-url"),
        payUrl: partnerCfgEl.getAttribute("data-pay-url"),
        defaultCurrency: partnerCfgEl.getAttribute("data-default-currency") || "ILS",
        today: partnerCfgEl.getAttribute("data-today") || ""
      };
    } catch (e) {
      partnerCfg = null;
    }
  }

  var partnerServiceModalEl = document.getElementById("partnerServiceModal");
  var partnerServiceForm = document.getElementById("partnerServiceForm");
  var partnerServicePartnerIdInput = document.getElementById("partnerServicePartnerId");
  var partnerServicePartnerNameEl = document.getElementById("partnerServicePartnerName");
  var partnerServiceAmountInput = document.getElementById("partnerServiceAmount");
  var partnerServiceCurrencyInput = document.getElementById("partnerServiceCurrency");
  var partnerServiceDescriptionInput = document.getElementById("partnerServiceDescription");
  var partnerServiceDateEl = document.getElementById("partnerServiceInvoiceDate");
  var partnerServiceErrorEl = document.getElementById("partnerServiceFormError");
  var partnerServiceSubmitBtn = document.getElementById("partnerServiceSubmitBtn");
  var partnerServiceSubmitSpinner = document.getElementById("partnerServiceSubmitSpinner");

  var partnerPayModalEl = document.getElementById("partnerServicePayModal");
  var partnerPayForm = document.getElementById("partnerServicePayForm");
  var partnerPayExpenseIdInput = document.getElementById("partnerPayExpenseId");
  var partnerPayPartnerNameEl = document.getElementById("partnerPayPartnerName");
  var partnerPayExpenseCodeEl = document.getElementById("partnerPayExpenseCode");
  var partnerPayAmountInput = document.getElementById("partnerPayAmount");
  var partnerPayCurrencyInput = document.getElementById("partnerPayCurrency");
  var partnerPayMethodInput = document.getElementById("partnerPayMethod");
  var partnerPayReferenceInput = document.getElementById("partnerPayReference");
  var partnerPayNotesInput = document.getElementById("partnerPayNotes");
  var partnerPayErrorEl = document.getElementById("partnerPayFormError");
  var partnerPaySubmitBtn = document.getElementById("partnerPaySubmitBtn");
  var partnerPaySubmitSpinner = document.getElementById("partnerPaySubmitSpinner");

  function attachPartnerServiceButtons() {
    if (!partnerCfg) return;
    document.querySelectorAll(".js-partner-service").forEach(function (btn) {
      if (btn.dataset.partnerServiceBound === "1") return;
      btn.dataset.partnerServiceBound = "1";
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (!partnerCfg.branchId) {
          notify("يرجى تهيئة فرع افتراضي قبل إنشاء فاتورة خدمة للشريك.", "warning");
          return;
        }
        openPartnerServiceModal(btn.dataset.partnerId, btn.dataset.partnerName);
      });
    });
  }

  function openPartnerServiceModal(partnerId, partnerName) {
    if (!partnerServiceModalEl || !partnerServiceForm) return;
    partnerServiceForm.reset();
    if (partnerServiceCurrencyInput && partnerCfg && partnerCfg.defaultCurrency) {
      partnerServiceCurrencyInput.value = partnerCfg.defaultCurrency;
    }
    partnerServicePartnerIdInput.value = partnerId || "";
    partnerServicePartnerNameEl.textContent = partnerName || "";
    if (partnerServiceDateEl && partnerCfg) partnerServiceDateEl.textContent = partnerCfg.today || "";
    if (partnerServiceErrorEl) {
      partnerServiceErrorEl.classList.add("d-none");
      partnerServiceErrorEl.textContent = "";
    }
    partnerServiceSubmitSpinner.classList.add("d-none");
    partnerServiceSubmitBtn.disabled = false;
    if (window.jQuery) window.jQuery(partnerServiceModalEl).modal("show");
  }

  function handlePartnerServiceSubmit(ev) {
    ev.preventDefault();
    if (!partnerCfg || !partnerCfg.createUrl) return;
    var amount = parseFloat(partnerServiceAmountInput.value || "0");
    if (!(amount > 0)) {
      showPartnerServiceError("يرجى إدخال مبلغ صالح.");
      return;
    }
    var payload = {
      partner_id: partnerServicePartnerIdInput.value,
      amount: amount,
      currency: partnerServiceCurrencyInput.value || partnerCfg.defaultCurrency || "ILS",
      description: partnerServiceDescriptionInput.value || "",
      branch_id: partnerCfg.branchId,
      date: partnerCfg.today
    };
    togglePartnerServiceSubmit(true);
    fetchWithTimeout(partnerCfg.createUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify(payload)
    }, 20000)
      .then(function (res) {
        if (!res.ok) throw res;
        return res.json();
      })
      .then(function (data) {
        togglePartnerServiceSubmit(false);
        if (!data || !data.success) {
          showPartnerServiceError((data && data.message) || "تعذر إنشاء الفاتورة.");
          return;
        }
        if (window.jQuery) window.jQuery(partnerServiceModalEl).modal("hide");
        if (data.auto_paid) {
          notify("تم إنشاء فاتورة خدمة الشريك وتم تسجيل الدفع تلقائياً.", "success");
          setTimeout(function () {
            window.location.reload();
          }, 600);
          return;
        }
        notify("تم إنشاء فاتورة خدمة الشريك بنجاح.", "success");
        openPartnerPayModal(data);
      })
      .catch(function (err) {
        togglePartnerServiceSubmit(false);
        if (err && err.name === "AbortError") {
          showPartnerServiceError("انتهت مهلة الاتصال بالخادم.");
          return;
        }
        if (err && typeof err.json === "function") {
          err.json().then(function (payload) {
            showPartnerServiceError((payload && payload.message) || "تعذر إنشاء الفاتورة.");
          }).catch(function () {
            showPartnerServiceError("تعذر إنشاء الفاتورة.");
          });
        } else {
          showPartnerServiceError("تعذر إنشاء الفاتورة.");
        }
      });
  }

  function showPartnerServiceError(msg) {
    if (!partnerServiceErrorEl) return;
    partnerServiceErrorEl.textContent = msg || "خطأ غير متوقع.";
    partnerServiceErrorEl.classList.remove("d-none");
  }

  function togglePartnerServiceSubmit(state) {
    partnerServiceSubmitBtn.disabled = !!state;
    partnerServiceSubmitSpinner.classList.toggle("d-none", !state);
  }

  function openPartnerPayModal(payload) {
    if (!partnerPayModalEl || !payload) return;
    partnerPayExpenseIdInput.value = payload.expense_id || "";
    partnerPayPartnerNameEl.textContent = payload.partner_name || "";
    partnerPayExpenseCodeEl.textContent = payload.expense_id ? "#" + payload.expense_id : "—";
    var amt = payload.amount || 0;
    partnerPayAmountInput.value = Number(amt).toFixed(2);
    partnerPayCurrencyInput.value = payload.currency || "ILS";
    partnerPayMethodInput.value = "cash";
    partnerPayReferenceInput.value = "";
    partnerPayNotesInput.value = "";
    if (partnerPayErrorEl) {
      partnerPayErrorEl.classList.add("d-none");
      partnerPayErrorEl.textContent = "";
    }
    partnerPaySubmitSpinner.classList.add("d-none");
    partnerPaySubmitBtn.disabled = false;
    if (window.jQuery) window.jQuery(partnerPayModalEl).modal("show");
  }

  function handlePartnerPaySubmit(ev) {
    ev.preventDefault();
    if (!partnerCfg || !partnerCfg.payUrl) return;
    var payload = {
      expense_id: partnerPayExpenseIdInput.value,
      amount: partnerPayAmountInput.value,
      currency: partnerPayCurrencyInput.value,
      method: partnerPayMethodInput.value,
      reference: partnerPayReferenceInput.value,
      notes: partnerPayNotesInput.value
    };
    var amt = parseFloat(payload.amount || "0");
    if (!(amt > 0)) {
      showPartnerPayError("أدخل مبلغ الدفعة.");
      return;
    }
    togglePartnerPaySubmit(true);
    fetchWithTimeout(partnerCfg.payUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify(payload)
    }, 20000)
      .then(function (res) {
        if (!res.ok) throw res;
        return res.json();
      })
      .then(function (data) {
        togglePartnerPaySubmit(false);
        if (!data || !data.success) {
          showPartnerPayError((data && data.message) || "تعذر حفظ الدفعة.");
          return;
        }
        if (window.jQuery) window.jQuery(partnerPayModalEl).modal("hide");
        notify("تم حفظ دفعة الشريك بنجاح.", "success");
        window.setTimeout(function () {
          window.location.reload();
        }, 600);
      })
      .catch(function (err) {
        togglePartnerPaySubmit(false);
        if (err && err.name === "AbortError") {
          showPartnerPayError("انتهت مهلة الاتصال بالخادم.");
          return;
        }
        if (err && typeof err.json === "function") {
          err.json().then(function (payload) {
            showPartnerPayError((payload && payload.message) || "تعذر حفظ الدفعة.");
          }).catch(function () {
            showPartnerPayError("تعذر حفظ الدفعة.");
          });
        } else {
          showPartnerPayError("تعذر حفظ الدفعة.");
        }
      });
  }

  function togglePartnerPaySubmit(state) {
    partnerPaySubmitBtn.disabled = !!state;
    partnerPaySubmitSpinner.classList.toggle("d-none", !state);
  }

  function showPartnerPayError(msg) {
    if (!partnerPayErrorEl) return;
    partnerPayErrorEl.textContent = msg || "خطأ غير متوقع.";
    partnerPayErrorEl.classList.remove("d-none");
  }

  function attachSupplierServiceButtons() {
    if (!quickServiceCfg) return;
    document.querySelectorAll(".js-supplier-service").forEach(function (btn) {
      if (btn.dataset.serviceBound === "1") return;
      btn.dataset.serviceBound = "1";
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        if (!quickServiceCfg.branchId) {
          notify("يرجى تهيئة فرع افتراضي قبل إنشاء فاتورة خدمة.", "warning");
          return;
        }
        openServiceModal(btn.dataset.supplierId, btn.dataset.supplierName);
      });
    });
  }

  function openServiceModal(supplierId, supplierName) {
    if (!serviceModalEl || !serviceForm) return;
    serviceForm.reset();
    if (serviceCurrencyInput && quickServiceCfg && quickServiceCfg.defaultCurrency) {
      serviceCurrencyInput.value = quickServiceCfg.defaultCurrency;
    }
    serviceSupplierIdInput.value = supplierId || "";
    serviceSupplierNameEl.textContent = supplierName || "";
    if (serviceDateEl && quickServiceCfg) serviceDateEl.textContent = quickServiceCfg.today || "";
    if (serviceErrorEl) {
      serviceErrorEl.classList.add("d-none");
      serviceErrorEl.textContent = "";
    }
    if (serviceSubmitSpinner) serviceSubmitSpinner.classList.add("d-none");
    if (serviceSubmitBtn) serviceSubmitBtn.disabled = false;
    if (window.jQuery && serviceModalEl) window.jQuery(serviceModalEl).modal("show");
  }

  function handleServiceSubmit(ev) {
    ev.preventDefault();
    if (!quickServiceCfg || !quickServiceCfg.createUrl) return;
    var amount = parseFloat(serviceAmountInput.value || "0");
    if (!(amount > 0)) {
      showServiceError("يرجى إدخال مبلغ صالح.");
      return;
    }
    var payload = {
      supplier_id: serviceSupplierIdInput.value,
      amount: amount,
      currency: serviceCurrencyInput.value || quickServiceCfg.defaultCurrency || "ILS",
      description: serviceDescriptionInput.value || "",
      branch_id: quickServiceCfg.branchId,
      date: quickServiceCfg.today
    };
    toggleServiceSubmit(true);
    fetchWithTimeout(quickServiceCfg.createUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify(payload)
    }, 20000)
      .then(function (res) {
        if (!res.ok) throw res;
        return res.json();
      })
      .then(function (data) {
        toggleServiceSubmit(false);
        if (!data || !data.success) {
          showServiceError((data && data.message) || "تعذر إنشاء الفاتورة.");
          return;
        }
        lastCreatedExpense = data;
        if (serviceModalEl && window.jQuery) window.jQuery(serviceModalEl).modal("hide");
        if (data.auto_paid) {
          notify("تم إنشاء فاتورة الخدمة وتم تسجيل الدفع تلقائياً.", "success");
          setTimeout(function () {
            window.location.reload();
          }, 600);
          return;
        }
        notify("تم إنشاء فاتورة الخدمة بنجاح.", "success");
        openPayModal(data);
      })
      .catch(function (err) {
        toggleServiceSubmit(false);
        if (err && err.name === "AbortError") {
          showServiceError("انتهت مهلة الاتصال بالخادم.");
          return;
        }
        if (err && typeof err.json === "function") {
          err.json().then(function (payload) {
            showServiceError((payload && payload.message) || "تعذر إنشاء الفاتورة.");
          }).catch(function () {
            showServiceError("تعذر إنشاء الفاتورة.");
          });
        } else {
          showServiceError("تعذر إنشاء الفاتورة.");
        }
      });
  }

  function showServiceError(msg) {
    if (!serviceErrorEl) return;
    serviceErrorEl.textContent = msg || "خطأ غير متوقع.";
    serviceErrorEl.classList.remove("d-none");
  }

  function toggleServiceSubmit(state) {
    if (!serviceSubmitBtn || !serviceSubmitSpinner) return;
    serviceSubmitBtn.disabled = !!state;
    serviceSubmitSpinner.classList.toggle("d-none", !state);
  }

  function openPayModal(payload) {
    if (!payModalEl || !payload) return;
    payExpenseIdInput.value = payload.expense_id || "";
    paySupplierNameEl.textContent = payload.supplier_name || "";
    payExpenseCodeEl.textContent = payload.expense_id ? "#" + payload.expense_id : "—";
    var amt = payload.amount || 0;
    payAmountInput.value = Number(amt).toFixed(2);
    payCurrencyInput.value = payload.currency || "ILS";
    payMethodInput.value = "cash";
    payReferenceInput.value = "";
    payNotesInput.value = "";
    if (payErrorEl) {
      payErrorEl.classList.add("d-none");
      payErrorEl.textContent = "";
    }
    paySubmitSpinner.classList.add("d-none");
    paySubmitBtn.disabled = false;
    if (window.jQuery) window.jQuery(payModalEl).modal("show");
  }

  function handlePaySubmit(ev) {
    ev.preventDefault();
    if (!quickServiceCfg || !quickServiceCfg.payUrl) return;
    var payload = {
      expense_id: payExpenseIdInput.value,
      amount: payAmountInput.value,
      currency: payCurrencyInput.value,
      method: payMethodInput.value,
      reference: payReferenceInput.value,
      notes: payNotesInput.value
    };
    var amt = parseFloat(payload.amount || "0");
    if (!(amt > 0)) {
      showPayError("أدخل مبلغ الدفعة.");
      return;
    }
    if (typeof window.gmRequirePerm === 'function' && !window.gmRequirePerm('manage_vendors')) {
      showPayError('ليس لديك صلاحية لتسجيل الدفعة.');
      return;
    }
    togglePaySubmit(true);
    fetch(quickServiceCfg.payUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify(payload)
    })
      .then(function (res) {
        if (!res.ok) throw res;
        return res.json();
      })
      .then(function (data) {
        togglePaySubmit(false);
        if (!data || !data.success) {
          showPayError((data && data.message) || "تعذر حفظ الدفعة.");
          return;
        }
        if (payModalEl && window.jQuery) window.jQuery(payModalEl).modal("hide");
        notify("تم حفظ الدفعة بنجاح.", "success");
        window.setTimeout(function () {
          window.location.reload();
        }, 600);
      })
      .catch(function (err) {
        togglePaySubmit(false);
        if (err && err.name === "AbortError") {
          showPayError("انتهت مهلة الاتصال بالخادم.");
          return;
        }
        if (err && typeof err.json === "function") {
          err.json().then(function (payload) {
            showPayError((payload && payload.message) || "تعذر حفظ الدفعة.");
          }).catch(function () {
            showPayError("تعذر حفظ الدفعة.");
          });
        } else {
          showPayError("تعذر حفظ الدفعة.");
        }
      });
  }

  function togglePaySubmit(state) {
    paySubmitBtn.disabled = !!state;
    paySubmitSpinner.classList.toggle("d-none", !state);
  }

  function showPayError(msg) {
    if (!payErrorEl) return;
    payErrorEl.textContent = msg || "خطأ غير متوقع.";
    payErrorEl.classList.remove("d-none");
  }

  function wireSimpleSearch(inputId, tableId, selectors) {
    var input = document.getElementById(inputId);
    var table = document.getElementById(tableId);
    if (!input || !table || !table.tBodies.length) return;
    input.addEventListener("input", function () {
      var q = input.value.trim().toLowerCase();
      Array.from(table.tBodies[0].rows).forEach(function (row) {
        var haystack = selectors.map(function (sel) {
          var el = row.querySelector(sel);
          return (el && el.textContent || "").toLowerCase();
        }).join(" ");
        row.style.display = haystack.includes(q) ? "" : "none";
      });
    });
  }

  function bindPrint() {
    var b = document.getElementById("btn-print");
    if (!b) return;
    b.addEventListener("click", function () { window.print(); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var suppliersInitialized = initSuppliersAjax();
    var partnersInitialized = initPartnersAjax();
    if (typeof window !== "undefined" && typeof window.enableTableSorting === "function") {
      if (!suppliersInitialized) {
        window.enableTableSorting("#suppliersTable");
      }
      if (!partnersInitialized) {
        window.enableTableSorting("#partnersTable");
      }
    }
    attachSettleButtons();
    attachSupplierServiceButtons();
    attachPartnerServiceButtons();
    bindPrint();
    if (serviceForm) {
      serviceForm.addEventListener("submit", handleServiceSubmit);
    }
    if (payForm) {
      payForm.addEventListener("submit", handlePaySubmit);
    }
    if (partnerServiceForm) {
      partnerServiceForm.addEventListener("submit", handlePartnerServiceSubmit);
    }
    if (partnerPayForm) {
      partnerPayForm.addEventListener("submit", handlePartnerPaySubmit);
    }
    if (window.jQuery && typeof window.jQuery === "function") {
      window.jQuery('[data-toggle="tooltip"]').tooltip();
    }
  });
})();

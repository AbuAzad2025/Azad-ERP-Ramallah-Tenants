document.addEventListener('DOMContentLoaded', function () {
  if (window.__PAYMENT_FORM_INIT__) return;
  window.__PAYMENT_FORM_INIT__ = true;
  'use strict';

  const filterSelectors = ['#filterEntity', '#filterStatus', '#filterDirection', '#filterMethod', '#startDate', '#endDate', '#filterCurrency'];
  const ENTITY_ENUM = { customer:'CUSTOMER', supplier:'SUPPLIER', partner:'PARTNER', sale:'SALE', service:'SERVICE', expense:'EXPENSE', loan:'LOAN', preorder:'PREORDER', shipment:'SHIPMENT' };
  const AR_STATUS = { COMPLETED:'مكتملة', PENDING:'قيد الانتظار', FAILED:'فاشلة', REFUNDED:'مُرجعة', CANCELLED:'ملغية' };

  function inferEntityContext() {
    const path = location.pathname.replace(/\/+$/, '');
    const m = path.match(/^\/vendors\/(suppliers|partners)\/(\d+)\/payments$/i);
    if (m) return { entity_type: m[1].toLowerCase()==='suppliers' ? 'SUPPLIER' : 'PARTNER', entity_id: m[2] };
    const qs = new URLSearchParams(location.search);
    const et = (qs.get('entity_type') || '').toLowerCase();
    const ei = qs.get('entity_id') || '';
    return { entity_type: ENTITY_ENUM[et] || '', entity_id: ei || '' };
  }

  const ctx = inferEntityContext();
  const entSel = document.querySelector('#filterEntity');
  if (entSel && ctx.entity_type) { entSel.value = ctx.entity_type; entSel.disabled = true; }

  function injectStatementButtons() {
    if (!ctx.entity_type || !ctx.entity_id) return;
    const filtersRow = document.querySelector('.row.mb-4.g-2.align-items-end') || document.querySelector('.row.mb-4');
    if (!filtersRow || document.getElementById('btnExportCsv')) return;
    const wrap = document.createElement('div');
    wrap.className = 'col-auto d-flex gap-2';
    const btnPrint = document.createElement('button');
    btnPrint.id = 'btnPrint';
    btnPrint.className = 'btn btn-outline-secondary';
    const printIcon = document.createElement('i');
    printIcon.className = 'fas fa-print me-1';
    btnPrint.appendChild(printIcon);
    btnPrint.appendChild(document.createTextNode(' طباعة كشف'));

    const btnExportCsv = document.createElement('button');
    btnExportCsv.id = 'btnExportCsv';
    btnExportCsv.className = 'btn btn-outline-success';
    const csvIcon = document.createElement('i');
    csvIcon.className = 'fas fa-file-csv me-1';
    btnExportCsv.appendChild(csvIcon);
    btnExportCsv.appendChild(document.createTextNode(' تصدير CSV'));

    wrap.appendChild(btnPrint);
    wrap.appendChild(btnExportCsv);
    filtersRow.appendChild(wrap);
    document.getElementById('btnPrint').addEventListener('click', printStatement);
    document.getElementById('btnExportCsv').addEventListener('click', exportCsv);
  }
  injectStatementButtons();

  var debounce = window.debounce || function(fn, ms) { var t; return function () { clearTimeout(t); t = setTimeout(function() { fn.apply(this, arguments); }, ms); }; };
  const debouncedReload = debounce(function () { updateUrlQuery(); loadPayments(1); }, 250);

  filterSelectors.forEach(function (sel) {
    const el = document.querySelector(sel);
    if (!el) return;
    el.addEventListener('change', debouncedReload, { passive: true });
    if (el.tagName === 'INPUT') el.addEventListener('input', debouncedReload, { passive: true });
  });

  var normalizeEntity = window.normalizeEntity || function(val) { if (!val) return ''; var k = String(val).toLowerCase(); return ENTITY_ENUM[k] || String(val).toUpperCase(); };
  var normalizeMethod = window.normalizeMethod || function(v) { v = String(v || '').trim(); return v ? v.replace(/\s+/g,'_').replace(/-/g,'_').toUpperCase() : ''; };
  var normDir = window.normDir || function(v) { v = (v || '').toUpperCase(); if (v === 'IN') return 'INCOMING'; if (v === 'OUT') return 'OUTGOING'; return v; };
  var validDates = window.validDates || function(start, end) { if (!start || !end) return { start: start, end: end }; var s = new Date(start), e = new Date(end); if (isNaN(s) || isNaN(e)) return { start: start, end: end }; if (s.getTime() > e.getTime()) return { start: end, end: start }; return { start: start, end: end }; };

  function currentFilters(page = 1) {
    const raw = {
      entity_type: normalizeEntity(document.querySelector('#filterEntity')?.value || ctx.entity_type || ''),
      status: document.querySelector('#filterStatus')?.value || '',
      direction: normDir(document.querySelector('#filterDirection')?.value || ''),
      method: normalizeMethod(document.querySelector('#filterMethod')?.value || ''),
      start_date: document.querySelector('#startDate')?.value || '',
      end_date: document.querySelector('#endDate')?.value || '',
      currency: (document.querySelector('#filterCurrency')?.value || '').toUpperCase(),
      page
    };
    const v = validDates(raw.start_date, raw.end_date);
    raw.start_date = v.start; raw.end_date = v.end;
    if (ctx.entity_id) raw.entity_id = ctx.entity_id;
    return raw;
  }

  function syncFiltersFromUrl() {
    const qs = new URLSearchParams(location.search);
    const setVal = (sel, v) => { const el = document.querySelector(sel); if (el && v != null) el.value = v; };
    setVal('#filterEntity', qs.get('entity_type'));
    setVal('#filterStatus', qs.get('status'));
    setVal('#filterDirection', qs.get('direction'));
    setVal('#filterMethod', qs.get('method'));
    setVal('#startDate', qs.get('start_date'));
    setVal('#endDate', qs.get('end_date'));
    setVal('#filterCurrency', qs.get('currency'));
  }

  function updateUrlQuery() {
    const raw = currentFilters();
    const params = new URLSearchParams();
    Object.entries(raw).forEach(function ([k, v]) { if (v && k !== 'page') params.append(k, v); });
    history.replaceState(null, '', location.pathname + (params.toString() ? ('?' + params.toString()) : ''));
  }

  let _abortCtrl = null;
  let _lastList = [];

  function loadPayments(page = 1) {
    const raw = currentFilters(page);
    const params = new URLSearchParams();
    Object.entries(raw).forEach(function ([k, v]) { if (v) params.append(k, v); });
    if (_abortCtrl) _abortCtrl.abort();
    _abortCtrl = new AbortController();
    setLoading(true);
    fetch('/payments/?' + params.toString(), { headers: { 'Accept': 'application/json' }, signal: _abortCtrl.signal })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        const list = Array.isArray(data.payments) ? data.payments : [];
        renderPaymentsTable(list);
        renderPagination(Number(data.total_pages || 1), Number(data.current_page || 1));
        renderTotals(data.totals || null);
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        renderPaymentsTable([]);
        renderPagination(1, 1);
        renderTotals(null);
      })
      .finally(function () { setLoading(false); });
  }

  function setLoading(is) {
    const tbody = document.querySelector('#paymentsTable tbody');
    if (!tbody) return;
    if (!is) return;
    tbody.textContent = '';
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 9;
    td.className = 'text-center text-muted py-4';
    const spinner = document.createElement('div');
    spinner.className = 'spinner-border spinner-border-sm me-2';
    td.appendChild(spinner);
    td.appendChild(document.createTextNode('جارِ التحميل…'));
    tr.appendChild(td);
    tbody.appendChild(tr);
  }

  function badgeForDirection(dir) {
    const v = String(dir || '').toUpperCase();
    const span = document.createElement('span');
    const isIncoming = (v === 'IN' || v === 'INCOMING');
    span.className = 'badge ' + (isIncoming ? 'bg-success' : 'bg-danger');
    span.textContent = isIncoming ? 'وارد' : 'صادر';
    return span;
  }

  function badgeForStatus(st) {
    const s = String(st || '');
    const cls = s === 'COMPLETED' ? 'bg-success' : s === 'PENDING' ? 'bg-warning text-dark' : s === 'FAILED' ? 'bg-danger' : 'bg-secondary';
    const txt = AR_STATUS[s] || s || '';
    const span = document.createElement('span');
    span.className = 'badge ' + cls;
    span.textContent = txt;
    return span;
  }

  var toNumber = window.toNumber || function(s) {
    s = String(s || '').replace(/[٠-٩]/g, function(d) { return '٠١٢٣٤٥٦٧٨٩'.indexOf(d); }).replace(/[٬،\s]/g, '').replace(',', '.');
    var n = parseFloat(s);
    return isNaN(n) ? 0 : n;
  };

  function fmtAmount(v) { return toNumber(v).toFixed(2); }

  var deriveEntityLabel = window.deriveEntityLabel || function(p) {
    if (p && p.entity_display) return p.entity_display;
    var map = [['customer_id','زبون'],['supplier_id','مورد'],['partner_id','شريك'],['sale_id','بيع'],['invoice_id','فاتورة'],['service_id','صيانة'],['shipment_id','شحنة'],['expense_id','مصروف'],['preorder_id','حجز'],['loan_settlement_id','تسوية']];
    if (p) for (var i = 0; i < map.length; i++) if (p[map[i][0]]) return map[i][1] + ' #' + p[map[i][0]];
    return (p && p.entity_type) || '';
  };

  function renderPaymentsTable(list) {
    _lastList = list.slice();
    const tbody = document.querySelector('#paymentsTable tbody');
    if (!tbody) return;
    tbody.textContent = '';
    if (!list.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 9;
      td.className = 'text-center text-muted py-4';
      td.textContent = 'لا توجد بيانات';
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    
    const currencies = {};
    list.forEach(function (p) {
      const curr = (p.currency || 'ILS').toUpperCase();
      if (!currencies[curr]) currencies[curr] = 0;
      currencies[curr] += toNumber(p.total_amount);
      
      const dateOnly = (p.payment_date || '').split('T')[0] || '';
      const tr = document.createElement('tr');

      const tdId = document.createElement('td');
      tdId.textContent = String(p.id ?? '');
      tr.appendChild(tdId);

      const tdDate = document.createElement('td');
      tdDate.textContent = dateOnly;
      tr.appendChild(tdDate);

      const tdAmt = document.createElement('td');
      tdAmt.textContent = fmtAmount(p.total_amount);
      tr.appendChild(tdAmt);

      const tdCurr = document.createElement('td');
      tdCurr.textContent = String(p.currency || '');
      tr.appendChild(tdCurr);

      const tdMethod = document.createElement('td');
      const splits = Array.isArray(p.splits) ? p.splits : [];
      if (splits.length) {
        splits.forEach(function (s) {
          const baseCurrency = (s.currency || p.currency || '').toUpperCase();
          const convertedCurrency = (s.converted_currency || p.currency || '').toUpperCase();
          let text = String((s.method || '')).toUpperCase() + ': ' + fmtAmount(s.amount) + ' ' + baseCurrency;
          if (baseCurrency && convertedCurrency && baseCurrency !== convertedCurrency && s.converted_amount != null) {
            text += ' (≈ ' + fmtAmount(s.converted_amount) + ' ' + convertedCurrency + ')';
          }
          const span = document.createElement('span');
          span.className = 'badge bg-secondary me-1';
          span.textContent = text;
          tdMethod.appendChild(span);
        });
      } else {
        tdMethod.textContent = String(p.method || '');
      }
      tr.appendChild(tdMethod);

      const tdDir = document.createElement('td');
      tdDir.appendChild(badgeForDirection(p.direction));
      tr.appendChild(tdDir);

      const tdSt = document.createElement('td');
      tdSt.appendChild(badgeForStatus(p.status));
      tr.appendChild(tdSt);

      const tdEnt = document.createElement('td');
      tdEnt.textContent = String(deriveEntityLabel(p) || '');
      tr.appendChild(tdEnt);

      const tdAction = document.createElement('td');
      const a = document.createElement('a');
      a.className = 'btn btn-info btn-sm';
      a.href = (window.gmPath || function(p){ return p; })('/payments/' + encodeURIComponent(String(p.id ?? '')));
      a.textContent = 'عرض';
      tdAction.appendChild(a);
      tr.appendChild(tdAction);

      tbody.appendChild(tr);
    });
    
    const currKeys = Object.keys(currencies);
    if (currKeys.length === 1) {
      const curr = currKeys[0];
      const t = document.createElement('tr');
      const td1 = document.createElement('td');
      const td2 = document.createElement('td');
      td2.className = 'text-end fw-bold';
      td2.textContent = 'إجمالي الصفحة';
      const td3 = document.createElement('td');
      td3.className = 'fw-bold';
      td3.textContent = fmtAmount(currencies[curr]);
      const td4 = document.createElement('td');
      td4.textContent = curr;
      const td5 = document.createElement('td');
      td5.colSpan = 5;
      t.appendChild(td1);
      t.appendChild(td2);
      t.appendChild(td3);
      t.appendChild(td4);
      t.appendChild(td5);
      tbody.appendChild(t);
    } else if (currKeys.length > 1) {
      const t = document.createElement('tr');
      const totalsText = currKeys.map(c => fmtAmount(currencies[c]) + ' ' + c).join(' + ');
      const td1 = document.createElement('td');
      const td2 = document.createElement('td');
      td2.className = 'text-end fw-bold';
      td2.textContent = 'إجمالي الصفحة';
      const td3 = document.createElement('td');
      td3.colSpan = 7;
      td3.className = 'fw-bold text-warning';
      td3.textContent = 'عملات متعددة: ' + totalsText;
      t.appendChild(td1);
      t.appendChild(td2);
      t.appendChild(td3);
      tbody.appendChild(t);
    }
  }

  function renderPagination(totalPages, currentPage) {
    const ul = document.querySelector('#pagination');
    if (!ul) return;
    ul.textContent = '';
    totalPages = Math.max(1, totalPages || 1);
    currentPage = Math.min(Math.max(1, currentPage || 1), totalPages);

    function add(page, label, disabled, active, isEllipsis=false) {
      const li = document.createElement('li');
      li.className = 'page-item ' + (disabled ? 'disabled' : '') + ' ' + (active ? 'active' : '');
      const a = document.createElement('a');
      a.className = 'page-link';
      a.href = '#';
      a.textContent = label;
      if (isEllipsis) {
        a.tabIndex = -1;
        a.setAttribute('aria-disabled', 'true');
      } else {
        a.dataset.page = String(page);
      }
      li.appendChild(a);
      ul.appendChild(li);
    }

    add(currentPage - 1, 'السابق', currentPage <= 1, false);
    const windowSize = 2;
    const first = 1, last = totalPages;
    let start = Math.max(first, currentPage - windowSize);
    let end = Math.min(last, currentPage + windowSize);
    if (start > first) { add(first, '1', false, first === currentPage); if (start > first + 1) add(currentPage, '…', true, false, true); }
    for (let i = start; i <= end; i++) add(i, String(i), false, i === currentPage);
    if (end < last) { if (end < last - 1) add(currentPage, '…', true, false, true); add(last, String(last), false, last === currentPage); }
    add(currentPage + 1, 'التالي', currentPage >= totalPages, false);
    ul.querySelectorAll('.page-link[data-page]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        const page = parseInt(a.dataset.page, 10);
        if (!isNaN(page)) loadPayments(page);
      }, { passive: false });
    });
  }

  function renderTotals(totals) {
    const elIn = document.getElementById('totalIncoming');
    const elOut = document.getElementById('totalOutgoing');
    const elNet = document.getElementById('netTotal');
    const elAll = document.getElementById('grandTotal');
    if (!elIn && !elOut && !elNet && !elAll) return;
    const safe = totals || { total_incoming: 0, total_outgoing: 0, net_total: 0, grand_total: 0, total_paid: 0 };
    if (elIn) elIn.textContent = fmtAmount(safe.total_incoming || 0);
    if (elOut) elOut.textContent = fmtAmount(safe.total_outgoing || 0);
    if (elNet) elNet.textContent = fmtAmount(safe.net_total || 0);
    if (elAll) elAll.textContent = fmtAmount(safe.grand_total || 0);
  }

  function printStatement() {
    try {
      const table = document.getElementById('paymentsTable');
      const title = 'كشف حساب - ' + (ctx.entity_type || '') + ' #' + (ctx.entity_id || '');
      const w = window.open('', 'stmt');
      if (!w || !w.document) throw new Error('Popup blocked');
      const doc = w.document;
      doc.documentElement.setAttribute('dir', 'rtl');
      doc.documentElement.setAttribute('lang', 'ar');
      doc.title = title;
      doc.head.textContent = '';
      doc.body.textContent = '';

      const meta = doc.createElement('meta');
      meta.setAttribute('charset', 'utf-8');
      doc.head.appendChild(meta);

      const link = doc.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/css/bootstrap.min.css';
      doc.head.appendChild(link);

      const style = doc.createElement('style');
      style.textContent = 'body{padding:24px}h3{margin-bottom:16px}table{font-size:12px}';
      doc.head.appendChild(style);

      const h3 = doc.createElement('h3');
      h3.textContent = title;
      doc.body.appendChild(h3);

      if (table) {
        const cloned = table.cloneNode(true);
        cloned.removeAttribute('id');
        doc.body.appendChild(cloned);
      }

      w.focus();
      setTimeout(function () {
        try { w.print(); } catch (e) {}
      }, 250);
    } catch (e) {
      alert('تعذر الطباعة الآن.');
    }
  }

  function exportCsv() {
    try {
      const headers = Array.from(document.querySelectorAll('#paymentsTable thead th')).map(function (th) { return th.textContent.trim(); }).slice(0, 8);
      const rows = _lastList.map(function (p) {
        const dateOnly = (p.payment_date || '').split('T')[0] || '';
        const method = (p.splits && p.splits.length) ? p.splits.map(function (s) { return String((s.method || '')).toUpperCase() + ': ' + fmtAmount(s.amount); }).join(' | ') : (p.method || '');
        return [String(p.id || ''), dateOnly, fmtAmount(p.total_amount), String(p.currency || ''), method, (p.direction || ''), (AR_STATUS[p.status] || p.status || ''), String(deriveEntityLabel(p) || '')];
      });
      const csv = [headers].concat(rows).map(function (r) { return r.map(function (cell) { return '"' + String(cell).replace(/"/g, '""') + '"'; }).join(','); }).join('\n');
      const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const now = new Date();
      const ymd = '' + now.getFullYear() + String(now.getMonth() + 1).padStart(2, '0') + String(now.getDate()).padStart(2, '0');
      a.href = url;
      a.download = 'statement_' + (ctx.entity_type || 'ALL').toLowerCase() + '_' + (ctx.entity_id || 'all') + '_' + ymd + '.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      alert('تعذر إنشاء CSV.');
    }
  }

  syncFiltersFromUrl();
  updateUrlQuery();
  loadPayments();
  window.addEventListener('popstate', function () { syncFiltersFromUrl(); loadPayments(1); });
});

// وظائف البحث الذكي - محسنة للأداء
function initSmartSearch() {
  // البحث عن جميع حقول البحث في الحقول الديناميكية
  const searchInputs = document.querySelectorAll('input[placeholder*="اكتب"], input[placeholder*="البحث"]');

  searchInputs.forEach(input => {
    // تحديد نوع الجهة من الـ placeholder أو الـ name
    let entityType = 'customer'; // افتراضي

    if (input.placeholder.includes('مورد') || input.placeholder.includes('تاجر')) {
      entityType = 'supplier';
    } else if (input.placeholder.includes('شريك')) {
      entityType = 'partner';
    } else if (input.placeholder.includes('زبون')) {
      entityType = 'customer';
    }

    if (!entityType) return;

    // تجنب إضافة event listeners متعددة
    if (input.hasAttribute('data-smart-search-initialized')) return;
    input.setAttribute('data-smart-search-initialized', 'true');

    let searchTimeout;
    let currentResults = [];
    let selectedIndex = -1;

    // إنشاء قائمة النتائج مرة واحدة فقط
    let resultsList = input.parentNode.querySelector('.smart-search-results');
    if (!resultsList) {
      resultsList = document.createElement('div');
      resultsList.className = 'smart-search-results position-absolute w-100 bg-white border shadow-lg rounded';
      resultsList.style.display = 'none';
      resultsList.style.zIndex = '1000';
      resultsList.style.maxHeight = '300px';
      resultsList.style.overflowY = 'auto';

      input.parentNode.style.position = 'relative';
      input.parentNode.appendChild(resultsList);
    }

    // وظيفة البحث
    function performSearch(query) {
      // تم تغيير الشرط للسماح بالبحث بحرف واحد
      if (query.length < 1) { // Changed from 2 to 1
        hideResults();
        return;
      }

      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        fetch(`/payments/search-entities?type=${entityType}&q=${encodeURIComponent(query)}`)
          .then(response => response.json())
          .then(data => {
            currentResults = data;
            selectedIndex = -1;
            showResults(data);
          })
          .catch(error => {

            hideResults();
          });
      }, 300);
    }

    // عرض النتائج
    function showResults(results) {
      if (results.length === 0) {
        hideResults();
        return;
      }
      resultsList.textContent = '';
      results.forEach((item, index) => {
        const itemDiv = document.createElement('div');
        itemDiv.className = `smart-search-item p-2 border-bottom ${index === selectedIndex ? 'bg-light' : ''}`;
        const name = document.createElement('span');
        name.className = 'fw-bold';
        name.textContent = String(item?.name || '');
        const meta = document.createElement('small');
        meta.className = 'text-muted';
        meta.textContent = ' (' + String(item?.id ?? '') + ')';
        itemDiv.appendChild(name);
        itemDiv.appendChild(meta);
        itemDiv.addEventListener('click', () => selectItem(item));
        resultsList.appendChild(itemDiv);
      });
      resultsList.style.display = 'block';
    }

    // إخفاء النتائج
    function hideResults() {
      resultsList.textContent = '';
      resultsList.style.display = 'none';
    }

    // تمييز العنصر المحدد
    function highlightSelectedItem() {
      resultsList.querySelectorAll('.smart-search-item').forEach((itemDiv, index) => {
        if (index === selectedIndex) {
          itemDiv.classList.add('bg-light');
          itemDiv.scrollIntoView({ block: 'nearest' });
        } else {
          itemDiv.classList.remove('bg-light');
        }
      });
    }

    // اختيار عنصر من القائمة
    function selectItem(item) {
      input.value = item.name;
      const hiddenInput = input.closest('[data-entity-type]').querySelector('input[type="hidden"]');
      if (hiddenInput) {
        hiddenInput.value = item.id;
      }
      hideResults();
    }

    // Event Listeners
    input.addEventListener('input', function() {
      performSearch(this.value.trim());
    });

    input.addEventListener('keydown', function(e) {
      if (resultsList.style.display === 'block' && currentResults.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          selectedIndex = (selectedIndex + 1) % currentResults.length;
          highlightSelectedItem();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          selectedIndex = (selectedIndex - 1 + currentResults.length) % currentResults.length;
          highlightSelectedItem();
        } else if (e.key === 'Enter') {
          e.preventDefault();
          if (selectedIndex !== -1) {
            selectItem(currentResults[selectedIndex]);
          }
        }
      }
    });

    input.addEventListener('focus', function() {
      if (currentResults.length > 0 && resultsList.childNodes.length > 0) {
        resultsList.style.display = 'block';
      }
    });

    input.addEventListener('blur', function() {
      setTimeout(() => {
        if (!resultsList.contains(document.activeElement)) {
          hideResults();
        }
      }, 100);
    });
  });
}

// استدعاء البحث الذكي تلقائياً عند تحميل الصفحة
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function() {
    setTimeout(initSmartSearch, 500);
  });
} else {
  // DOM already loaded
  setTimeout(initSmartSearch, 100);
}

// استدعاء إضافي عند تحميل الصفحة بالكامل
window.addEventListener('load', function() {
  setTimeout(initSmartSearch, 200);
});

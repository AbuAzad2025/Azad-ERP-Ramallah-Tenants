/* global jQuery */
(function() {
  if (window.__PAYMENTS_INIT__) return;
  window.__PAYMENTS_INIT__ = true;

let smartSearchInitialized = false;

function initializeSmartSearchOnce() {
  if (!smartSearchInitialized) {
    smartSearchInitialized = true;
    setTimeout(function() {
      initSmartSearch();
    }, 100);
  }
}

document.addEventListener('DOMContentLoaded', function() {
  'use strict';

  var getCSRFToken = window.getCSRFToken || function() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || document.getElementById('csrf_token')?.value || '';
  };

  initializeSmartSearchOnce();

  const filterSelectors = ['#filterEntity', '#filterStatus', '#filterDirection', '#filterMethod', '#startDate', '#endDate', '#filterCurrency'];
  const searchInput = document.querySelector('#payments-search');
  const ENTITY_ENUM = { customer:'CUSTOMER', supplier:'SUPPLIER', partner:'PARTNER', sale:'SALE', service:'SERVICE', expense:'EXPENSE', loan:'LOAN', preorder:'PREORDER', shipment:'SHIPMENT' };
  const AR_STATUS = { COMPLETED:'مكتملة', PENDING:'قيد الانتظار', FAILED:'فاشلة', REFUNDED:'مُرجعة', CANCELLED:'ملغية' };

  var normalizeEntity = window.normalizeEntity || function(val) { if (!val) return ''; var k = String(val).toLowerCase(); return ENTITY_ENUM[k] || String(val).toUpperCase(); };
  var normalizeMethod = window.normalizeMethod || function(v) { v = String(v || '').trim(); return v ? v.replace(/\s+/g,'_').replace(/-/g,'_').toUpperCase() : ''; };
  function normDir(v) { v = (v || '').toUpperCase(); if (v === 'INCOMING') return 'IN'; if (v === 'OUTGOING') return 'OUT'; return v; }
  var validDates = window.validDates || function(start, end) { if (!start || !end) return { start: start, end: end }; var s = new Date(start), e = new Date(end); if (isNaN(s) || isNaN(e)) return { start: start, end: end }; if (s.getTime() > e.getTime()) return { start: end, end: start }; return { start: start, end: end }; };
  var deriveEntityLabel = window.deriveEntityLabel || function(p) { if (p && p.entity_display) return p.entity_display; var m = [['customer_id','عميل'],['supplier_id','مورد'],['partner_id','شريك'],['sale_id','بيع'],['invoice_id','فاتورة'],['service_id','صيانة'],['shipment_id','شحنة'],['expense_id','مصروف'],['preorder_id','حجز'],['loan_settlement_id','تسوية']]; for (var i = 0; i < m.length; i++) if (p && p[m[i][0]]) return m[i][1] + ' #' + p[m[i][0]]; return (p && p.entity_type) || ''; };
  function inferEntityContext() {
    const path = location.pathname.replace(/\/+$/, '');
    const m = path.match(/^\/vendors\/(suppliers|partners)\/(\d+)\/payments$/i);
    if (m) return { entity_type: m[1].toLowerCase()==='suppliers' ? 'SUPPLIER' : 'PARTNER', entity_id: m[2] };
    const msale = path.match(/^\/sales\/(\d+)\/payments$/i);
    if (msale) return { entity_type: 'SALE', entity_id: msale[1] };
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
    wrap.className = 'col-auto d-flex gap-2 no-print';
    wrap.innerHTML = '<button id="btnExportCsv" class="btn btn-outline-success"><i class="fas fa-file-csv me-1"></i> تصدير CSV</button>';
    filtersRow.appendChild(wrap);
    document.getElementById('btnExportCsv').addEventListener('click', exportCsv);
  }
  injectStatementButtons();
  if (typeof window !== 'undefined' && typeof window.enableTableSorting === 'function') {
    window.enableTableSorting('#paymentsTable');
  }
  var debounce = window.debounce || function(fn, ms) { var t; return function () { clearTimeout(t); t = setTimeout(function() { fn.apply(this, arguments); }, ms); }; };
  const debouncedReload = debounce(function () { updateUrlQuery(); loadPayments(1); }, 250);
  
  
  const applyFilters = function() {
    updateUrlQuery();
    loadPayments(1);
    if (btnApplyFilters) {
      btnApplyFilters.classList.remove('btn-warning');
      btnApplyFilters.classList.add('btn-success');
      btnApplyFilters.innerHTML = '<i class="fas fa-filter me-1"></i> تطبيق';
    }
  };
  
  const resetFilters = function() {
    const qs = new URLSearchParams(location.search);
    const entityType = qs.get('entity_type') || '';
    const entityId = qs.get('entity_id') || '';
    
    const filterEntity = document.querySelector('#filterEntity');
    const filterStatus = document.querySelector('#filterStatus');
    const filterDirection = document.querySelector('#filterDirection');
    const filterMethod = document.querySelector('#filterMethod');
    const startDate = document.querySelector('#startDate');
    const endDate = document.querySelector('#endDate');
    const filterCurrency = document.querySelector('#filterCurrency');
    
    if (filterEntity) filterEntity.value = entityType;
    if (filterStatus) filterStatus.value = '';
    if (filterDirection) filterDirection.value = '';
    if (filterMethod) filterMethod.value = '';
    if (startDate) startDate.value = '';
    if (endDate) endDate.value = '';
    if (filterCurrency) filterCurrency.value = '';
    if (searchInput) searchInput.value = '';
    
    if (btnApplyFilters) {
      btnApplyFilters.classList.remove('btn-warning');
      btnApplyFilters.classList.add('btn-success');
      btnApplyFilters.innerHTML = '<i class="fas fa-filter me-1"></i> تطبيق';
    }
    
    const params = new URLSearchParams();
    if (entityType) params.append('entity_type', entityType);
    if (entityId) params.append('entity_id', entityId);
    history.replaceState(null, '', location.pathname + (params.toString() ? ('?' + params.toString()) : ''));
    loadPayments(1);
  };
  
  const btnApplyFilters = document.getElementById('btnApplyFilters');
  if (btnApplyFilters) {
    btnApplyFilters.addEventListener('click', applyFilters);
  }
  
  const btnResetFilters = document.getElementById('btnResetFilters');
  if (btnResetFilters) {
    btnResetFilters.addEventListener('click', resetFilters);
  }
  
  filterSelectors.forEach(function (sel) {
    const el = document.querySelector(sel);
    if (!el) return;
    el.addEventListener('change', function() {
      if (btnApplyFilters) {
        btnApplyFilters.classList.add('btn-warning');
        btnApplyFilters.innerHTML = '<i class="fas fa-filter me-1"></i> تطبيق <span class="badge bg-light text-dark ms-1">تغييرات</span>';
      }
    }, { passive: true });
    if (el.tagName === 'INPUT') {
      el.addEventListener('input', function() {
        if (btnApplyFilters) {
          btnApplyFilters.classList.add('btn-warning');
          btnApplyFilters.innerHTML = '<i class="fas fa-filter me-1"></i> تطبيق <span class="badge bg-light text-dark ms-1">تغييرات</span>';
        }
      }, { passive: true });
    }
  });
  if (searchInput) {
    searchInput.addEventListener('input', function() {
      if (btnApplyFilters) {
        btnApplyFilters.classList.add('btn-warning');
        btnApplyFilters.innerHTML = '<i class="fas fa-filter me-1"></i> تطبيق <span class="badge bg-light text-dark ms-1">تغييرات</span>';
      }
      debouncedReload();
    }, { passive: true });
  }
  function currentFilters(page = 1) {
    const urlParams = new URLSearchParams(window.location.search);
    const raw = {
      entity_type: normalizeEntity(document.querySelector('#filterEntity')?.value || ctx.entity_type || ''),
      status: document.querySelector('#filterStatus')?.value || '',
      direction: normDir(document.querySelector('#filterDirection')?.value || ''),
      method: normalizeMethod(document.querySelector('#filterMethod')?.value || ''),
      start_date: document.querySelector('#startDate')?.value || '',
      end_date: document.querySelector('#endDate')?.value || '',
      currency: (document.querySelector('#filterCurrency')?.value || '').toUpperCase(),
      q: (searchInput && searchInput.value) ? searchInput.value.trim() : '',
      sort: urlParams.get('sort') || 'date',
      order: urlParams.get('order') || 'desc',
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
    setVal('#payments-search', qs.get('q'));
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
    params.append('format', 'json'); // إضافة format=json لإرجاع JSON
    if (_abortCtrl) _abortCtrl.abort();
    _abortCtrl = new AbortController();
    setLoading(true);
    fetch('/payments/?' + params.toString(), { headers: { 'Accept': 'application/json' }, signal: _abortCtrl.signal })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        const list = Array.isArray(data.payments) ? data.payments : [];
        _currentPageSum = {
          sum: data.totals?.page_sum || 0,
          sumILS: data.totals?.page_sum_ils || 0
        };
        _lastList = list.slice();
        try {
          renderPaymentsTable(_lastList);
        } catch (renderErr) {
          console.error('renderPaymentsTable error:', renderErr);
          renderPaymentsTable([]);
        }
        renderPagination(Number(data.total_pages || 1), Number(data.current_page || 1));
        renderTotals(data.totals || null);
        const searchSummaryEl = document.getElementById('payments-search-summary');
        if (searchSummaryEl) searchSummaryEl.textContent = 'إجمالي النتائج: ' + (data.total_items || 0);
        const totalCountEl = document.getElementById('payments-total-count');
        if (totalCountEl) totalCountEl.textContent = data.total_items || 0;
        const card = document.getElementById('paymentsCard');
        if (card) card.style.display = '';
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        _lastList = [];
        renderPaymentsTable([]);
        renderPagination(1, 1);
        renderTotals(null);
        const searchSummaryEl = document.getElementById('payments-search-summary');
        if (searchSummaryEl) searchSummaryEl.textContent = 'إجمالي النتائج: 0';
        const totalCountEl = document.getElementById('payments-total-count');
        if (totalCountEl) totalCountEl.textContent = '0';
      })
      .finally(function () { setLoading(false); });
  }
  function setLoading(is) {
    const tbody = document.querySelector('#paymentsTable tbody');
    if (!tbody) return;
    if (is) tbody.innerHTML = '<tr><td colspan="13" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2"></div>جارِ التحميل…</td></tr>';
  }
  let _currentPageSum = {sum: 0, sumILS: 0};
  
  function renderPaymentsTable(list) {
    const tbody = document.querySelector('#paymentsTable tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!list.length) {
      const message = 'لا توجد بيانات';
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 13;
      td.className = 'text-center text-muted py-4';
      td.textContent = message;
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    const sanitize = function (v) {
      if (v == null) return '';
      return String(v)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    };
    const sanitizeAttr = sanitize;
    const safePath = function (segment) {
      return encodeURIComponent(String(segment == null ? '' : segment));
    };
    const sorted = list.slice().sort(function (a, b) {
      const db = b.payment_date ? Date.parse(b.payment_date) : 0;
      const da = a.payment_date ? Date.parse(a.payment_date) : 0;
      if (!Number.isNaN(db) && !Number.isNaN(da) && db !== da) return db - da;
      const bi = b.id || 0;
      const ai = a.id || 0;
      return bi - ai;
    });
    let sumAmount = 0;
    let sumAmountIls = 0;
    sorted.forEach(function (p) {
      const splitsHtml = (p.splits || []).map(function (s) {
        const splitCurrency = (s.currency || p.currency || '').toUpperCase();
        const convertedCurrency = (p.currency || '').toUpperCase();
        const methodTxt = sanitize(String((s.method || '')).toUpperCase());
        const splitCurTxt = sanitize(splitCurrency);
        const convCurTxt = sanitize(convertedCurrency);
        let text = methodTxt + ': ' + fmtAmount(s.amount) + ' ' + splitCurTxt;
        if (splitCurrency && convertedCurrency && splitCurrency !== convertedCurrency && s.converted_amount != null) {
          text += '<span class="text-light text-opacity-75 ms-1">≈ ' + fmtAmount(s.converted_amount) + ' ' + convCurTxt + '</span>';
        }
        return '<span class="badge bg-secondary me-1 text-light">' + text + '</span>';
      }).join(' ');
      const dateOnly = (p.payment_date || '').split('T')[0] || '';
      var viewLink = '/payments/' + safePath(p.id);
      if (p && typeof p.payment_id === 'number' && typeof p.split_id === 'number') {
        viewLink = '/payments/' + safePath(p.payment_id) + '/split/' + safePath(p.split_id);
      } else if (p && typeof p.id === 'string' && p.id.indexOf('check_') === 0) {
        var cid = p.id.replace('check_', '');
        if (cid && String(cid).trim()) {
          viewLink = '/checks/detail/' + safePath(cid);
        }
      }
      var actionsHtml = '<div class="btn-group btn-group-xs action-btns" role="group">' +
        '<a href="' + viewLink + '" class="btn btn-info rounded-start-pill" title="عرض"><i class="fas fa-eye"></i></a>';
      
      if (p.is_archived) {
          actionsHtml += '<button type="button" class="btn btn-success btn-restore" data-id="' + sanitizeAttr(p.id) + '" title="استعادة"><i class="fas fa-undo"></i></button>';
      } else {
          actionsHtml += '<button type="button" class="btn btn-warning btn-archive" data-id="' + sanitizeAttr(p.id) + '" title="أرشفة"><i class="fas fa-archive"></i></button>';
      }

      var st = String(p.status || '').toUpperCase();
      var isSplit = false;
      var splitId = null;
      var paymentId = null;
      if (p && typeof p.payment_id === 'number' && typeof p.split_id === 'number') {
        isSplit = true;
        splitId = p.split_id;
        paymentId = p.payment_id;
      } else if (typeof p.id === 'string' && p.id.indexOf('_split_') > -1) {
        isSplit = true;
        var parts = p.id.split('_split_');
        paymentId = parseInt(parts[0], 10);
        splitId = parseInt(parts[1], 10);
      }
      var isManualCheck = typeof p.id === 'string' && p.id.indexOf('check_') === 0;

      if (!isManualCheck) {
        var receiptPaymentId = isSplit ? paymentId : (typeof p.id === 'number' ? p.id : null);
        if (receiptPaymentId) {
          actionsHtml += '<a href="' + (window.gmPath || function(p){ return p; })('/payments/' + receiptPaymentId + '/receipt') + '" target="_blank" class="btn btn-secondary" title="إيصال"><i class="fas fa-receipt"></i></a>';
        }
        if (isSplit) {
          var refundedFlag = (typeof p.is_refunded_split === 'boolean') ? p.is_refunded_split : false;
          if (!refundedFlag && (st === 'COMPLETED' || st === 'CASHED')) {
            actionsHtml += '<button type="button" class="btn btn-warning btn-refund rounded-end-pill" data-split-id="' + splitId + '" data-split-refunded="false" title="إرجاع"><i class="fas fa-undo"></i></button>';
          }
        } else {
          if (st === 'COMPLETED') {
            actionsHtml += '<button type="button" class="btn btn-warning btn-refund rounded-end-pill" data-payment-id="' + (p.id || '') + '" data-status="COMPLETED" title="إرجاع"><i class="fas fa-undo"></i></button>';
          }
        }
      }

      actionsHtml += '</div>';
      const tr = document.createElement('tr');
      let amountInILS = p.amount_in_ils || p.total_amount; // fallback للبيانات القديمة
      let fxRateDisplay = '-';
      
      if (p.currency && p.currency !== 'ILS') {
        if (typeof FXUtils !== 'undefined' && FXUtils.formatFxRate) {
          if (p.fx_rate_used && parseFloat(p.fx_rate_used) > 0) {
            fxRateDisplay = FXUtils.formatFxRate(parseFloat(p.fx_rate_used), p.fx_rate_source);
          } else {
            fxRateDisplay = FXUtils.formatFxRate(1, 'default');
          }
        } else {
          fxRateDisplay = String(p.fx_rate_used || '1');
        }
      }
      const amountNumeric = Number(p.total_amount || 0);
      if (!Number.isNaN(amountNumeric)) sumAmount += amountNumeric;
      const amountIlsNumeric = Number(amountInILS || 0);
      if (!Number.isNaN(amountIlsNumeric)) sumAmountIls += amountIlsNumeric;
      
      const entityDetails = deriveEntityLabel(p);
      let notesHtml = '';
      if (p.is_manual_check) {
        notesHtml += '<div class="mt-1"><span class="badge bg-warning text-dark"><i class="fas fa-file-invoice"></i> شيك يدوي';
        if (p.check_number) {
          notesHtml += ' - رقم: ' + sanitize(p.check_number);
        }
        notesHtml += '</span></div>';
      }
      if (p.notes && p.notes.trim()) {
        const note = p.notes.substring(0, 80);
        notesHtml += '<div class="mt-1"><small class="text-muted"><i class="fas fa-sticky-note"></i> ' + sanitize(note) + (p.notes.length > 80 ? '...' : '') + '</small></div>';
      }
      var delivererText = p.deliverer_name && p.deliverer_name.trim() ? sanitize(p.deliverer_name.trim()) : '-';
      var receiverText = p.receiver_name && p.receiver_name.trim() ? sanitize(p.receiver_name.trim()) : '-';
      
      tr.innerHTML =
        '<td class="text-center" data-sort-value="' + sanitizeAttr(p.id || 0) + '"><strong>' + sanitize(p.id) + '</strong></td>' +
        '<td class="text-center" data-sort-value="' + (p.payment_date || '') + '">' + dateOnly + '</td>' +
        '<td class="text-end" data-sort-value="' + (amountNumeric || 0) + '"><strong>' + fmtAmount(p.total_amount) + '</strong></td>' +
        '<td class="text-center"><span class="badge badge-secondary">' + sanitize(p.currency || '') + '</span></td>' +
        '<td class="text-center"><small>' + fxRateDisplay + '</small></td>' +
        '<td class="text-end" data-sort-value="' + (amountIlsNumeric || 0) + '"><strong style="color: #0056b3;">' + fmtAmount(amountInILS) + ' ₪</strong></td>' +
        '<td class="text-center">' + (p.is_manual_check ? '<span class="badge bg-warning text-dark"><i class="fas fa-file-invoice"></i> شيك يدوي</span>' : (splitsHtml || '<span class="badge badge-info">' + sanitize(p.method || '') + '</span>')) + '</td>' +
        '<td class="text-center">' + badgeForDirection(p.direction) + '</td>' +
        '<td class="text-center">' + badgeForStatus(p.status) + '</td>' +
        '<td>' + entityDetails + '</td>' +
        '<td>' + delivererText + '</td>' +
        '<td>' + receiverText + '</td>' +
        '<td>' + notesHtml + '</td>' +
        '<td class="text-center">' + actionsHtml + '</td>';
      tbody.appendChild(tr);
    });
    const totalsSource = _currentPageSum || { sum: sumAmount, sumILS: sumAmountIls };
    const totalsLabel = 'إجمالي الصفحة';
    const totalRow = document.createElement('tr');
    totalRow.dataset.sortFixed = 'true';
    totalRow.innerHTML = '<td></td><td class="text-end fw-bold">' + totalsLabel + '</td><td class="fw-bold">' + fmtAmount(totalsSource.sum) + '</td><td></td><td></td><td class="fw-bold" style="color: #0056b3;">' + fmtAmount(totalsSource.sumILS) + ' ₪</td><td colspan="8"></td>';
    tbody.appendChild(totalRow);
  }
  

  document.addEventListener('click', async function (e) {
    const btn = e.target.closest('.btn-archive');
    if (!btn) return;
    const id = btn.dataset.id;
    if (!id) return;
    
    const reason = prompt('أدخل سبب أرشفة هذه الدفعة:');
    if (!reason) return;
    
    if (!confirm('هل أنت متأكد من أرشفة سند الدفع #' + id + '؟')) return;
    
    const csrf = getCSRFToken();
    try {
      const r = await fetch('/payments/archive/' + id, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
        },
        body: new URLSearchParams({ 
          csrf_token: csrf,
          reason: reason
        }).toString()
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && (j.status === 'success' || j.ok)) {
        loadPayments();
        if(typeof showToast!=='undefined'){showToast('تم أرشفة سند الدفع بنجاح', 'success');}else{alert('تم أرشفة سند الدفع بنجاح');};
      } else {
        if(typeof showToast!=='undefined'){showToast('تعذر الأرشفة: ' + (j.message || 'خطأ غير معروف'), 'error');}else{alert('تعذر الأرشفة: ' + (j.message || 'خطأ غير معروف'));};
      }
    } catch (err) {
      if(typeof showToast!=='undefined'){showToast('خطأ في الاتصال بالخادم.', 'error');}else{alert('خطأ في الاتصال بالخادم.');};
    }
  });

  document.addEventListener('click', async function (e) {
    const btn = e.target.closest('.btn-restore');
    if (!btn) return;
    const id = btn.dataset.id;
    if (!id) return;
    
    if (!confirm('هل أنت متأكد من استعادة سند الدفع #' + id + '؟')) return;
    
    const csrf = getCSRFToken();
    try {
      const r = await fetch('/payments/restore/' + id, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
        },
        body: new URLSearchParams({ 
          csrf_token: csrf
        }).toString()
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && (j.status === 'success' || j.success || j.ok)) {
        loadPayments();
        if(typeof showToast!=='undefined'){showToast('تم استعادة سند الدفع بنجاح', 'success');}else{alert('تم استعادة سند الدفع بنجاح');};
      } else {
        if(typeof showToast!=='undefined'){showToast('تعذر الاستعادة: ' + (j.message || 'خطأ غير معروف'), 'error');}else{alert('تعذر الاستعادة: ' + (j.message || 'خطأ غير معروف'));};
      }
    } catch (err) {
      if(typeof showToast!=='undefined'){showToast('خطأ في الاتصال بالخادم.', 'error');}else{alert('خطأ في الاتصال بالخادم.');};
    }
  });

  document.addEventListener('click', async function (e) {
    const btn = e.target.closest('.btn-refund');
    if (!btn) return;
    var sid = btn.getAttribute('data-split-id');
    var pid = btn.getAttribute('data-payment-id');
    if (!(sid || pid)) return;
    var isSplitRefunded = btn.getAttribute('data-split-refunded');
    var payStatus = btn.getAttribute('data-status');
    if (sid && isSplitRefunded === 'true') { if(typeof showToast!=='undefined'){showToast('لا يمكن إرجاع جزء مُرجع بالفعل.', 'success');}else{alert('لا يمكن إرجاع جزء مُرجع بالفعل.');}; return; }
    if (pid && payStatus && payStatus !== 'COMPLETED') { if(typeof showToast!=='undefined'){showToast('لا يمكن إرجاع إلا الدفعات المكتملة محاسبياً.', 'success');}else{alert('لا يمكن إرجاع إلا الدفعات المكتملة محاسبياً.');}; return; }
    if (!confirm('سيتم إنشاء سند عكسي بنفس المبلغ وبالاتجاه المعاكس مع تحديث دفتر الأستاذ ووضع الدفعة/الجزء كمُرجع. هل أنت متأكد من الإرجاع؟')) return;
    const csrf = getCSRFToken();
    try {
      var url = sid ? ('/payments/split/' + sid + '/refund') : ('/payments/refund/' + pid);
      const r = await fetch(url, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'X-CSRFToken': csrf
        },
        body: new URLSearchParams({ csrf_token: csrf }).toString()
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && (j.success || j.ok)) {
        if(typeof showToast!=='undefined'){showToast('تم تنفيذ الإرجاع بنجاح: تم إنشاء سند عكسي وتحديث دفتر الأستاذ', 'success');}else{alert('تم تنفيذ الإرجاع بنجاح: تم إنشاء سند عكسي وتحديث دفتر الأستاذ');};
        loadPayments(1);
      } else {
        if(typeof showToast!=='undefined'){showToast('تعذر الإرجاع محاسبياً: ' + (j.message || 'العملية غير منطقية أو غير متاحة'), 'error');}else{alert('تعذر الإرجاع محاسبياً: ' + (j.message || 'العملية غير منطقية أو غير متاحة'));};
      }
    } catch (err) {
      if(typeof showToast!=='undefined'){showToast('خطأ في الاتصال بالخادم.', 'error');}else{alert('خطأ في الاتصال بالخادم.');};
    }
  });

  
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
      a.textContent = String(label || '');
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
    const safe = totals || { total_incoming: 0, total_outgoing: 0, net_total: 0, grand_total: 0, total_paid: 0 };
    const incomingEl = document.getElementById('payments-total-incoming');
    if (incomingEl) incomingEl.textContent = fmtAmount(safe.total_incoming || 0);
    const outgoingEl = document.getElementById('payments-total-outgoing');
    if (outgoingEl) outgoingEl.textContent = fmtAmount(safe.total_outgoing || 0);
    const netEl = document.getElementById('payments-net-total');
    if (netEl) netEl.textContent = fmtAmount(safe.net_total || 0);
    const grandEl = document.getElementById('payments-grand-total');
    if (grandEl) grandEl.textContent = fmtAmount(safe.grand_total || 0);
  }
  function exportCsv() {
    try {
      const headers = Array.from(document.querySelectorAll('#paymentsTable thead th')).map(function (th) { return th.textContent.trim(); }).slice(0, 8);
      const stripTags = (s) => String(s || '').replace(/<[^>]*>/g, '');
      const rows = _lastList.map(function (p) {
        const dateOnly = (p.payment_date || '').split('T')[0] || '';
        const method = (p.splits && p.splits.length) ? p.splits.map(function (s) { return String((s.method || '')).toUpperCase() + ': ' + fmtAmount(s.amount); }).join(' | ') : (p.method || '');
        return [String(p.id || ''), dateOnly, fmtAmount(p.total_amount), String(p.currency || ''), method, (p.direction || ''), (AR_STATUS[p.status] || p.status || ''), stripTags(deriveEntityLabel(p) || '')];
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
      if(typeof showToast!=='undefined'){showToast('تعذر إنشاء CSV.', 'success');}else{alert('تعذر إنشاء CSV.');};
    }
  }
  syncFiltersFromUrl();
  updateUrlQuery();
  loadPayments();
  window.addEventListener('popstate', function () { syncFiltersFromUrl(); loadPayments(1); });
});

function initSmartSearch() {
  const searchInputs = document.querySelectorAll('input[placeholder*="اكتب"], input[placeholder*="البحث"]');
  
  searchInputs.forEach(input => {
    let entityType = 'customer'; // افتراضي
    
    if (input.placeholder.includes('مورد') || input.placeholder.includes('تاجر')) {
      entityType = 'supplier';
    } else if (input.placeholder.includes('شريك')) {
      entityType = 'partner';
    } else if (input.placeholder.includes('عميل')) {
      entityType = 'customer';
    }
    
    if (!entityType) return;
    
    if (input.hasAttribute('data-smart-search-initialized')) return;
    input.setAttribute('data-smart-search-initialized', 'true');
    
    let searchTimeout;
    let currentResults = [];
    let selectedIndex = -1;
    
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
    
    function performSearch(query) {
      if (query.length < 1) {
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
    
    function showResults(results) {
      if (results.length === 0) {
        hideResults();
        return;
      }

      resultsList.textContent = '';
      results.forEach((result, index) => {
        const item = document.createElement('div');
        item.className = 'smart-search-item p-2 border-bottom cursor-pointer';
        item.dataset.index = String(index);
        const title = document.createElement('div');
        title.className = 'fw-bold';
        title.textContent = result?.display || '';
        item.appendChild(title);
        if (result && result.phone) {
          const phone = document.createElement('small');
          phone.className = 'text-muted';
          phone.textContent = String(result.phone);
          item.appendChild(phone);
        }
        item.addEventListener('click', () => selectResult(index));
        item.addEventListener('mouseenter', () => highlightItem(index));
        resultsList.appendChild(item);
      });

      resultsList.style.display = 'block';
    }
    
    function hideResults() {
      resultsList.style.display = 'none';
      currentResults = [];
      selectedIndex = -1;
    }
    
    function selectResult(index) {
      if (index >= 0 && index < currentResults.length) {
        const result = currentResults[index];
        input.value = result.display;
        
        const entityIdField = input.parentNode.querySelector('input[type="hidden"]');
        if (entityIdField) {
          entityIdField.value = result.id;
        }
        
        hideResults();
      }
    }
    
    function highlightItem(index) {
      resultsList.querySelectorAll('.smart-search-item').forEach((item, i) => {
        item.classList.toggle('bg-light', i === index);
      });
      selectedIndex = index;
    }
    
    input.addEventListener('input', (e) => {
      performSearch(e.target.value);
    });
    
    input.addEventListener('focus', (e) => {
      if (currentResults.length > 0) {
        showResults(currentResults);
      }
    });
    
    input.addEventListener('blur', (e) => {
      setTimeout(() => hideResults(), 200);
    });
    
    input.addEventListener('keydown', (e) => {
      if (resultsList.style.display === 'none') return;
      
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          selectedIndex = Math.min(selectedIndex + 1, currentResults.length - 1);
          highlightItem(selectedIndex);
          break;
        case 'ArrowUp':
          e.preventDefault();
          selectedIndex = Math.max(selectedIndex - 1, -1);
          if (selectedIndex >= 0) {
            highlightItem(selectedIndex);
          } else {
            resultsList.querySelectorAll('.smart-search-item').forEach(item => {
              item.classList.remove('bg-light');
            });
          }
          break;
        case 'Enter':
          e.preventDefault();
          if (selectedIndex >= 0) {
            selectResult(selectedIndex);
          }
          break;
        case 'Escape':
          e.preventDefault();
          hideResults();
          break;
      }
    });
  });
}

document.addEventListener('change', function(e) {
  if (e.target && e.target.name === 'entity_type') {
    smartSearchInitialized = false;
    setTimeout(function() {
      initializeSmartSearchOnce();
    }, 200);
  }
});
})();

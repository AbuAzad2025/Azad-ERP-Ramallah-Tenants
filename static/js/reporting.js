(function () {
  if (window.__REPORTING_INIT__) return;
  window.__REPORTING_INIT__ = true;
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const safeJSON = (s, fallback = null) => { try { return JSON.parse(s || ""); } catch { return fallback; } };
  const t = (k) => {
    const labels = window.FIELD_LABELS || {};
    return labels[k] || k;
  };

  const EXCLUDED = (window.EXCLUDED_FIELDS || []).map(String);
  const filterList = (arr) => (arr || []).filter((x) => !EXCLUDED.includes(String(x)));

  const STORAGE_KEY = 'dynamic_report_state.v2';
  const saveState = () => {
    const f = $('#report-form');
    if (!f) return;
    const sel = (name) => $(`[name="${name}"]`, f);
    const selected = Array.from($('#selected_fields')?.selectedOptions || []).map(o => o.value);
    const state = {
      table: sel('table')?.value || '',
      date_field: sel('date_field')?.value || '',
      start_date: sel('start_date')?.value || '',
      end_date: sel('end_date')?.value || '',
      limit: sel('limit')?.value || '',
      selected_fields: filterList(selected),
      like_filters: collectLikeFilters()
    };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {}
  };
  const loadState = () => {
    try {
      const st = safeJSON(localStorage.getItem(STORAGE_KEY), null) || null;
      if (!st) return null;
      st.selected_fields = filterList(st.selected_fields);
      if (st.date_field && EXCLUDED.includes(st.date_field)) st.date_field = '';
      return st;
    } catch { return null; }
  };

  let dt;
  function initDataTable() {
    const table = $('#report-table');
    if (!table || !table.length || !window.jQuery || !jQuery.fn?.DataTable) {
      if (table && table.length && window.jQuery && typeof window.ensureDataTables === 'function') {
        window.ensureDataTables().then(initDataTable);
      }
      return;
    }
    if (jQuery.fn.dataTable.isDataTable(table)) {
      dt = jQuery(table).DataTable();
      return;
    }
    
    // تحقق من البنية
    if (!table.find('thead').length || !table.find('tbody').length) {
      return;
    }
    
    // تحقق من وجود بيانات فعلية
    const dataRows = table.find('tbody tr').not(':has(td[colspan])');
    if (dataRows.length === 0) {
      return; // لا نهيئ DataTables للجداول الفارغة
    }
    
    // تحقق من تطابق الأعمدة
    const headerCols = table.find('thead tr:first th, thead tr:first td').length;
    const bodyCols = dataRows.first().find('td').length;
    
    if (headerCols !== bodyCols) {

      return;
    }
    
    try {
      dt = jQuery(table).DataTable({
        pageLength: 50,
        order: [],
        autoWidth: false,
        responsive: true,
        scrollX: headerCols > 8,
        language: {
          emptyTable: "لا توجد بيانات",
          info: "إظهار _START_ إلى _END_ من أصل _TOTAL_",
          infoEmpty: "إظهار 0 إلى 0 من أصل 0",
          lengthMenu: "إظهار _MENU_",
          loadingRecords: "جارٍ التحميل...",
          processing: "جارٍ المعالجة...",
          search: "بحث:",
          zeroRecords: "لا نتائج مطابقة",
          paginate: { first: "الأول", last: "الأخير", next: "التالي", previous: "السابق" }
        }
      });
    } catch (e) {

    }
  }

  function renderTable(headers, rows) {
    headers = filterList(Array.isArray(headers) ? headers : []);
    rows = Array.isArray(rows) ? rows.map(r => {
      const o = {};
      headers.forEach(h => { o[h] = r[h]; });
      return o;
    }) : [];

    const thead = $('#thead-dynamic');
    const tbody = $('#tbody-dynamic');
    const noData = $('#no-data');

    thead.innerHTML = '';
    const trh = document.createElement('tr');
    headers.forEach(h => {
      const th = document.createElement('th');
      th.textContent = t(h);
      trh.appendChild(th);
    });
    thead.appendChild(trh);

    tbody.innerHTML = '';
    rows.forEach(obj => {
      const tr = document.createElement('tr');
      headers.forEach(h => {
        const td = document.createElement('td');
        let v = obj[h];
        if (typeof v === 'number' && isFinite(v)) {
          td.classList.add('text-end');
          v = Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
        } else if (v == null || v === '') {
          v = '—';
        }
        td.textContent = v;
        td.classList.add('text-nowrap');
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });

    if (dt) {
      dt.clear();
      dt.rows.add(jQuery(tbody).find('tr'));
      dt.draw();
    } else {
      initDataTable();
    }
    $('#result-count').textContent = rows.length || 0;
    noData.classList.toggle('d-none', rows.length > 0);
  }

  function translateField(name) { return t(name); }

  async function fetchModelFields(model) {
    if (!model) return { columns: [], date_fields: [], all_fields: [] };
    const r = await fetch(`/reports/api/model_fields?model=${encodeURIComponent(model)}`);
    if (!r.ok) return { columns: [], date_fields: [], all_fields: [] };
    const json = await r.json();
    json.columns = filterList(json.columns);
    json.date_fields = filterList(json.date_fields);
    json.all_fields = filterList(json.all_fields);
    return json;
  }

  function fillSelectOptions(select, items, keepSelected = true) {
    if (!select) return;
    const prev = keepSelected ? new Set(Array.from(select.selectedOptions).map(o => o.value)) : new Set();
    select.innerHTML = '';
    filterList(items || []).forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = translateField(v);
      if (prev.has(v)) opt.selected = true;
      select.appendChild(opt);
    });
    const pre = safeJSON(select.getAttribute('data-selected'), []);
    if (pre?.length) {
      const filteredPre = filterList(pre);
      $$('#selected_fields option').forEach(o => o.selected = filteredPre.includes(o.value));
      select.removeAttribute('data-selected');
    }
  }

  function applyDateFieldOptions(select, dateFields) {
    if (!select) return;
    const current = select.getAttribute('data-selected') || select.value || '';
    const def = select.getAttribute('data-default') || '';
    select.innerHTML = '<option value="">—</option>';
    filterList(dateFields || []).forEach(df => {
      const opt = document.createElement('option');
      opt.value = df;
      opt.textContent = translateField(df);
      select.appendChild(opt);
    });
    const canUse = (v) => v && $(`option[value="${CSS.escape(v)}"]`, select);
    if (canUse(current)) {
      select.value = current;
    } else if (canUse(def)) {
      select.value = def;
    } else {
      select.value = '';
    }
    select.setAttribute('data-selected', select.value || '');
  }

  const LIKE_HINTS = ['name','number','code','sku','email','phone','notes','desc','reference','tracking'];
  function isLikelyTextField(c) {
    const lc = (c || '').toLowerCase();
    return LIKE_HINTS.some(k => lc.includes(k));
  }
  function buildLikeFilters(columns) {
    const wrap = $('#like_filters');
    if (!wrap) return;
    const initial = safeJSON(wrap.getAttribute('data-initial-like'), {}) || {};
    wrap.innerHTML = '';
    const textCols = filterList(columns || []).filter(isLikelyTextField).slice(0, 12);
    textCols.forEach(col => {
      const div = document.createElement('div');
      div.className = 'col-lg-3 col-md-4 col-sm-6';
      const label = document.createElement('label');
      label.className = 'form-label';
      label.textContent = translateField(col);
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-control';
      input.name = col;
      input.placeholder = `يحتوي… (${translateField(col)})`;
      if (initial[col] != null) input.value = String(initial[col]);
      div.appendChild(label);
      div.appendChild(input);
      wrap.appendChild(div);
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          $('#report-form')?.requestSubmit();
        }
      });
    });
  }

  function collectLikeFilters() {
    const obj = {};
    $$('#like_filters input[name]').forEach(inp => {
      const val = inp.value?.trim();
      if (val) obj[inp.name] = val;
    });
    return obj;
  }

  function showLoading(v) { $('#loading-overlay')?.classList.toggle('d-none', !v); }

  async function runDynamicReport() {
    const form = $('#report-form');
    if (!form) return;
    const fd = new FormData(form);
    let cols = Array.from($('#selected_fields')?.selectedOptions || []).map(o => o.value);
    cols = filterList(cols);
    const payload = {
      table: fd.get('table') || '',
      date_field: EXCLUDED.includes(String(fd.get('date_field') || '')) ? '' : (fd.get('date_field') || ''),
      start_date: fd.get('start_date') || '',
      end_date: fd.get('end_date') || '',
      limit: Number(fd.get('limit') || 1000),
      columns: cols,
      like_filters: collectLikeFilters(),
      aggregates: { count: ['id'] }
    };
    const csrf = form.querySelector('input[name="csrf_token"]')?.value || '';
    showLoading(true);
    try {
      if (typeof window.gmRequirePermAny === 'function' && !window.gmRequirePermAny('view_reports', 'manage_reports')) {
        throw new Error('ليس لديك صلاحية لتشغيل هذا التقرير.');
      }
      const r = await fetch('/reports/api/dynamic', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(csrf ? { 'X-CSRFToken': csrf } : {})
        },
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error('فشل الاتصال بالسيرفر');
      const data = await r.json();
      let rows = Array.isArray(data.data) ? data.data : [];
      const headersFromRows = rows.length ? Object.keys(rows[0]) : (cols || []);
      const headers = filterList(headersFromRows);
      rows = rows.map(rec => {
        const o = {};
        headers.forEach(h => { o[h] = rec[h]; });
        return o;
      });
      const limited = rows.slice(0, payload.limit || 1000);
      renderTable(headers, limited);
      renderSummary(data.summary || {});
      saveState();
    } catch (e) {
      alert("حدث خطأ أثناء جلب التقرير: " + e.message);

    } finally {
      showLoading(false);
    }
  }

  function renderSummary(summary) {
    const host = $('#summary-cards');
    if (!host) return;
    host.textContent = '';
    const entries = Object.entries(summary || {});
    if (!entries.length) {
      host.classList.add('d-none');
      return;
    }
    entries.forEach(([k, v]) => {
      const col = document.createElement('div');
      col.className = 'col-xl-2 col-lg-3 col-md-4 col-sm-6';
      const card = document.createElement('div');
      card.className = 'card text-center h-100 shadow-sm summary-card';

      const body = document.createElement('div');
      body.className = 'card-body';

      const keyEl = document.createElement('div');
      keyEl.className = 'text-muted small';
      keyEl.textContent = t(k);

      const valEl = document.createElement('div');
      valEl.className = 'fs-4 fw-bold';
      valEl.textContent = formatVal(v);

      body.appendChild(keyEl);
      body.appendChild(valEl);
      card.appendChild(body);
      col.appendChild(card);
      host.appendChild(col);
    });
    host.classList.remove('d-none');
  }
  function formatVal(v) {
    if (typeof v === 'number' && isFinite(v)) {
      return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return v ?? '—';
  }

  function getReportTitle() {
    const withAttr = document.querySelector('[data-report-title]');
    if (withAttr) {
      const attr = withAttr.getAttribute('data-report-title');
      if (attr) return attr.trim();
    }
    const source =
      document.querySelector('.page-title') ||
      document.querySelector('.content h4') ||
      document.querySelector('h3');
    if (source && source.textContent) return source.textContent.trim();
    return document.title || 'التقرير';
  }

  const PRINT_ROWS_PER_PAGE_DEFAULT = 35;
  let activePrintTable = null;
  let activeRowCount = 0;
  let activeColumns = [];
  let printForm;
  let printModal;

  function collectColumns(table) {
    const row = table.querySelector('thead tr:last-child') || table.querySelector('thead tr') || table.querySelector('tbody tr');
    if (!row) return [];
    return Array.from(row.children).map((cell, idx) => ({
      index: idx,
      label: (cell.textContent || '').trim() || `عمود ${idx + 1}`
    }));
  }

  function populateColumnOptions() {
    const container = $('#printColumnsContainer');
    if (!container) return;
    container.innerHTML = '';
    if (!activeColumns.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted small';
      empty.textContent = 'لا توجد أعمدة متاحة.';
      container.appendChild(empty);
      return;
    }
    const fragment = document.createDocumentFragment();
    activeColumns.forEach((col) => {
      const wrap = document.createElement('div');
      wrap.className = 'custom-control custom-checkbox';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'custom-control-input';
      input.id = `report-print-col-${col.index}`;
      input.name = 'print_columns';
      input.value = String(col.index);
      input.checked = true;
      const label = document.createElement('label');
      label.className = 'custom-control-label';
      label.setAttribute('for', input.id);
      label.textContent = col.label;
      wrap.appendChild(input);
      wrap.appendChild(label);
      fragment.appendChild(wrap);
    });
    container.appendChild(fragment);
  }

  function updatePrintStats() {
    $('#printRowCount').textContent = activeRowCount;
    const pages = Math.max(1, Math.ceil((activeRowCount || 0) / PRINT_ROWS_PER_PAGE_DEFAULT));
    $('#printPageCount').textContent = pages;
    const rowStart = printForm?.querySelector('[name="start_row"]');
    const rowEnd = printForm?.querySelector('[name="end_row"]');
    if (rowStart) rowStart.value = 1;
    if (rowEnd) rowEnd.value = activeRowCount || 1;
    const pageStart = printForm?.querySelector('[name="start_page"]');
    const pageEnd = printForm?.querySelector('[name="end_page"]');
    if (pageStart) pageStart.value = 1;
    if (pageEnd) pageEnd.value = pages;
    const rowsPerPageInput = printForm?.querySelector('[name="rows_per_page"]');
    if (rowsPerPageInput) rowsPerPageInput.value = PRINT_ROWS_PER_PAGE_DEFAULT;
  }

  function updateModeFields(mode) {
    const rowInputs = ['start_row', 'end_row'].map((name) => printForm?.querySelector(`[name="${name}"]`));
    const pageInputs = ['start_page', 'end_page', 'rows_per_page'].map((name) => printForm?.querySelector(`[name="${name}"]`));
    rowInputs.forEach((el) => { if (el) el.disabled = mode !== 'rows'; });
    pageInputs.forEach((el) => { if (el) el.disabled = mode !== 'pages'; });
  }

  function openPrintModal(table) {
    activePrintTable = table;
    activeRowCount = Array.from(table.querySelectorAll('tbody tr')).length;
    activeColumns = collectColumns(table);
    populateColumnOptions();
    updatePrintStats();
    const modeAll = printForm?.querySelector('#printModeAll');
    if (modeAll) modeAll.checked = true;
    updateModeFields('all');
    const orientation = printForm?.querySelector('[name="orientation"]');
    if (orientation) orientation.value = 'portrait';
    if (window.jQuery && typeof window.jQuery.fn?.modal === 'function') {
      const modalInstance = window.jQuery('#reportPrintModal');
      modalInstance.modal({ backdrop: 'static', keyboard: false, show: true });
    } else if (printModal) {
      printModal.classList.add('show');
      printModal.style.display = 'block';
    }
  }

  function applyRowRange(clone, start, end) {
    if (!start || !end) return;
    const rows = Array.from(clone.querySelectorAll('tbody tr'));
    rows.forEach((row, idx) => {
      const position = idx + 1;
      if (position < start || position > end) row.remove();
    });
  }

  function applyColumnFilter(clone, keepSet) {
    if (!keepSet || !keepSet.size) return;
    const rows = Array.from(clone.querySelectorAll('tr'));
    rows.forEach((row) => {
      let cursor = -1;
      Array.from(row.children).forEach((cell) => {
        const span = Number(cell.colSpan || 1);
        for (let i = 0; i < span; i += 1) {
          cursor += 1;
          if (span > 1) continue;
          if (!keepSet.has(cursor)) {
            cell.remove();
            break;
          }
        }
      });
    });
  }

  function sendToPrintWindow(clone, orientation) {
    const title = getReportTitle();
    const stamp = new Date().toLocaleString('ar-EG');
    const orient = orientation === 'landscape' ? 'landscape' : 'portrait';
    const styles = `
@page { size: A4 ${orient}; margin: 12mm; }
* { box-sizing: border-box; }
body { font-family: "Tajawal", "Cairo", "Arial", sans-serif; direction: rtl; padding: 16px; color: #000; }
h3 { margin: 0 0 8px 0; font-size: 18px; }
p { margin: 0 0 16px 0; font-size: 12px; color: #555; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border: 1px solid #333; padding: 6px 8px; text-align: right; vertical-align: middle; }
thead th { background: #f1f1f1; }
tbody tr:nth-child(even) { background: #fafafa; }
    `.trim();
    const win = window.open('about:blank', '_blank', 'width=1000,height=800');
    if (!win) {
      alert('لم يتم فتح نافذة الطباعة. يرجى السماح بالنوافذ المنبثقة أو إعادة المحاولة.');
      return;
    }
    clone.querySelectorAll('script').forEach((node) => node.remove());
    const doc = win.document;
    doc.documentElement.setAttribute('dir', 'rtl');
    doc.documentElement.setAttribute('lang', 'ar');
    doc.title = String(title || '');
    doc.head.textContent = '';
    doc.body.textContent = '';

    const meta = doc.createElement('meta');
    meta.setAttribute('charset', 'utf-8');
    doc.head.appendChild(meta);

    const style = doc.createElement('style');
    style.textContent = styles;
    doc.head.appendChild(style);

    const titleEl = doc.createElement('h3');
    titleEl.textContent = String(title || '');
    doc.body.appendChild(titleEl);

    const stampEl = doc.createElement('p');
    stampEl.textContent = String(stamp || '');
    doc.body.appendChild(stampEl);

    const host = doc.createElement('div');
    host.textContent = '';
    host.appendChild(doc.importNode(clone, true));
    doc.body.appendChild(host);

    let printed = false;
    const doPrint = () => {
      if (printed) return;
      printed = true;
      try { win.focus(); } catch (_) {}
      try { win.print(); } catch (_) {}
    };
    try {
      if (doc.readyState === 'complete') {
        setTimeout(doPrint, 50);
      } else if (typeof win.addEventListener === 'function') {
        win.addEventListener('load', () => setTimeout(doPrint, 50), { once: true });
        setTimeout(doPrint, 400);
      } else {
        setTimeout(doPrint, 50);
      }
    } catch (_) {
      setTimeout(doPrint, 50);
    }
  }

  function handlePrintSubmit(event) {
    event.preventDefault();
    if (!activePrintTable) return;
    const data = new FormData(printForm);
    const mode = data.get('print_mode') || 'all';
    const orientation = data.get('orientation') || 'portrait';
    const selectedColumns = data.getAll('print_columns');
    const keep = selectedColumns.length
      ? new Set(selectedColumns.map((val) => Number(val)))
      : new Set(activeColumns.map((col) => col.index));
    if (!keep.size) {
      alert('يجب اختيار عمود واحد على الأقل للطباعة.');
      return;
    }
    const clone = activePrintTable.cloneNode(true);
    const totalRows = activeRowCount || 0;
    if (mode === 'rows') {
      let start = parseInt(data.get('start_row'), 10) || 1;
      let end = parseInt(data.get('end_row'), 10) || totalRows;
      if (start > end) [start, end] = [end, start];
      applyRowRange(clone, start, end);
    } else if (mode === 'pages') {
      let startPage = parseInt(data.get('start_page'), 10) || 1;
      let endPage = parseInt(data.get('end_page'), 10) || 1;
      if (startPage > endPage) [startPage, endPage] = [endPage, startPage];
      const rowsPerPage = parseInt(data.get('rows_per_page'), 10) || PRINT_ROWS_PER_PAGE_DEFAULT;
      const firstRow = (startPage - 1) * rowsPerPage + 1;
      const lastRow = endPage * rowsPerPage;
      applyRowRange(clone, firstRow, lastRow);
    }
    applyColumnFilter(clone, keep);
    sendToPrintWindow(clone, orientation);
    if (window.jQuery && typeof window.jQuery.fn?.modal === 'function') {
      window.jQuery('#reportPrintModal').modal('hide');
    } else if (printModal) {
      printModal.classList.remove('show');
      printModal.style.display = 'none';
    }
  }

  function setupPrintModal() {
    printForm = document.getElementById('reportPrintForm');
    printModal = document.getElementById('reportPrintModal');
    if (!printForm) return;
    printForm.addEventListener('submit', handlePrintSubmit);
    $$('#reportPrintForm input[name="print_mode"]').forEach((radio) => {
      radio.addEventListener('change', (event) => updateModeFields(event.target.value));
    });
  }

  function setupTablePrint() {
    setupPrintModal();
    const buttons = $$('.report-table-print');
    if (!buttons.length) return;
    let toolbarShown = false;
    buttons.forEach((btn) => {
      const selector = btn.getAttribute('data-table-target') || '#report-table';
      const table = document.querySelector(selector);
      if (!table) return;
      if (!toolbarShown) {
        const toolbar = document.querySelector('.report-table-toolbar');
        if (toolbar) toolbar.style.display = 'flex';
        toolbarShown = true;
      }
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        openPrintModal(table);
      });
    });
  }

  async function refreshForModel(model) {
    const { columns, date_fields } = await fetchModelFields(model);
    const sel = $('#selected_fields');
    const keep = new Set(filterList(Array.from(sel?.selectedOptions || []).map(o => o.value)));
    fillSelectOptions(sel, columns, true);
    if (keep.size) {
      $$('#selected_fields option').forEach(o => { if (keep.has(o.value)) o.selected = true; });
    }
    applyDateFieldOptions($('#date_field'), date_fields);
    buildLikeFilters(columns);
  }

  document.addEventListener('DOMContentLoaded', async () => {
    initDataTable();
    setupTablePrint();
    const state = loadState();
    const f = $('#report-form');
    if (state && f) {
      f.table.value = state.table || f.table.value;
      await refreshForModel(f.table.value);
      $('#date_field').value = state.date_field || $('#date_field').value;
      f.start_date.value = state.start_date || f.start_date.value;
      f.end_date.value = state.end_date || f.end_date.value;
      f.limit.value = state.limit || f.limit.value;
      const sel = $('#selected_fields');
      if (sel && Array.isArray(state.selected_fields) && state.selected_fields.length) {
        const allowed = new Set(filterList(Array.from(sel.options).map(o => o.value)));
        $$('#selected_fields option').forEach(o => { o.selected = state.selected_fields.includes(o.value) && allowed.has(o.value); });
      }
      const wrap = $('#like_filters');
      if (wrap) {
        const iv = state.like_filters || {};
        Object.keys(iv).forEach(k => {
          if (EXCLUDED.includes(k)) return;
          const inp = $(`#like_filters input[name="${CSS.escape(k)}"]`);
          if (inp) inp.value = iv[k];
        });
      }
    } else {
      await refreshForModel($('#table')?.value || window.__selectedTable || '');
    }
    $('#table')?.addEventListener('change', async function () {
      await refreshForModel(this.value);
      saveState();
    });
    $('#report-form')?.addEventListener('submit', (e) => {
      const isCSV = e.submitter && e.submitter.getAttribute('formaction')?.includes('/export/dynamic.csv');
      if (!isCSV) {
        e.preventDefault();
        runDynamicReport();
      } else {
        saveState();
      }
    });
    if (window.__initialData) {
      renderTable(filterList(window.__initialHeaders || []), (window.__initialData || []).map(rec => {
        const o = {};
        filterList(window.__initialHeaders || []).forEach(h => { o[h] = rec[h]; });
        return o;
      }));
      renderSummary(window.__initialSummary || {});
    }
  });
})();

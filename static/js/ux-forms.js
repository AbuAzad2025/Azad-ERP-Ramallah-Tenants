/**
 * تحسين تجربة النماذج: قوائم منسدلة، أزرار، تسميات موحّدة.
 */
(function () {
  'use strict';

  const SAVING_HTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> جاري الحفظ…';

  function initSelect2Unified() {
    if (!window.jQuery || !$.fn.select2) return;
    $('select.form-control:not([data-no-select2])').each(function () {
      const $el = $(this);
      if ($el.data('select2')) return;
      $el.select2({
        dir: 'rtl',
        width: '100%',
        placeholder: $el.attr('placeholder') || '— اختر —',
        allowClear: !$el.prop('required'),
      });
    });
  }

  function normalizeEmptyOptions() {
    document.querySelectorAll('select.form-control').forEach(function (sel) {
      const first = sel.options[0];
      if (!first) return;
      const t = (first.textContent || '').trim();
      if (t === '' || t === 'اختر' || t === 'اختر...' || t === '—') {
        first.textContent = '— اختر —';
        first.value = first.value || '';
      }
    });
  }

  function isHiddenForm(form) {
    if (form.hidden) return true;
    const st = (form.getAttribute('style') || '').replace(/\s/g, '');
    if (st.includes('display:none') || st.includes('display:none;')) return true;
    if (form.classList.contains('d-none') || form.offsetParent === null) return true;
    return false;
  }

  function isInlineDeleteForm(form) {
    const onsubmit = form.getAttribute('onsubmit') || '';
    if (!onsubmit.includes('confirm')) return false;
    const inline =
      form.classList.contains('d-inline') ||
      (form.getAttribute('style') || '').includes('inline');
    const submits = form.querySelectorAll(
      'button[type="submit"], input[type="submit"], button:not([type])'
    );
    return inline && submits.length <= 1;
  }

  function shouldAutoUxSubmit(form) {
    if (form.dataset.noUxSubmit !== undefined) return false;
    if (form.dataset.uxSubmit !== undefined) return false;
    if (isHiddenForm(form)) return false;
    if (isInlineDeleteForm(form)) return false;
    const method = (form.getAttribute('method') || 'get').toLowerCase();
    if (method !== 'post') return false;
    const hasSubmit = form.querySelector(
      'button[type="submit"], input[type="submit"], button.btn-primary, button.btn-success'
    );
    if (!hasSubmit) return false;
    if (
      form.classList.contains('needs-validation') ||
      form.id && /form$/i.test(form.id) ||
      form.id && /Form$/.test(form.id) ||
      form.querySelector('.card-body')
    ) {
      return true;
    }
    return form.querySelectorAll('input, select, textarea').length >= 2;
  }

  function autoMarkSubmitForms() {
    document.querySelectorAll('form').forEach(function (form) {
      if (shouldAutoUxSubmit(form)) {
        form.setAttribute('data-ux-submit', '1');
      }
    });
  }

  function bindSubmitLoading() {
    document.querySelectorAll('form[data-ux-submit]').forEach(function (form) {
      if (form.dataset.uxBound) return;
      form.dataset.uxBound = '1';
      form.addEventListener('submit', function () {
        const btn =
          form.querySelector('[type="submit"]') ||
          form.querySelector('button.btn-primary, button.btn-success');
        if (!btn || btn.disabled) return;
        btn.dataset.uxOrig = btn.innerHTML;
        btn.disabled = true;
        btn.setAttribute('aria-busy', 'true');
        btn.innerHTML = SAVING_HTML;
      });
    });
  }

  function init() {
    normalizeEmptyOptions();
    autoMarkSubmitForms();
    initSelect2Unified();
    bindSubmitLoading();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

/**
 * رسائل موحّدة — toasts، flashes، AJAX، أخطاء JS
 * واضحة، بلا مبالغة، بلا تكرار مزعج
 */
(function () {
  'use strict';

  const TITLES = {
    success: 'تم بنجاح',
    danger: 'تعذّر الإكمال',
    error: 'تعذّر الإكمال',
    warning: 'تنبيه',
    info: 'معلومة',
  };

  const ICONS = {
    success: 'fa-check-circle',
    danger: 'fa-times-circle',
    error: 'fa-times-circle',
    warning: 'fa-exclamation-triangle',
    info: 'fa-info-circle',
  };

  const ALIASES = {
    'حدث خطأ داخلي': 'internal_error',
    'حدث خطأ': 'internal_error',
    'حدث خطأ غير متوقع': 'internal_error',
    'حدث خطأ غير متوقع!': 'internal_error',
    'internal server error': 'internal_error',
    'bad request': 'validation_error',
    unauthorized: 'session_expired',
    'not found': 'not_found',
    'غير مصرح لك بهذا الإجراء': 'permission_denied',
  };

  const DEFAULTS = {
    internal_error:
      'تعذّر إكمال العملية. تحقق من البيانات وحاول مجدداً، أو تواصل مع مسؤول النظام إن استمر الخطأ.',
    validation_error: 'يرجى مراجعة الحقول المظلّلة وتصحيحها قبل المتابعة.',
    required_fields: 'يرجى تعبئة جميع الحقول المطلوبة (*).',
    permission_denied: 'ليس لديك صلاحية تنفيذ هذا الإجراء. اطلب الصلاحية من المسؤول.',
    not_found: 'العنصر المطلوب غير موجود أو ربما تم حذفه.',
    network_error: 'تعذّر الاتصال بالخادم. تحقق من الشبكة وحاول مرة أخرى.',
    session_expired: 'انتهت الجلسة. سجّل الدخول مجدداً للمتابعة.',
    saved: 'تم حفظ البيانات بنجاح.',
  };

  const UX_MSG = Object.assign({}, DEFAULTS, window.UX_MSG || {});

  const recentToasts = new Map();
  const DEDUPE_MS = 5000;

  function normalizeType(type) {
    const t = String(type || 'info').toLowerCase();
    if (t === 'error' || t === 'fail' || t === 'failed' || t === 'danger') return 'danger';
    if (t === 'warn' || t === 'alert') return 'warning';
    return ['success', 'warning', 'info', 'danger'].includes(t) ? t : 'info';
  }

  function stripEmoji(text) {
    return String(text || '')
      .replace(/^[\s✅❌⚠️ℹ️🔴🟢🟡🔵⭐📌💡]+/, '')
      .replace(/[\u2705\u274c\u26a0\ufe0f\u2139\ufe0f]/g, '')
      .replace(/\s{2,}/g, ' ')
      .trim();
  }

  function fromKey(key) {
    if (!key) return '';
    return UX_MSG[key] || DEFAULTS[key] || '';
  }

  function humanize(text, options) {
    options = options || {};
    if (options.key) {
      const k = fromKey(options.key);
      if (k) return k;
    }
    const t = stripEmoji(text);
    if (!t) {
      return fromKey(options.defaultKey) || DEFAULTS.internal_error;
    }
    const low = t.toLowerCase();
    if (ALIASES[t] || ALIASES[low]) {
      return fromKey(ALIASES[t] || ALIASES[low]);
    }
    if (t === 'حدث خطأ داخلي' || t === 'حدث خطأ' || low === 'internal server error') {
      return DEFAULTS.internal_error;
    }
    return t;
  }

  function shouldSkip(text, type) {
    const key = normalizeType(type) + '|' + humanize(text);
    const now = Date.now();
    const last = recentToasts.get(key);
    if (last && now - last < DEDUPE_MS) {
      return true;
    }
    recentToasts.set(key, now);
    return false;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function ensureToastHost() {
    let host = document.getElementById('ux-toast-host');
    if (host) return host;
    host = document.createElement('div');
    host.id = 'ux-toast-host';
    host.className = 'ux-toast-host';
    host.setAttribute('aria-live', 'polite');
    host.setAttribute('aria-relevant', 'additions');
    document.body.appendChild(host);
    return host;
  }

  function notify(type, message, options) {
    options = options || {};
    const cat = normalizeType(type);
    const body = humanize(message, {
      key: options.key,
      defaultKey: options.defaultKey || (cat === 'danger' ? 'internal_error' : ''),
    });
    if (!body) return;
    if (!options.force && shouldSkip(body, cat)) return;

    const title = options.title || TITLES[cat] || 'إشعار';
    const duration =
      options.duration != null
        ? options.duration
        : cat === 'success'
          ? 5500
          : cat === 'info'
            ? 6000
            : cat === 'warning'
              ? 9000
              : 0;

    if (typeof Swal !== 'undefined' && options.modal) {
      Swal.fire({
        title: title,
        text: body,
        icon: cat === 'danger' ? 'error' : cat,
        confirmButtonText: options.confirmText || 'حسناً',
      });
      return;
    }

    if (typeof toastr !== 'undefined' && !options.inline) {
      const method = cat === 'danger' ? 'error' : cat;
      toastr.options = Object.assign(
        {
          closeButton: true,
          progressBar: true,
          positionClass: 'toast-top-left',
          timeOut: duration || (cat === 'danger' ? 0 : 8000),
          extendedTimeOut: 2000,
          rtl: true,
          preventDuplicates: true,
        },
        options.toastr || {}
      );
      toastr[method](body, title);
      return;
    }

    const host = ensureToastHost();
    const existing = host.querySelectorAll('.ux-toast');
    if (existing.length >= 4) {
      existing[0].remove();
    }

    const toast = document.createElement('div');
    toast.className = 'ux-toast ux-toast--' + cat;
    toast.setAttribute('role', 'status');
    toast.innerHTML =
      '<div class="ux-toast__icon"><i class="fas ' +
      (ICONS[cat] || 'fa-info-circle') +
      '" aria-hidden="true"></i></div>' +
      '<div class="ux-toast__content">' +
      '<strong class="ux-toast__title">' +
      escapeHtml(title) +
      '</strong>' +
      '<p class="ux-toast__text">' +
      escapeHtml(body) +
      '</p></div>' +
      '<button type="button" class="ux-toast__close" aria-label="إغلاق">&times;</button>';
    host.appendChild(toast);
    requestAnimationFrame(function () {
      toast.classList.add('ux-toast--visible');
    });
    toast.querySelector('.ux-toast__close').addEventListener('click', function () {
      toast.classList.remove('ux-toast--visible');
      setTimeout(function () {
        toast.remove();
      }, 250);
    });
    if (duration > 0) {
      setTimeout(function () {
        if (toast.parentNode) {
          toast.classList.remove('ux-toast--visible');
          setTimeout(function () {
            toast.remove();
          }, 250);
        }
      }, duration);
    }
  }

  function parseJsonMessage(data) {
    if (!data || typeof data !== 'object') return null;
    if (data.key && fromKey(data.key)) return fromKey(data.key);
    const raw = data.message || data.error || data.detail || data.msg;
    if (raw) return humanize(raw);
    if (data.errors && typeof data.errors === 'object') {
      const first = Object.values(data.errors)[0];
      if (Array.isArray(first) && first[0]) return humanize(first[0]);
      if (typeof first === 'string') return humanize(first);
    }
    return null;
  }

  async function extractResponseMessage(res) {
    try {
      const ct = (res.headers && res.headers.get('content-type')) || '';
      if (ct.indexOf('application/json') >= 0) {
        const data = await res.clone().json();
        return parseJsonMessage(data);
      }
      const text = await res.clone().text();
      if (text && text.length < 500) return humanize(text);
    } catch (_) {}
    return null;
  }

  function statusToType(status) {
    if (status === 401 || status === 403) return 'warning';
    if (status === 404) return 'warning';
    if (status === 422 || status === 400) return 'warning';
    if (status >= 500) return 'danger';
    return 'danger';
  }

  function defaultKeyForStatus(status) {
    if (status === 401) return 'session_expired';
    if (status === 403) return 'permission_denied';
    if (status === 404) return 'not_found';
    if (status === 422 || status === 400) return 'validation_error';
    if (status >= 500) return 'internal_error';
    return 'internal_error';
  }

  function handleHttpError(res, parsedMessage) {
    const status = res.status;
    const body =
      parsedMessage ||
      humanize(null, { defaultKey: defaultKeyForStatus(status), key: defaultKeyForStatus(status) });
    notify(statusToType(status), body, { force: true });
  }

  function enhanceInlineFlashes() {
    const stack = document.querySelector('.ux-flash-stack');
    if (stack && stack.querySelector('.ux-flash')) {
      stack.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    document.querySelectorAll('.ux-flash-stack .ux-flash').forEach(function (el) {
      const cat = el.dataset.category || 'info';
      if (cat === 'success' || cat === 'info') {
        setTimeout(function () {
          if (!el.classList.contains('ux-flash--dismissed')) {
            el.classList.add('ux-flash--fade');
            setTimeout(function () {
              el.remove();
            }, 400);
          }
        }, 10000);
      }
    });
  }

  function enhanceFormValidation() {
    document.querySelectorAll('form.needs-validation, form[data-ux-validate]').forEach(function (form) {
      if (form.dataset.uxValidateBound) return;
      form.dataset.uxValidateBound = '1';
      form.addEventListener(
        'invalid',
        function (ev) {
          const el = ev.target;
          if (!el || !el.setCustomValidity) return;
          if (el.validity.valueMissing) {
            el.setCustomValidity('هذا الحقل مطلوب.');
          } else if (el.validity.typeMismatch) {
            el.setCustomValidity('الصيغة غير صحيحة.');
          } else if (el.validity.rangeUnderflow || el.validity.rangeOverflow) {
            el.setCustomValidity('القيمة خارج النطاق المسموح.');
          }
        },
        true
      );
      form.addEventListener(
        'input',
        function (ev) {
          const el = ev.target;
          if (el && el.setCustomValidity) el.setCustomValidity('');
        },
        true
      );
      form.addEventListener(
        'submit',
        function (ev) {
          if (!form.checkValidity()) {
            ev.preventDefault();
            ev.stopPropagation();
            const firstInvalid = form.querySelector(':invalid');
            if (firstInvalid) {
              firstInvalid.focus({ preventScroll: false });
              firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            notify('warning', null, { key: 'validation_error', inline: true });
          }
          form.classList.add('was-validated');
        },
        false
      );
    });
  }

  function patchFetchErrors() {
    if (window.__UX_FETCH_PATCHED__) return;
    window.__UX_FETCH_PATCHED__ = true;
    const orig = window.fetch;
    if (typeof orig !== 'function') return;
    window.fetch = function () {
      const opts = arguments[1] || {};
      if (opts.uxFeedback === false) {
        return orig.apply(this, arguments);
      }
      const forceUx = opts.uxFeedback === true;
      return orig.apply(this, arguments).then(async function (res) {
        if (res.ok) return res;
        const autoUx =
          forceUx || res.status >= 500 || res.status === 401 || res.status === 403;
        if (!autoUx) return res;
        const parsed = await extractResponseMessage(res);
        handleHttpError(res, parsed);
        return res;
      });
    };
  }

  function patchJqueryAjax() {
    if (!window.jQuery || window.__UX_JQ_PATCHED__) return;
    window.__UX_JQ_PATCHED__ = true;
    jQuery(document).ajaxError(function (_ev, xhr, settings) {
      if (settings && settings.uxFeedback === false) return;
      if (!xhr || xhr.status === 0) {
        notify('warning', null, { key: 'network_error', force: true });
        return;
      }
      let parsed = null;
      try {
        parsed = parseJsonMessage(xhr.responseJSON);
      } catch (_) {}
      handleHttpError({ status: xhr.status }, parsed);
    });
  }

  function setupGlobalErrorHandlers() {
    window.addEventListener('unhandledrejection', function (event) {
      const reason = event.reason;
      const message = reason && (reason.message || String(reason));
      if (!message) return;
      if (/ResizeObserver|Non-Error promise rejection|Loading chunk/i.test(message)) return;
      if (/fetch|network|Failed to fetch|NetworkError/i.test(message)) {
        notify('warning', null, { key: 'network_error', force: true });
        event.preventDefault();
        return;
      }
      notify('danger', message, { defaultKey: 'internal_error', force: true });
    });

    window.addEventListener('error', function (event) {
      if (!event.message || /Script error/i.test(event.message)) return;
      if (/ResizeObserver/i.test(event.message)) return;
    });
  }

  function patchJsonForms() {
    document.querySelectorAll('form[data-ux-json]').forEach(function (form) {
      if (form.dataset.uxJsonBound) return;
      form.dataset.uxJsonBound = '1';
      form.addEventListener('submit', async function (ev) {
        if (form.dataset.uxJsonSubmitting === '1') return;
        const action = form.getAttribute('action');
        if (!action) return;
        ev.preventDefault();
        form.dataset.uxJsonSubmitting = '1';
        try {
          const res = await fetch(action, {
            method: (form.method || 'POST').toUpperCase(),
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin',
          });
          const data = await res.json().catch(function () {
            return {};
          });
          if (res.ok && data.success !== false) {
            notify('success', data.message || null, { key: data.key || 'saved', force: true });
            if (data.redirect) window.location.href = data.redirect;
            else if (data.reload) window.location.reload();
          } else {
            const msg = parseJsonMessage(data) || humanize(data.message || data.error);
            notify(statusToType(res.status), msg, { force: true });
          }
        } catch (e) {
          notify('warning', null, { key: 'network_error', force: true });
        } finally {
          form.dataset.uxJsonSubmitting = '0';
        }
      });
    });
  }

  window.AzadUX = window.AzadUX || {};
  window.AzadUX.notify = notify;
  window.AzadUX.humanize = humanize;
  window.uxNotify = function (type, message, options) {
    notify(type || 'info', message, options || {});
  };
  window.showToast = function (message, type, options) {
    notify(type || 'info', message, options || {});
  };

  function init() {
    enhanceInlineFlashes();
    enhanceFormValidation();
    patchFetchErrors();
    patchJqueryAjax();
    setupGlobalErrorHandlers();
    patchJsonForms();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

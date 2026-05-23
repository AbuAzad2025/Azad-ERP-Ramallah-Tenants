/**
 * صلاحيات الواجهة — تُحمَّل من window.GM_AUTH (يُحقَن من القالب، مع توسيع المرادفات من الخادم).
 */
(function (global) {
  'use strict';

  if (global.GMPermissions && global.GMPermissions.__ready) {
    return;
  }

  var DEFAULT_MSG = 'ليس لديك صلاحية لهذا الإجراء.';

  /** مرادفات محلية (احتياط إذا لم يُوسَّع GM_AUTH من الخادم) */
  var LOCAL_ALIASES = {
    archive_sale: ['archive_sale', 'manage_sales'],
    manage_checks: ['manage_checks', 'manage_payments'],
    manage_payments: ['manage_payments', 'manage_checks'],
    view_payments: ['view_payments', 'manage_payments']
  };

  function norm(code) {
    return String(code || '').trim().toLowerCase();
  }

  function readAuth() {
    var a = global.GM_AUTH;
    if (!a || typeof a !== 'object') {
      return { super: false, perms: [], msg: DEFAULT_MSG };
    }
    return a;
  }

  function permSet() {
    var a = readAuth();
    if (a._set instanceof Set) return a._set;
    var s = new Set();
    (a.perms || []).forEach(function (p) {
      var n = norm(p);
      if (n) s.add(n);
    });
    a._set = s;
    return s;
  }

  function codesFor(code) {
    var key = norm(code);
    var list = LOCAL_ALIASES[key] || [key];
    return list.map(norm);
  }

  function isSuper() {
    return !!readAuth().super;
  }

  function has(code) {
    if (isSuper()) return true;
    var s = permSet();
    var codes = codesFor(code);
    for (var i = 0; i < codes.length; i++) {
      if (s.has(codes[i])) return true;
    }
    return false;
  }

  function hasAny() {
    if (isSuper()) return true;
    for (var i = 0; i < arguments.length; i++) {
      if (has(arguments[i])) return true;
    }
    return false;
  }

  function forbiddenMessage() {
    var a = readAuth();
    return a.msg || DEFAULT_MSG;
  }

  function notifyForbidden(customMsg) {
    var msg = customMsg || forbiddenMessage();
    if (global.toastr) {
      global.toastr.warning(msg, 'صلاحيات');
    } else if (typeof global.showToast === 'function') {
      global.showToast(msg, 'warning');
    } else {
      global.alert(msg);
    }
  }

  function requirePerm(code, customMsg) {
    if (has(code)) return true;
    notifyForbidden(customMsg);
    return false;
  }

  function requireAny() {
    var args = Array.prototype.slice.call(arguments);
    var customMsg = null;
    if (args.length > 1) {
      var last = args[args.length - 1];
      if (typeof last === 'string' && (last.indexOf(' ') >= 0 || last.length > 48)) {
        customMsg = args.pop();
      }
    }
    if (hasAny.apply(null, args)) return true;
    notifyForbidden(customMsg);
    return false;
  }

  var WRITE_URL_PERM = [
    { re: /\/sales\/(?:archive|restore)/i, any: ['manage_sales', 'archive_sale'] },
    { re: /\/customers\/(?:archive|restore)/i, perm: 'manage_customers' },
    { re: /\/payments\/(?:archive|restore|refund|split\/)/i, perm: 'manage_payments' },
    { re: /\/service\/(?:archive|restore)/i, perm: 'manage_service' },
    { re: /\/expenses\/(?:archive|restore)/i, perm: 'manage_expenses' },
    { re: /\/shipments\/(?:archive|restore)/i, perm: 'manage_shipments' },
    { re: /\/checks\/(?:archive|restore)/i, perm: 'manage_payments' },
    { re: /\/checks\/api\//i, perm: 'manage_payments' },
    { re: /\/vendors\/(?:suppliers|partners)\/(?:archive|restore)/i, perm: 'manage_vendors' },
    { re: /\/notes\/(?:delete|toggle|create|update)/i, perm: 'manage_notes' },
    { re: /\/security\/api\/users\/bulk/i, perm: 'manage_users' },
    { re: /\/ledger\/.*(?:manual|post|create|delete)/i, perm: 'manage_ledger' },
    { re: /\/recurring\/delete/i, perm: 'access_owner_dashboard' },
    { re: /\/shop\/admin\//i, perm: 'manage_shop' },
    { re: /\/reports\/api\/dynamic/i, any: ['view_reports', 'manage_reports'] },
    { re: /\/vendors\/.*(?:pay|payment|quick)/i, perm: 'manage_vendors' },
    { re: /\/warehouses\/(?:api\/|transfer|adjust)/i, any: ['manage_warehouses', 'manage_inventory'] },
    { re: /\/customers\/(?:create|edit|archive)/i, perm: 'manage_customers' }
  ];

  function matchWriteUrl(url) {
    var u = String(url || '');
    for (var i = 0; i < WRITE_URL_PERM.length; i++) {
      var rule = WRITE_URL_PERM[i];
      if (!rule.re.test(u)) continue;
      if (rule.any) return { any: rule.any };
      return { perm: rule.perm };
    }
    return null;
  }

  function permForUrl(url) {
    var m = matchWriteUrl(url);
    if (!m) return null;
    return m.perm || (m.any && m.any[0]) || null;
  }

  function requireUrl(url, customMsg) {
    var m = matchWriteUrl(url);
    if (!m) return true;
    if (m.any) return requireAny.apply(null, m.any.concat(customMsg ? [customMsg] : []));
    return requirePerm(m.perm, customMsg);
  }

  var GLOBAL_ACTION_PERMS = {
    archiveExpense: 'manage_expenses',
    restoreExpense: 'manage_expenses',
    archiveSupplier: 'manage_vendors',
    restoreSupplier: 'manage_vendors',
    archivePartner: 'manage_vendors',
    restorePartner: 'manage_vendors',
    archiveSale: ['manage_sales', 'archive_sale'],
    restoreSale: ['manage_sales', 'archive_sale'],
    archiveCustomer: 'manage_customers',
    restoreCustomer: 'manage_customers',
    archivePayment: 'manage_payments',
    restorePayment: 'manage_payments',
    archiveShipment: 'manage_shipments',
    restoreShipment: 'manage_shipments',
    archiveCheck: 'manage_payments',
    restoreCheck: 'manage_payments',
    archiveService: 'manage_service',
    restoreService: 'manage_service',
    bulkActivateUsers: 'manage_users',
    bulkDeactivateUsers: 'manage_users',
    bulkDeleteUsers: 'manage_users'
  };

  function requireActionPerm(spec) {
    if (Array.isArray(spec)) return requireAny.apply(null, spec);
    return requirePerm(spec);
  }

  function wrapGlobalActions() {
    Object.keys(GLOBAL_ACTION_PERMS).forEach(function (name) {
      var spec = GLOBAL_ACTION_PERMS[name];
      var orig = global[name];
      if (typeof orig !== 'function' || orig.__gmPermWrapped) return;
      var wrapped = function () {
        if (!requireActionPerm(spec)) return;
        return orig.apply(this, arguments);
      };
      wrapped.__gmPermWrapped = true;
      global[name] = wrapped;
    });
  }

  function applyDomGuards(root) {
    root = root || document;
    if (!root || !root.querySelectorAll) return;

    root.querySelectorAll('[data-gm-perm]').forEach(function (el) {
      var need = el.getAttribute('data-gm-perm');
      if (!need || has(need)) return;
      el.style.display = 'none';
      el.setAttribute('aria-hidden', 'true');
      el.setAttribute('data-gm-denied', '1');
    });

    root.querySelectorAll('[data-gm-perm-any]').forEach(function (el) {
      var raw = el.getAttribute('data-gm-perm-any') || '';
      var list = raw.split(/[\s,|]+/).filter(Boolean);
      if (!list.length || hasAny.apply(null, list)) return;
      el.style.display = 'none';
      el.setAttribute('aria-hidden', 'true');
      el.setAttribute('data-gm-denied', '1');
    });

    root.querySelectorAll('[data-gm-disable-without]').forEach(function (el) {
      var need = el.getAttribute('data-gm-disable-without');
      if (!need || has(need)) return;
      el.classList.add('disabled');
      el.setAttribute('aria-disabled', 'true');
      if (el.tagName === 'BUTTON' || el.tagName === 'INPUT') {
        el.disabled = true;
      }
    });
  }

  function bindDelegatedGuards() {
    document.body.addEventListener(
      'click',
      function (e) {
        var el = e.target.closest('[data-gm-require-perm]');
        if (!el) return;
        var need = el.getAttribute('data-gm-require-perm');
        var needAny = el.getAttribute('data-gm-require-perm-any');
        if (needAny) {
          var parts = needAny.split(/[\s,|]+/).filter(Boolean);
          if (parts.length && hasAny.apply(null, parts)) return;
        } else if (!need || has(need)) {
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        notifyForbidden();
      },
      true
    );

    document.body.addEventListener(
      'click',
      function (e) {
        var btn = e.target.closest('.archive-btn, .restore-btn');
        if (!btn) return;
        var url = btn.dataset.archiveUrl || btn.dataset.restoreUrl || '';
        var explicit = btn.getAttribute('data-gm-perm');
        var explicitAny = btn.getAttribute('data-gm-perm-any');
        if (explicitAny) {
          var parts = explicitAny.split(/[\s,|]+/).filter(Boolean);
          if (parts.length && !hasAny.apply(null, parts)) {
            e.preventDefault();
            e.stopImmediatePropagation();
            notifyForbidden();
          }
          return;
        }
        if (explicit && !has(explicit)) {
          e.preventDefault();
          e.stopImmediatePropagation();
          notifyForbidden();
          return;
        }
        if (!requireUrl(url)) {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
      },
      true
    );
  }

  function patchFetch() {
    var orig = global.fetch;
    if (!orig || orig.__gmPermPatched) return;
    function wrappedFetch(input, init) {
      init = init || {};
      var method = String(init.method || 'GET').toUpperCase();
      if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        if (url && !requireUrl(url)) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ error: forbiddenMessage(), message: forbiddenMessage() }),
              { status: 403, headers: { 'Content-Type': 'application/json' } }
            )
          );
        }
      }
      return orig.apply(this, arguments);
    }
    wrappedFetch.__gmPermPatched = true;
    global.fetch = wrappedFetch;
  }

  function patchJqueryAjax() {
    if (!global.jQuery) return;
    var $ = global.jQuery;
    if ($.__gmPermAjaxPatched) return;
    $.ajaxPrefilter(function (options) {
      var method = String(options.type || options.method || 'GET').toUpperCase();
      if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') return;
      var url = options.url || '';
      if (!url || requireUrl(url)) return;
      options.beforeSend = function () {
        notifyForbidden();
        return false;
      };
    });
    $.__gmPermAjaxPatched = true;
  }

  function init() {
    wrapGlobalActions();
    applyDomGuards(document);
    bindDelegatedGuards();
    patchFetch();
    patchJqueryAjax();
  }

  var api = {
    __ready: true,
    has: has,
    hasAny: hasAny,
    require: requirePerm,
    requireAny: requireAny,
    requireUrl: requireUrl,
    permForUrl: permForUrl,
    notifyForbidden: notifyForbidden,
    applyDomGuards: applyDomGuards,
    wrapGlobalActions: wrapGlobalActions,
    init: init,
    GLOBAL_ACTION_PERMS: GLOBAL_ACTION_PERMS
  };

  global.GMPermissions = api;
  global.gmHas = has;
  global.gmHasAny = hasAny;
  global.gmRequirePerm = requirePerm;
  global.gmRequirePermAny = requireAny;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  global.addEventListener('load', function () {
    wrapGlobalActions();
    applyDomGuards(document);
    patchJqueryAjax();
  });
})(typeof window !== 'undefined' ? window : this);

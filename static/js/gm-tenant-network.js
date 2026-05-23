/**
 * توحيد كل مسارات الشبكة والتنقل تحت بادئة التينانت /t/<slug>/.
 * يُحمَّل من base.html بعد jQuery مباشرة.
 */
(function (global) {
  'use strict';

  if (global.__GM_TENANT_NETWORK__) return;
  global.__GM_TENANT_NETWORK__ = true;

  var PREFIX = function () {
    return global.GM_PREFIX || '';
  };

  function gmPath(p) {
    if (typeof global.gmPath === 'function' && global.gmPath !== gmPath) {
      return global.gmPath(p);
    }
    if (!p) return PREFIX() || '/';
    if (/^https?:\/\//i.test(p)) return p;
    var path = p.charAt(0) === '/' ? p : '/' + p;
    if (path.indexOf('/static/') === 0) return path;
    return PREFIX() + path;
  }

  global.gmPath = global.gmPath || gmPath;
  global.gmU = gmPath;

  function rewriteUrl(url) {
    if (url == null) return url;
    if (typeof url !== 'string') return url;
    var u = url.trim();
    if (!u || /^https?:\/\//i.test(u) || u.indexOf('//') === 0) return u;
    if (u.charAt(0) === '/' && u.indexOf('/static/') !== 0) {
      var fixed = gmPath(u);
      return fixed;
    }
    return u;
  }

  global.gmRewriteUrl = rewriteUrl;

  function patchFetch() {
    var orig = global.fetch;
    if (!orig || orig.__gmTenantFetchPatched) return;
    global.fetch = function (input, init) {
      if (typeof input === 'string') {
        input = rewriteUrl(input);
      } else if (input && typeof Request !== 'undefined' && input instanceof Request) {
        var reqUrl = input.url;
        var next = rewriteUrl(reqUrl);
        if (next !== reqUrl) input = new Request(next, input);
      }
      return orig.call(this, input, init);
    };
    global.fetch.__gmTenantFetchPatched = true;
  }

  function patchXHR() {
    if (!global.XMLHttpRequest || global.XMLHttpRequest.__gmTenantPatched) return;
    var origOpen = global.XMLHttpRequest.prototype.open;
    global.XMLHttpRequest.prototype.open = function (method, url) {
      var args = Array.prototype.slice.call(arguments);
      if (typeof url === 'string') args[1] = rewriteUrl(url);
      return origOpen.apply(this, args);
    };
    global.XMLHttpRequest.__gmTenantPatched = true;
  }

  function patchLocation() {
    if (!global.Location || global.Location.__gmTenantPatched) return;
    ['assign', 'replace'].forEach(function (name) {
      var orig = global.Location.prototype[name];
      if (typeof orig !== 'function') return;
      global.Location.prototype[name] = function (url) {
        return orig.call(this, rewriteUrl(String(url || '')));
      };
    });
    try {
      var desc = Object.getOwnPropertyDescriptor(global.Location.prototype, 'href');
      if (desc && typeof desc.set === 'function' && !desc.__gmPatched) {
        Object.defineProperty(global.Location.prototype, 'href', {
          configurable: true,
          enumerable: desc.enumerable,
          get: desc.get,
          set: function (v) {
            desc.set.call(this, rewriteUrl(String(v || '')));
          }
        });
        desc.__gmPatched = true;
      }
    } catch (_) {}
    global.Location.__gmTenantPatched = true;
  }

  function patchWindowOpen() {
    var orig = global.open;
    if (!orig || orig.__gmTenantPatched) return;
    global.open = function (url) {
      var args = Array.prototype.slice.call(arguments);
      if (typeof args[0] === 'string') args[0] = rewriteUrl(args[0]);
      return orig.apply(this, args);
    };
    global.open.__gmTenantPatched = true;
  }

  function patchJQuery() {
    if (!global.jQuery) return false;
    var $ = global.jQuery;
    if ($.__gmTenantNetworkPatched) return true;

    $.ajaxPrefilter(function (options) {
      if (options && options.url) options.url = rewriteUrl(options.url);
    });

    ['get', 'post', 'getJSON'].forEach(function (name) {
      var orig = $[name];
      if (typeof orig !== 'function') return;
      $[name] = function (url) {
        var args = Array.prototype.slice.call(arguments);
        if (typeof url === 'string') args[0] = rewriteUrl(url);
        return orig.apply(this, args);
      };
    });

    var origAjax = $.ajax;
    $.ajax = function (url, options) {
      if (typeof url === 'object') {
        options = url;
        url = undefined;
      }
      options = options || {};
      if (url) options.url = rewriteUrl(url);
      else if (options.url) options.url = rewriteUrl(options.url);
      return origAjax.call(this, options);
    };

    if ($.fn && $.fn.load) {
      var origLoad = $.fn.load;
      $.fn.load = function (url) {
        var args = Array.prototype.slice.call(arguments);
        if (typeof args[0] === 'string') args[0] = rewriteUrl(args[0]);
        return origLoad.apply(this, args);
      };
    }

    $__gmTenantNetworkPatched = true;
    return true;
  }

  function patchFormActionSetter() {
    try {
      var proto = global.HTMLFormElement && global.HTMLFormElement.prototype;
      if (!proto || proto.__gmActionPatched) return;
      var desc = Object.getOwnPropertyDescriptor(proto, 'action');
      if (!desc || typeof desc.set !== 'function') return;
      Object.defineProperty(proto, 'action', {
        configurable: desc.configurable,
        enumerable: desc.enumerable,
        get: desc.get,
        set: function (v) {
          desc.set.call(this, rewriteUrl(String(v || '')));
        }
      });
      proto.__gmActionPatched = true;
    } catch (_) {}
  }

  function fixAnchors(root) {
    root = root || document;
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('a[href^="/"]').forEach(function (a) {
      var raw = a.getAttribute('href');
      if (!raw || raw.indexOf('/static/') === 0) return;
      var fixed = rewriteUrl(raw);
      if (fixed !== raw) a.setAttribute('href', fixed);
    });
    root.querySelectorAll('form[action^="/"]').forEach(function (f) {
      var raw = f.getAttribute('action');
      if (!raw || raw.indexOf('/static/') === 0) return;
      var fixed = rewriteUrl(raw);
      if (fixed !== raw) f.setAttribute('action', fixed);
    });
  }

  function bindNavigationGuards() {
    document.addEventListener(
      'click',
      function (e) {
        var a = e.target.closest('a[href^="/"]');
        if (!a) return;
        var raw = a.getAttribute('href');
        if (!raw || raw.indexOf('/static/') === 0) return;
        var fixed = rewriteUrl(raw);
        if (fixed !== raw) a.setAttribute('href', fixed);
      },
      true
    );
    document.addEventListener(
      'submit',
      function (e) {
        var form = e.target;
        if (!form || form.tagName !== 'FORM') return;
        var raw = form.getAttribute('action');
        if (!raw || raw.charAt(0) !== '/' || raw.indexOf('/static/') === 0) return;
        var fixed = rewriteUrl(raw);
        if (fixed !== raw) form.setAttribute('action', fixed);
      },
      true
    );
  }

  function initDom() {
    fixAnchors(document);
    bindNavigationGuards();
  }

  patchFetch();
  patchXHR();
  patchLocation();
  patchWindowOpen();
  patchFormActionSetter();

  if (!patchJQuery()) {
    document.addEventListener('DOMContentLoaded', patchJQuery);
    global.addEventListener('load', patchJQuery);
  }

  global.gmFetch = function (url, init) {
    return global.fetch(rewriteUrl(url), init);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDom);
  } else {
    initDom();
  }
  global.addEventListener('load', function () {
    patchJQuery();
    fixAnchors(document);
  });

  if (typeof MutationObserver !== 'undefined') {
    var moTimer;
    var mo = new MutationObserver(function () {
      clearTimeout(moTimer);
      moTimer = setTimeout(function () {
        fixAnchors(document);
      }, 80);
    });
    function startObserve() {
      if (!document.body) return;
      mo.observe(document.body, { childList: true, subtree: true });
    }
    if (document.body) startObserve();
    else document.addEventListener('DOMContentLoaded', startObserve);
  }
})();

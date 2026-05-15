(function () {
  'use strict';

  function ensureContainer() {
    var container = document.getElementById('ai-transaction-toast-container');
    if (container) return container;
    container = document.createElement('div');
    container.id = 'ai-transaction-toast-container';
    container.style.position = 'fixed';
    container.style.top = '80px';
    container.style.left = '20px';
    container.style.right = 'auto';
    container.style.zIndex = '20000';
    container.style.maxWidth = '420px';
    container.style.direction = 'rtl';
    document.body.appendChild(container);
    return container;
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function showAiTransactionMessage(message, level) {
    if (!message) return;
    var container = ensureContainer();
    var alertClass = level === 'danger' ? 'alert-danger' : (level === 'warning' ? 'alert-warning' : 'alert-info');
    var div = document.createElement('div');
    div.className = 'alert ' + alertClass + ' alert-dismissible fade show shadow';
    div.setAttribute('role', 'alert');
    div.style.whiteSpace = 'pre-line';
    div.innerHTML = '<div class="d-flex align-items-start">' +
      '<i class="fas fa-robot ml-2 mt-1"></i>' +
      '<div><strong>مساعد الحركة الذكي</strong><br>' + escapeHtml(message) + '</div>' +
      '</div>' +
      '<button type="button" class="close" data-dismiss="alert" aria-label="إغلاق"><span aria-hidden="true">&times;</span></button>';
    container.appendChild(div);
    setTimeout(function () {
      try {
        if (window.jQuery && window.jQuery.fn && window.jQuery.fn.alert) {
          window.jQuery(div).alert('close');
        } else if (div.parentNode) {
          div.parentNode.removeChild(div);
        }
      } catch (e) {
        if (div.parentNode) div.parentNode.removeChild(div);
      }
    }, 12000);
  }

  function inspectPayload(payload) {
    if (!payload || typeof payload !== 'object') return;
    if (payload.blocked === true || payload.ai_transaction === true) {
      showAiTransactionMessage(payload.message || payload.error || 'تم إيقاف الحركة بسبب ملاحظة ذكية.', 'danger');
      return;
    }
    if (payload.ai_feedback_message) {
      showAiTransactionMessage(payload.ai_feedback_message, payload.ai_feedback_level || 'info');
    }
  }

  function tryParseJson(text) {
    try { return JSON.parse(text); } catch (e) { return null; }
  }

  var originalFetch = window.fetch;
  if (typeof originalFetch === 'function' && !window.__aiTransactionFetchWrapped) {
    window.__aiTransactionFetchWrapped = true;
    window.fetch = function () {
      return originalFetch.apply(this, arguments).then(function (response) {
        try {
          var clone = response.clone();
          clone.text().then(function (text) { inspectPayload(tryParseJson(text)); }).catch(function () {});
        } catch (e) {}
        return response;
      });
    };
  }

  if (window.jQuery && !window.__aiTransactionAjaxWrapped) {
    window.__aiTransactionAjaxWrapped = true;
    window.jQuery(document).ajaxComplete(function (event, xhr) {
      try {
        var payload = xhr.responseJSON || tryParseJson(xhr.responseText);
        inspectPayload(payload);
      } catch (e) {}
    });
  }

  window.showAiTransactionMessage = showAiTransactionMessage;
})();

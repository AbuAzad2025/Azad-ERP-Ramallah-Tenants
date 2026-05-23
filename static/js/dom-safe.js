/**
 * DOM آمن — تقليل XSS عند تحديث الواجهة ديناميكياً.
 */
(function (global) {
  'use strict';

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function setText(el, text) {
    if (!el) return;
    el.textContent = text == null ? '' : String(text);
  }

  /** HTML من استجابة JSON للتطبيق فقط (نفس الأصل). */
  function setHtmlTrusted(el, html) {
    if (!el) return;
    const tpl = document.createElement('template');
    tpl.innerHTML = html == null ? '' : String(html);
    el.replaceChildren(...tpl.content.childNodes);
  }

  function clear(el) {
    if (!el) return;
    el.replaceChildren();
  }

  function setHtmlMessage(el, htmlString) {
    if (!el) return;
    setHtmlTrusted(el, htmlString);
  }

  function iconText(className, text) {
    return '<i class="' + escapeHtml(className) + '"></i> ' + escapeHtml(text);
  }

  global.AzadDom = {
    escapeHtml: escapeHtml,
    setText: setText,
    setHtmlTrusted: setHtmlTrusted,
    setHtmlMessage: setHtmlMessage,
    clear: clear,
    iconText: iconText,
  };
})(typeof window !== 'undefined' ? window : global);

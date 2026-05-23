/**
 * تلميحات وتلاشي لحواف التمرير الأفقي في الدفتر والتقارير المالية
 */
(function (global) {
  'use strict';

  if (global.__GM_FINANCIAL_SCROLL__) return;
  global.__GM_FINANCIAL_SCROLL__ = true;

  var THRESH = 8;

  function updateScrollState(shell) {
    var track = shell.querySelector('.gm-hscroll__track');
    if (!track) return;
    var max = track.scrollWidth - track.clientWidth;
    var scrollable = max > THRESH;
    shell.classList.toggle('is-scrollable', scrollable);
    shell.classList.toggle('is-scrolled', track.scrollLeft > THRESH);
    shell.classList.toggle('is-at-end', !scrollable || track.scrollLeft >= max - THRESH);
  }

  function bindShell(shell) {
    if (!shell || shell.dataset.gmHscrollBound) return;
    shell.dataset.gmHscrollBound = '1';
    var track = shell.querySelector('.gm-hscroll__track');
    if (!track) return;
    var onScroll = function () { updateScrollState(shell); };
    track.addEventListener('scroll', onScroll, { passive: true });
    if (typeof ResizeObserver !== 'undefined') {
      try {
        var ro = new ResizeObserver(function () { updateScrollState(shell); });
        ro.observe(track);
        var table = track.querySelector('table');
        if (table) ro.observe(table);
      } catch (_) {}
    }
    global.addEventListener('resize', onScroll, { passive: true });
    global.addEventListener('gm:layout-change', onScroll);
    setTimeout(onScroll, 0);
    setTimeout(onScroll, 400);
  }

  function initAll(root) {
    (root || document).querySelectorAll('[data-gm-hscroll]').forEach(bindShell);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { initAll(document); });
  } else {
    initAll(document);
  }

  global.gmInitFinancialScroll = initAll;
})(window);

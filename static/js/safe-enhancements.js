(function() {
  if (window.__SAFE_ENHANCEMENTS_INIT__) return;
  window.__SAFE_ENHANCEMENTS_INIT__ = true;
  'use strict';
  
  if (!window.EventUtils || !window.PerfUtils) return;
  
  const { delegate, debounce, throttle } = window.EventUtils;
  const { requestCache } = window.PerfUtils;

  function enhanceTableSearch() {
    const searchInputs = document.querySelectorAll('input[type="search"], input[placeholder*="بحث"]');
    searchInputs.forEach(input => {
      const originalHandler = input.oninput;
      if (originalHandler) {
        input.oninput = null;
        const debouncedHandler = debounce((e) => originalHandler.call(input, e), 300);
        input.addEventListener('input', debouncedHandler);
      }
    });
  }

  function wrapPlainTables() {
    const tables = document.querySelectorAll('table.table');
    tables.forEach(table => {
      if (table.closest('.table-responsive')) return;
      if (table.closest('.dataTables_wrapper')) return;
      if (table.closest('.scroll_table, .gm-scroll-rail, .gm-ledger-scroll-card, [data-gm-scroll-table]')) return;
      const parent = table.parentElement;
      if (!parent) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'table-responsive';
      parent.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    });
  }

  function enhanceTableScrolling() {
    const tables = document.querySelectorAll('.table-responsive');
    tables.forEach(container => {
      const scrollIndicator = document.createElement('div');
      scrollIndicator.className = 'scroll-indicator';
      scrollIndicator.style.cssText = `position:sticky;top:0;height:3px;background:linear-gradient(90deg,#667eea 0%,transparent 100%);transform-origin:left;transform:scaleX(0);transition:transform 0.1s ease;z-index:10`;
      container.insertBefore(scrollIndicator, container.firstChild);
      const table = container.querySelector('table');
      if (table) {
        container.addEventListener('scroll', throttle(() => {
          const scrollLeft = container.scrollLeft;
          const scrollWidth = container.scrollWidth - container.clientWidth;
          const scrollPercent = scrollWidth > 0 ? scrollLeft / scrollWidth : 0;
          scrollIndicator.style.transform = `scaleX(${scrollPercent})`;
        }, 50), { passive: true });
      }
    });
  }

  function enableAutoSaveDraft() {
    const forms = document.querySelectorAll('form[data-autosave="true"]');
    forms.forEach(form => {
      const formId = form.id || form.action;
      const storageKey = `draft_${formId}`;
      const savedDraft = localStorage.getItem(storageKey);
      if (savedDraft) {
        try {
          const data = JSON.parse(savedDraft);
          Object.keys(data).forEach(name => {
            const field = form.elements[name];
            if (field && !field.value) field.value = data[name];
          });
        } catch (e) {
          if (typeof toastr !== 'undefined') toastr.warning('بيانات المسودة المحفوظة تالفة، تم تجاهلها.');
        }
      }
      const saveHandler = debounce(() => {
        const formData = new FormData(form);
        const data = {};
        for (let [key, value] of formData.entries()) {
          if (key !== 'csrf_token') data[key] = value;
        }
        localStorage.setItem(storageKey, JSON.stringify(data));
      }, 2000);
      form.addEventListener('input', saveHandler);
      form.addEventListener('submit', () => {
        setTimeout(() => localStorage.removeItem(storageKey), 1000);
      });
    });
  }

  function enhanceModals() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const openModal = document.querySelector('.modal.show');
        if (openModal) {
          const closeBtn = openModal.querySelector('.close, [data-dismiss="modal"]');
          if (closeBtn) closeBtn.click();
        }
      }
    });
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => {
      modal.addEventListener('shown.bs.modal', () => {
        document.body.style.overflow = 'hidden';
      });
      modal.addEventListener('hidden.bs.modal', () => {
        document.body.style.overflow = '';
      });
    });
  }

  function enhanceTooltips() {
    const elements = document.querySelectorAll('[title]:not([data-toggle="tooltip"])');
    elements.forEach(el => {
      if (el.title && typeof $ !== 'undefined' && $.fn.tooltip) {
        $(el).tooltip({ trigger: 'hover', placement: 'auto', boundary: 'window' });
      }
    });
  }

  function enableCopyToClipboard() {
    delegate(document, 'click', '[data-copy]', async function(e) {
      e.preventDefault();
      const textToCopy = this.dataset.copy || this.textContent;
      try {
        await navigator.clipboard.writeText(textToCopy);
        const originalText = this.textContent;
        const originalIcon = this.innerHTML;
        if (this.querySelector('i')) {
          this.innerHTML = '<i class="fas fa-check text-success"></i> تم النسخ';
        } else {
          this.textContent = '✅ تم النسخ';
        }
        setTimeout(() => {
          if (this.querySelector('i')) {
            this.innerHTML = originalIcon;
          } else {
            this.textContent = originalText;
          }
        }, 2000);
      } catch (err) {
        if (typeof toastr !== 'undefined') toastr.error('فشل النسخ إلى الحافظة');
        else if (window.AzadUX) AzadUX.notify('warning', 'تعذّر النسخ إلى الحافظة. انسخ يدوياً.');
        else alert('تعذّر النسخ إلى الحافظة.');
      }
    });
  }

  function enhancePrintHandling() {
    window.addEventListener('beforeprint', () => {
      document.body.classList.add('is-printing');
    });
    window.addEventListener('afterprint', () => {
      document.body.classList.remove('is-printing');
    });
  }

  function enhanceFormValidation() {
    const forms = document.querySelectorAll('form[novalidate]');
    forms.forEach(form => {
      form.addEventListener('submit', function(e) {
        if (!this.checkValidity()) {
          e.preventDefault();
          e.stopPropagation();
          this.classList.add('was-validated');
          const firstInvalid = this.querySelector(':invalid');
          if (firstInvalid) {
            firstInvalid.focus();
            firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }
      });
    });
  }

  function enhanceTableRowHighlight() {
    const tables = document.querySelectorAll('.table tbody');
    tables.forEach(tbody => {
      delegate(tbody, 'mouseenter', 'tr', function() {
        this.style.backgroundColor = 'rgba(102, 126, 234, 0.1)';
      });
      delegate(tbody, 'mouseleave', 'tr', function() {
        this.style.backgroundColor = '';
      });
    });
  }

  function setupGlobalErrorHandler() {
    /* معالجة الأخطاء العامة في ux-messages.js (AzadUX) */
  }

  function enhanceNumberInputs() {
    const numberInputs = document.querySelectorAll('input[type="number"]');
    numberInputs.forEach(input => {
      if (input.min === '0') {
        input.addEventListener('keydown', (e) => {
          if (e.key === '-') e.preventDefault();
        });
      }
      input.addEventListener('focus', function() {
        this.select();
      });
    });
  }

  function enhanceDateInputs() {
    if (document.body.classList.contains('erp-unified')) {
      return;
    }
    const dateInputs = document.querySelectorAll('input[type="date"], input[type="datetime-local"]');
    dateInputs.forEach(input => {
      if (!input.classList.contains('has-icon')) {
        input.classList.add('has-icon');
        const wrapper = document.createElement('div');
        wrapper.style.position = 'relative';
        wrapper.style.display = 'inline-block';
        wrapper.style.width = '100%';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);
        const icon = document.createElement('i');
        icon.className = 'fas fa-calendar-alt';
        icon.style.cssText = 'position:absolute;left:10px;top:50%;transform:translateY(-50%);pointer-events:none;color:#6c757d';
        wrapper.appendChild(icon);
        input.style.paddingLeft = '35px';
      }
    });
  }

  function enhanceSelects() {
    const selects = document.querySelectorAll('select:not(.select2-hidden-accessible)');
    selects.forEach(select => {
      select.addEventListener('change', function() {
        this.classList.add('just-changed');
        setTimeout(() => this.classList.remove('just-changed'), 300);
      });
    });
  }

  function autoResizeTextareas() {
    const textareas = document.querySelectorAll('textarea[data-autoresize="true"]');
    textareas.forEach(textarea => {
      const resize = () => {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
      };
      textarea.addEventListener('input', resize);
      resize();
    });
  }

  function enhanceFocusManagement() {
    const forms = document.querySelectorAll('form[data-autofocus="true"]');
    forms.forEach(form => {
      const firstInput = form.querySelector('input:not([type="hidden"]), select, textarea');
      if (firstInput && !firstInput.value) {
        setTimeout(() => firstInput.focus(), 100);
      }
    });
  }

  function enhanceKeyboardNavigation() {
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        const activeForm = document.querySelector('form:not([data-no-shortcut])');
        if (activeForm) {
          e.preventDefault();
          const submitBtn = activeForm.querySelector('button[type="submit"]');
          if (submitBtn) submitBtn.click();
        }
      }
    });
  }

  function enhanceDropdowns() {
    const dropdowns = document.querySelectorAll('.dropdown-toggle');
    dropdowns.forEach(dropdown => {
      const menu = dropdown.nextElementSibling;
      if (menu && menu.classList.contains('dropdown-menu')) {
        document.addEventListener('click', (e) => {
          if (!dropdown.contains(e.target) && !menu.contains(e.target)) {
            menu.classList.remove('show');
          }
        });
      }
    });
  }

  function optimizeAnimations() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) {
      document.documentElement.style.setProperty('--transition-fast', '0s');
      document.documentElement.style.setProperty('--transition-normal', '0s');
      document.documentElement.style.setProperty('--transition-slow', '0s');
    }
  }

  function addBackToTopButton() {
    if (document.getElementById('back-to-top')) return;
    const btn = document.createElement('button');
    btn.id = 'back-to-top';
    btn.innerHTML = '<i class="fas fa-arrow-up"></i>';
    btn.title = 'العودة للأعلى';
    btn.style.cssText = 'position:fixed;bottom:20px;left:20px;width:50px;height:50px;border-radius:50%;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border:none;box-shadow:0 4px 12px rgba(0,0,0,0.2);cursor:pointer;display:none;z-index:1000;transition:all 0.3s ease;font-size:18px';
    document.body.appendChild(btn);
    window.addEventListener('scroll', throttle(() => {
      btn.style.display = window.pageYOffset > 300 ? 'block' : 'none';
    }, 100), { passive: true });
    btn.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    btn.addEventListener('mouseenter', () => {
      btn.style.transform = 'scale(1.1)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.transform = 'scale(1)';
    });
  }

  function enhanceLoadingStates() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
      form.addEventListener('submit', function(e) {
        // FIX: Don't disable button if form is invalid or submission prevented
        if (e.defaultPrevented || !this.checkValidity()) return;

        const submitBtn = this.querySelector('button[type="submit"], input[type="submit"]');
        if (submitBtn && !submitBtn.dataset.noLoading && !submitBtn.classList.contains('no-loading')) {
          submitBtn.dataset.originalHtml = submitBtn.innerHTML;
          submitBtn.disabled = true;
          submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> جاري الحفظ...';
          
          // Re-enable after 10 seconds just in case server hangs
          setTimeout(() => {
            submitBtn.disabled = false;
            if (submitBtn.dataset.originalHtml) {
              submitBtn.innerHTML = submitBtn.dataset.originalHtml;
            }
          }, 10000);
        }
      });
    });
  }

  function initBootstrapCompatBridge() {
    document.addEventListener('click', function (e) {
      const dismissBtn = e.target.closest('[data-bs-dismiss="alert"], [data-dismiss="alert"]');
      if (!dismissBtn) return;
      const alertEl = dismissBtn.closest('.alert');
      if (alertEl) {
        e.preventDefault();
        alertEl.remove();
      }
    });

    document.addEventListener('click', function (e) {
      const tabTrigger = e.target.closest('[data-bs-toggle="tab"], [data-bs-toggle="pill"]');
      if (!tabTrigger || !window.jQuery) return;
      const href = tabTrigger.getAttribute('href') || tabTrigger.getAttribute('data-bs-target');
      if (!href || href.charAt(0) !== '#') return;
      try {
        e.preventDefault();
        window.jQuery(href).tab('show');
      } catch (_) {}
    });
  }

  function initAllEnhancements() {
    try {
      initBootstrapCompatBridge();
      enhanceTableSearch();
      wrapPlainTables();
      enhanceTableScrolling();
      enableAutoSaveDraft();
      enhanceModals();
      enhanceTooltips();
      enableCopyToClipboard();
      enhancePrintHandling();
      enhanceFormValidation();
      enhanceTableRowHighlight();
      setupGlobalErrorHandler();
      enhanceNumberInputs();
      enhanceDateInputs();
      enhanceSelects();
      autoResizeTextareas();
      enhanceFocusManagement();
      enhanceDropdowns();
      optimizeAnimations();
      addBackToTopButton();
      enhanceLoadingStates();
      enhanceKeyboardNavigation();
    } catch (error) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllEnhancements);
  } else {
    initAllEnhancements();
  }
  
  window.reinitEnhancements = initAllEnhancements;
  
  window.SafeEnhancements = {
    init: initAllEnhancements,
    enhanceTableSearch,
    wrapPlainTables,
    enhanceTableScrolling,
    enableAutoSaveDraft,
    enhanceModals,
    enhanceTooltips,
    enableCopyToClipboard,
    enhancePrintHandling,
    enhanceFormValidation,
    enhanceTableRowHighlight,
    enhanceNumberInputs,
    enhanceDateInputs,
    enhanceSelects,
    autoResizeTextareas,
    enhanceFocusManagement,
    enhanceDropdowns,
    optimizeAnimations,
    addBackToTopButton,
    enhanceLoadingStates,
    enhanceKeyboardNavigation
  };

})();


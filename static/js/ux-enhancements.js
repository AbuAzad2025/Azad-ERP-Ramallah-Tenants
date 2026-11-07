(function() {
  if (window.__UX_ENHANCEMENTS_INIT__) return;
  window.__UX_ENHANCEMENTS_INIT__ = true;
  'use strict';

  const UXEnhancements = {
    init() {
      this.initProgressLoader();
      this.initTooltips();
      this.initToasts();
      this.initPasswordStrength();
      this.initLoadingStates();
      
      // Global helpers
      window.startLoader = () => { if (typeof NProgress !== 'undefined') NProgress.start(); };
      window.stopLoader = () => { if (typeof NProgress !== 'undefined') NProgress.done(); };
      window.showToast = this.showToast.bind(this);
    },

    initProgressLoader() {
      if (typeof NProgress === 'undefined') return;
      if (window.__NPROGRESS_BOUND__) return;
      window.__NPROGRESS_BOUND__ = true;

      NProgress.configure({
        showSpinner: false,
        minimum: 0.1,
        speed: 500,
        trickleSpeed: 200
      });

      if (typeof $ !== 'undefined') {
        $(document).ajaxStart(() => NProgress.start());
        $(document).ajaxStop(() => NProgress.done());
      }

      const originalFetch = window.fetch;
      window.fetch = function() {
        NProgress.start();
        return originalFetch.apply(this, arguments).then(res => {
          NProgress.done();
          return res;
        }).catch(err => {
          NProgress.done();
          throw err;
        });
      };

      document.body.addEventListener('click', function(e) {
        const link = e.target.closest('a');
        if (!link || !link.href) return;
        if (link.href.startsWith('#') || link.href.startsWith('javascript:')) return;
        if (link.target === '_blank' || e.ctrlKey || e.metaKey) return;
        if (link.hostname !== window.location.hostname) return;
        if (link.hasAttribute('download') || link.classList.contains('no-nprogress')) return;
        NProgress.start();
      }, true);
    },

    initTooltips() {
      if (typeof $ !== 'undefined' && $.fn.tooltip) {
        $('[data-toggle="tooltip"], [title]').tooltip({
          trigger: 'hover',
          boundary: 'window'
        });
      }
    },

    showToast(message, type = 'info') {
      if (window.AzadUX && typeof window.AzadUX.notify === 'function') {
        window.AzadUX.notify(type, message);
        return;
      }
      if (typeof toastr !== 'undefined') {
        const method = type === 'danger' ? 'error' : type;
        toastr[method](message);
      } else if (typeof Swal !== 'undefined') {
        Swal.fire({
          text: message,
          icon: type === 'danger' ? 'error' : type,
          toast: true,
          position: 'top-end',
          showConfirmButton: false,
          timer: 3000
        });
      } else {
        // Fallback (should not happen in production)
        console.warn('Toast library missing:', message);
      }
    },

    initToasts() {
      // Convert Flask flashes to Toastr
      const alerts = document.querySelectorAll('.alert-dismissible');
      alerts.forEach(alert => {
        let type = 'info';
        if (alert.classList.contains('alert-success')) type = 'success';
        if (alert.classList.contains('alert-danger')) type = 'error';
        if (alert.classList.contains('alert-warning')) type = 'warning';
        
        // Only show toast if it's a floating alert, otherwise keep it static
        if (alert.classList.contains('floating-alert')) {
            this.showToast(alert.innerText.trim(), type);
            alert.style.display = 'none';
        }
      });
    },

    initPasswordStrength() {
      const passwordInputs = document.querySelectorAll('input[type="password"][name="password"], input[type="password"][name="new_password"]');
      
      passwordInputs.forEach(input => {
        // Skip login forms
        if (input.closest('form[action*="login"]')) return;
        
        // Avoid duplicate init
        if (input.parentNode.querySelector('.password-strength')) return;
        
        const strengthDiv = document.createElement('div');
        strengthDiv.className = 'password-strength mt-1';
        strengthDiv.innerHTML = '<div class="progress" style="height: 5px;"><div class="progress-bar bg-danger" style="width: 0%"></div></div><small class="text-muted d-block mt-1 strength-text"></small>';
        input.parentNode.appendChild(strengthDiv);
        
        const bar = strengthDiv.querySelector('.progress-bar');
        const text = strengthDiv.querySelector('.strength-text');
        
        input.addEventListener('input', (e) => {
          const val = e.target.value;
          if (!val) {
            bar.style.width = '0%';
            text.textContent = '';
            return;
          }
          
          let score = 0;
          if (val.length >= 8) score++;
          if (val.length >= 12) score++;
          if (/[a-z]/.test(val)) score++;
          if (/[A-Z]/.test(val)) score++;
          if (/[0-9]/.test(val)) score++;
          if (/[^a-zA-Z0-9]/.test(val)) score++;
          
          let width = 0;
          let color = 'bg-danger';
          let label = 'ضعيف جداً';
          
          if (score <= 2) { width = 25; color = 'bg-danger'; label = 'ضعيف'; }
          else if (score <= 4) { width = 60; color = 'bg-warning'; label = 'متوسط'; }
          else { width = 100; color = 'bg-success'; label = 'قوي'; }
          
          bar.style.width = width + '%';
          bar.className = `progress-bar ${color}`;
          text.textContent = label;
          text.className = `small d-block mt-1 strength-text text-${color.replace('bg-', '')}`;
        });
      });
    },

    initLoadingStates() {
      document.addEventListener('submit', function(e) {
        const form = e.target;
        if (!form || form.getAttribute('data-no-loading') === 'true') return;
        if (form.checkValidity && !form.checkValidity()) return;
        
        const btn = form.querySelector('button[type="submit"]:not(.no-loading)');
        if (btn) {
          if (btn.classList.contains('loading')) {
            e.preventDefault();
            return;
          }
          
          // Save original width to prevent jumping
          btn.style.width = getComputedStyle(btn).width;
          
          btn.classList.add('loading');
          const originalContent = btn.innerHTML;
          btn.setAttribute('data-original-content', originalContent);
          
          btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';
          btn.disabled = true;
          
          // Safety timeout (15s)
          setTimeout(() => {
            if (btn.isConnected) {
                btn.classList.remove('loading');
                btn.innerHTML = originalContent;
                btn.disabled = false;
                btn.style.width = '';
            }
          }, 15000);
        }
        
        if (typeof NProgress !== 'undefined') NProgress.start();
      }, true);
    }
  };

  // Initialize on DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => UXEnhancements.init());
  } else {
    UXEnhancements.init();
  }
})();

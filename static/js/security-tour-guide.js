(function() {
  if (window.__SECURITY_TOUR_GUIDE_INIT__) return;
  window.__SECURITY_TOUR_GUIDE_INIT__ = true;

  window.SecurityTourGuide = {
    currentStep: 0,
    totalSteps: 0,
    overlay: null,
    spotlight: null,
    tooltipBox: null,
    isActive: false,

    tours: {
      dashboard: [
        {
          element: '.security-sidebar',
          title: 'القائمة الجانبية',
          description: 'تنقل بين أقسام لوحة المالك: المراقبة، الإدارة، النظام، البيانات، والطوارئ.',
          position: 'right'
        },
        {
          element: '[data-target="#commandPaletteModal"]',
          title: 'البحث السريع',
          description: 'اضغط Ctrl+K للبحث في الصفحات والأوامر.',
          position: 'bottom'
        },
        {
          element: '.erp-sec-kpi-row',
          title: 'مؤشرات المستخدمين',
          description: 'أرقام حقيقية من قاعدة البيانات مع رسوم بيانية لآخر 7 أيام.',
          position: 'top'
        },
        {
          element: '.erp-sec-stat',
          title: 'التشغيل والبنية',
          description: 'متصلون الآن، IPs محظورة، نشاط مشبوه، وحجم قاعدة البيانات.',
          position: 'top'
        },
        {
          element: '#sidebarToggle',
          title: 'إظهار/إخفاء القائمة',
          description: 'توسيع مساحة المحتوى بإخفاء الشريط الجانبي.',
          position: 'right'
        }
      ],

      database_manager: [
        {
          element: '.nav-tabs',
          title: 'التبويبات',
          description: 'أدوات DR: تصفح، SQL، نسخ احتياطي، وصيانة.',
          position: 'bottom'
        },
        {
          element: '[data-toggle="tab"][href="#browse"]',
          title: 'تصفح الجداول',
          description: 'عرض بيانات الجداول مباشرة.',
          position: 'bottom'
        },
        {
          element: '[data-toggle="tab"][href="#sql"]',
          title: 'محرر SQL',
          description: 'تنفيذ استعلامات على قاعدة البيانات.',
          position: 'bottom'
        }
      ],

      security_center: [
        {
          element: '.card:first',
          title: 'مركز الأمان',
          description: 'مراقبة الأنشطة الأمنية والتهديدات.',
          position: 'bottom'
        }
      ]
    },

    start: function(tourName = 'dashboard') {
      const tour = this.tours[tourName];
      if (!tour || tour.length === 0) {
        return;
      }

      if (localStorage.getItem(`security_tour_${tourName}_completed`) === 'true') {
        if (!confirm('لقد أكملت هذه الجولة من قبل. هل تريد إعادتها؟')) {
          return;
        }
      }

      this.currentStep = 0;
      this.totalSteps = tour.length;
      this.isActive = true;
      this.currentTour = tourName;

      this.createOverlay();
      this.showStep(tour[0]);
    },

    createOverlay: function() {
      this.overlay = document.createElement('div');
      this.overlay.id = 'tour-overlay';
      this.overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.7);
        z-index: 99998;
        pointer-events: none;
      `;

      this.spotlight = document.createElement('div');
      this.spotlight.id = 'tour-spotlight';
      this.spotlight.style.cssText = `
        position: absolute;
        border: 3px solid #ffc107;
        border-radius: 8px;
        box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.7);
        transition: all 0.3s ease;
        pointer-events: none;
        z-index: 99999;
      `;

      this.tooltipBox = document.createElement('div');
      this.tooltipBox.id = 'tour-tooltip';
      this.tooltipBox.style.cssText = `
        position: absolute;
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        max-width: 350px;
        z-index: 100000;
        pointer-events: auto;
      `;

      document.body.appendChild(this.overlay);
      document.body.appendChild(this.spotlight);
      document.body.appendChild(this.tooltipBox);
    },

    showStep: function(step) {
      const element = document.querySelector(step.element);
      if (!element) {
        this.next();
        return;
      }

      element.scrollIntoView({ behavior: 'smooth', block: 'center' });

      setTimeout(() => {
        const rect = element.getBoundingClientRect();

        this.spotlight.style.top = (rect.top - 10) + 'px';
        this.spotlight.style.left = (rect.left - 10) + 'px';
        this.spotlight.style.width = (rect.width + 20) + 'px';
        this.spotlight.style.height = (rect.height + 20) + 'px';

        this.positionTooltip(rect, step.position);

        this.tooltipBox.innerHTML = `
          <div class="tour-header mb-3">
            <h5 class="mb-0 text-primary">
              <i class="fas fa-lightbulb text-warning"></i> ${step.title}
            </h5>
            <small class="text-muted">خطوة ${this.currentStep + 1} من ${this.totalSteps}</small>
          </div>
          <p class="mb-3">${step.description}</p>
          <div class="d-flex justify-content-between align-items-center">
            <div class="progress flex-grow-1 mr-3" style="height: 6px;">
              <div class="progress-bar bg-primary" style="width: ${((this.currentStep + 1) / this.totalSteps) * 100}%"></div>
            </div>
            <div class="btn-group">
              ${this.currentStep > 0 ? '<button class="btn btn-sm btn-outline-secondary" onclick="SecurityTourGuide.previous()"><i class="fas fa-arrow-right"></i></button>' : ''}
              <button class="btn btn-sm btn-outline-danger" onclick="SecurityTourGuide.stop()">إيقاف</button>
              <button class="btn btn-sm btn-primary" onclick="SecurityTourGuide.next()">
                ${this.currentStep < this.totalSteps - 1 ? 'التالي <i class="fas fa-arrow-left"></i>' : 'إنهاء <i class="fas fa-check"></i>'}
              </button>
            </div>
          </div>
        `;
      }, 100);
    },

    positionTooltip: function(rect, position) {
      const tooltip = this.tooltipBox;
      const padding = 20;

      switch(position) {
        case 'top':
          tooltip.style.top = (rect.top - tooltip.offsetHeight - padding) + 'px';
          tooltip.style.left = (rect.left + rect.width / 2 - tooltip.offsetWidth / 2) + 'px';
          break;
        case 'bottom':
          tooltip.style.top = (rect.bottom + padding) + 'px';
          tooltip.style.left = (rect.left + rect.width / 2 - tooltip.offsetWidth / 2) + 'px';
          break;
        case 'left':
          tooltip.style.top = (rect.top + rect.height / 2 - tooltip.offsetHeight / 2) + 'px';
          tooltip.style.left = (rect.left - tooltip.offsetWidth - padding) + 'px';
          break;
        case 'right':
          tooltip.style.top = (rect.top + rect.height / 2 - tooltip.offsetHeight / 2) + 'px';
          tooltip.style.left = (rect.right + padding) + 'px';
          break;
      }

      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const tooltipRect = tooltip.getBoundingClientRect();

      if (tooltipRect.right > viewportWidth) {
        tooltip.style.left = (viewportWidth - tooltipRect.width - 20) + 'px';
      }
      if (tooltipRect.left < 0) {
        tooltip.style.left = '20px';
      }
      if (tooltipRect.bottom > viewportHeight) {
        tooltip.style.top = (viewportHeight - tooltipRect.height - 20) + 'px';
      }
      if (tooltipRect.top < 0) {
        tooltip.style.top = '20px';
      }
    },

    next: function() {
      this.currentStep++;

      if (this.currentStep >= this.totalSteps) {
        this.complete();
      } else {
        const tour = this.tours[this.currentTour];
        this.showStep(tour[this.currentStep]);
      }
    },

    previous: function() {
      if (this.currentStep > 0) {
        this.currentStep--;
        const tour = this.tours[this.currentTour];
        this.showStep(tour[this.currentStep]);
      }
    },

    stop: function() {
      if (confirm('هل تريد إيقاف الجولة الإرشادية؟')) {
        this.cleanup();
      }
    },

    complete: function() {
      localStorage.setItem(`security_tour_${this.currentTour}_completed`, 'true');

      this.tooltipBox.innerHTML = `
        <div class="text-center">
          <i class="fas fa-check-circle text-success fa-3x mb-3"></i>
          <h5 class="text-success">تم إكمال الجولة</h5>
          <p>يمكنك الآن استكشاف اللوحة بحرية</p>
          <button class="btn btn-primary" onclick="SecurityTourGuide.cleanup()">إغلاق</button>
        </div>
      `;

      setTimeout(() => {
        this.cleanup();
      }, 3000);
    },

    cleanup: function() {
      this.overlay?.remove();
      this.spotlight?.remove();
      this.tooltipBox?.remove();
      this.isActive = false;
      this.currentStep = 0;
    }
  };

  document.addEventListener('keydown', function(e) {
    if (!SecurityTourGuide.isActive) return;

    if (e.key === 'ArrowLeft' || e.key === 'Enter') {
      SecurityTourGuide.next();
    } else if (e.key === 'ArrowRight') {
      SecurityTourGuide.previous();
    } else if (e.key === 'Escape') {
      SecurityTourGuide.stop();
    }
  });

})();

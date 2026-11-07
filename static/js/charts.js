(function () {
  if (window.__CHARTS_INIT__) return;
  window.__CHARTS_INIT__ = true;

  'use strict';

  let chartsInitialized = false;
  let chartLibrariesPromise = null;

  const parseJsonSafe = (raw, fallback) => {
    try { return raw ? JSON.parse(raw) : fallback; } catch { return fallback; }
  };

  var escapeHtml = window.escapeHtml || function(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  };

  function buildDataPreviewHtml(el) {
    const labels = parseJsonSafe(el.getAttribute('data-labels'), []);
    const rawDatasets = parseJsonSafe(el.getAttribute('data-datasets'), null);
    const values = parseJsonSafe(el.getAttribute('data-values'), []);

    const rows = [];
    if (Array.isArray(rawDatasets) && rawDatasets.length) {
      const ds = rawDatasets[0];
      const data = Array.isArray(ds?.data) ? ds.data : [];
      for (let i = 0; i < Math.min(labels.length, data.length, 8); i++) {
        rows.push({ label: labels[i], value: data[i] });
      }
    } else if (Array.isArray(values) && values.length) {
      for (let i = 0; i < Math.min(labels.length, values.length, 8); i++) {
        rows.push({ label: labels[i], value: values[i] });
      }
    }

    if (!rows.length) return '';
    const items = rows.map(r => `<tr><td>${escapeHtml(r.label)}</td><td>${escapeHtml(r.value)}</td></tr>`).join('');
    return `
      <div class="chart-fallback-preview">
        <div class="chart-fallback-preview-title">معاينة بيانات (آخر 8 نقاط)</div>
        <div class="table-responsive">
          <table class="table table-sm mb-0">
            <thead><tr><th>الفترة</th><th>القيمة</th></tr></thead>
            <tbody>${items}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  function ensureChartContainer(el) {
    const container = el?.parentElement;
    if (!container) return null;
    const computed = window.getComputedStyle(container);
    if (computed.position === 'static') {
      container.style.position = 'relative';
    }
    return container;
  }

  function clearChartFallback(el) {
    const container = ensureChartContainer(el);
    if (!container) return;
    const existing = container.querySelector('.chart-fallback');
    if (existing) existing.remove();
  }

  function showChartFallback(el, opts = {}) {
    const container = ensureChartContainer(el);
    if (!container) return;
    clearChartFallback(el);

    const title = opts.title || 'تعذر عرض الرسم البياني';
    const message = opts.message || 'تحقق من الاتصال أو توفر البيانات.';
    const detail = opts.detail || '';
    const previewHtml = opts.previewHtml || '';
    const canRetry = opts.retry === true;

    const overlay = document.createElement('div');
    overlay.className = 'chart-fallback';
    const safeTitle = escapeHtml(title);
    const safeMessage = escapeHtml(message);
    const safeDetail = escapeHtml(detail);
    overlay.innerHTML = `
      <div class="chart-fallback-inner">
        <div class="chart-fallback-title">${safeTitle}</div>
        <div class="chart-fallback-message">${safeMessage}</div>
        ${detail ? `<div class="chart-fallback-detail">${safeDetail}</div>` : ''}
        ${previewHtml || ''}
        ${canRetry ? `<button type="button" class="btn btn-sm btn-primary chart-fallback-retry">إعادة المحاولة</button>` : ''}
      </div>
    `;
    container.appendChild(overlay);

    if (canRetry) {
      const btn = overlay.querySelector('.chart-fallback-retry');
      if (btn) {
        btn.addEventListener('click', () => {
          clearChartFallback(el);
          try { startCharts(true); } catch {}
        });
      }
    }
  }

  function showFallbackForAllCanvases(opts) {
    document.querySelectorAll('canvas.chartjs-chart').forEach(el => showChartFallback(el, { ...opts, previewHtml: buildDataPreviewHtml(el) }));
  }

  function onReady(callback) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', callback, { once: true });
    } else {
      callback();
    }
  }

  function hasChartElements(root = document) {
    return !!(root.querySelector && root.querySelector('canvas.chartjs-chart'));
  }

  function loadExternalScript(src) {
    if (window.PerfUtils && PerfUtils.loadScript) {
      return PerfUtils.loadScript(src, { async: false });
    }
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.async = false;
      script.onload = () => resolve(script);
      script.onerror = () => reject(new Error('Failed to load script: ' + src));
      document.head.appendChild(script);
    });
  }

  function ensureChartLibraries() {
    if (typeof window.Chart !== 'undefined') {
      return Promise.resolve();
    }
    if (chartLibrariesPromise) return chartLibrariesPromise;
    const chartSources = [
      'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js'
    ];
    const labelSources = [
      'https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0'
    ];
    const tryLoadFirstAvailable = (sources) => sources.reduce((p, src) => p.catch(() => loadExternalScript(src)), Promise.reject(new Error('init')));
    const sources = [
      () => tryLoadFirstAvailable(chartSources),
      () => tryLoadFirstAvailable(labelSources).catch(() => null)
    ];
    chartLibrariesPromise = sources.reduce((chain, loader) => chain.then(loader), Promise.resolve()).then(() => {
      if (typeof window.Chart === 'undefined') {
        throw new Error('Chart libraries failed to load');
      }
    }).catch(error => {
      chartLibrariesPromise = null;
      throw error;
    });
    return chartLibrariesPromise;
  }

  function bootstrap() {
    if (chartsInitialized) return;
    if (typeof window.Chart === 'undefined') return;
    chartsInitialized = true;

    const isRTL = (document.dir || document.documentElement.getAttribute('dir') || '').toLowerCase() === 'rtl';
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const uiMode = (document.documentElement.getAttribute('data-ui-mode') || '').toLowerCase();
    const isCompact = uiMode === 'mobile' || (uiMode !== 'desktop' && window.matchMedia && window.matchMedia('(max-width: 768px)').matches);
    const isDashboard = document.body.classList.contains('dashboard-page');
    const fallbackPalette = ['#0d6efd','#198754','#dc3545','#fd7e14','#20c997','#6f42c1','#0dcaf0','#6610f2','#6c757d','#198754'];
    const varColor = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
    const palette = [
      varColor('--erp-primary', varColor('--bs-primary', fallbackPalette[0])),
      varColor('--erp-success', varColor('--bs-success', fallbackPalette[1])),
      varColor('--erp-danger', varColor('--bs-danger', fallbackPalette[2])),
      varColor('--erp-warning', varColor('--bs-warning', fallbackPalette[3])),
      varColor('--erp-secondary', varColor('--bs-teal', fallbackPalette[4])),
      varColor('--erp-accent', varColor('--bs-purple', fallbackPalette[5])),
      varColor('--erp-info', varColor('--bs-info', fallbackPalette[6])),
      varColor('--erp-gold', varColor('--bs-indigo', fallbackPalette[7])),
      varColor('--erp-primary-dark', varColor('--bs-secondary', fallbackPalette[8])),
      varColor('--erp-success', varColor('--bs-green', fallbackPalette[9]))
    ];
    const getColor = (i, custom) => (custom && custom[i]) || palette[i % palette.length];

    function formatValue(v, opts = {}) {
      const n = Number(v);
      if (!isFinite(n)) return String(v);
      const { currency, unit, digits = 2, locale = 'en-US' } = opts;
      try {
        if (currency) return new Intl.NumberFormat(locale, { style: 'currency', currency, maximumFractionDigits: digits }).format(n);
        const str = new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(n);
        return unit ? `${str} ${unit}` : str;
      } catch {
        const str = n.toFixed(Math.max(0, Math.min(6, digits)));
        return unit ? `${str} ${unit}` : str;
      }
    }

    function createInteractiveChart(canvas, config) {
      const chart = new Chart(canvas, {
        ...config,
        options: {
          ...config.options,
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            intersect: false,
            mode: 'index'
          },
          plugins: {
            ...config.options?.plugins,
            legend: {
              ...config.options?.plugins?.legend,
              position: 'top',
              labels: {
                usePointStyle: true,
                padding: 20,
                font: {
                  family: 'Cairo, sans-serif',
                  size: 12
                }
              }
            },
            tooltip: {
              ...config.options?.plugins?.tooltip,
              backgroundColor: 'rgba(0, 0, 0, 0.8)',
              titleColor: '#fff',
              bodyColor: '#fff',
              borderColor: '#fff',
              borderWidth: 1,
              cornerRadius: 6,
              displayColors: true,
              callbacks: {
                ...config.options?.plugins?.tooltip?.callbacks,
                label: function(context) {
                  const label = context.dataset.label || '';
                  const value = context.parsed.y || context.parsed;
                  return `${label}: ${formatValue(value, { currency: 'ILS' })}`;
                }
              }
            }
          },
          scales: {
            ...config.options?.scales,
            x: {
              ...config.options?.scales?.x,
              grid: {
                display: true,
                color: 'rgba(0, 0, 0, 0.1)'
              },
              ticks: {
                font: {
                  family: 'Cairo, sans-serif',
                  size: 11
                }
              }
            },
            y: {
              ...config.options?.scales?.y,
              grid: {
                display: true,
                color: 'rgba(0, 0, 0, 0.1)'
              },
              ticks: {
                font: {
                  family: 'Cairo, sans-serif',
                  size: 11
                },
                callback: function(value) {
                  return formatValue(value, { currency: 'ILS' });
                }
              }
            }
          }
        }
      });

      canvas.onclick = function(event) {
        const points = chart.getElementsAtEventForMode(event, 'nearest', { intersect: true }, true);
        if (points.length) {
          const point = points[0];
          const data = chart.data.datasets[point.datasetIndex].data[point.index];
          showDataDetails(data, point.datasetIndex, point.index);
        }
      };

      return chart;
    }

    function showDataDetails(data, datasetIndex, dataIndex) {
      const detailsContainer = document.getElementById('chart-details');
      if (detailsContainer) {
        detailsContainer.textContent = '';
        const card = document.createElement('div');
        card.className = 'card';

        const header = document.createElement('div');
        header.className = 'card-header';
        const title = document.createElement('h5');
        title.className = 'card-title';
        title.textContent = 'تفاصيل البيانات';
        header.appendChild(title);

        const body = document.createElement('div');
        body.className = 'card-body';

        const pValue = document.createElement('p');
        const strongValue = document.createElement('strong');
        strongValue.textContent = 'القيمة:';
        pValue.appendChild(strongValue);
        pValue.appendChild(document.createTextNode(' ' + formatValue(data, { currency: 'ILS' })));

        const pDataset = document.createElement('p');
        const strongDataset = document.createElement('strong');
        strongDataset.textContent = 'المجموعة:';
        pDataset.appendChild(strongDataset);
        pDataset.appendChild(document.createTextNode(' ' + String((datasetIndex || 0) + 1)));

        const pIndex = document.createElement('p');
        const strongIndex = document.createElement('strong');
        strongIndex.textContent = 'الفهرس:';
        pIndex.appendChild(strongIndex);
        pIndex.appendChild(document.createTextNode(' ' + String((dataIndex || 0) + 1)));

        body.appendChild(pValue);
        body.appendChild(pDataset);
        body.appendChild(pIndex);

        card.appendChild(header);
        card.appendChild(body);
        detailsContainer.appendChild(card);
      }
    }

    const parseJsonAttr = (el, name, fallback) => {
      const raw = el.getAttribute(name);
      try { return raw ? JSON.parse(raw) : fallback; } catch { return fallback; }
    };

    function hasMeaningfulData(labels, datasets) {
      if (!Array.isArray(labels) || labels.length === 0) return false;
      if (!Array.isArray(datasets) || datasets.length === 0) return false;
      return datasets.some(ds => Array.isArray(ds?.data) && ds.data.length > 0);
    }

    function buildDatasets(el, ctx) {
      const rawDatasets = parseJsonAttr(el, 'data-datasets', null);
      const colors = parseJsonAttr(el, 'data-colors', null);
      const smooth = el.getAttribute('data-smooth') === '1';
      const fill = el.getAttribute('data-fill') === '1';
      if (Array.isArray(rawDatasets)) {
        return rawDatasets.map((d, i) => {
          const gradient = ctx.createLinearGradient(0, 0, 0, el.height);
          gradient.addColorStop(0, getColor(i, colors));
          gradient.addColorStop(1, getColor((i+1), colors));
          return {
            label: d.label || `Dataset ${i + 1}`,
            data: Array.isArray(d.data) ? d.data : [],
            borderWidth: 2,
            tension: smooth ? 0.35 : 0,
            fill: d.fill ?? fill,
            borderColor: d.borderColor || getColor(i, colors),
            backgroundColor: d.backgroundColor || gradient
          };
        });
      }
      const values = parseJsonAttr(el, 'data-values', []);
      const label = el.getAttribute('data-label') || '';
      const gradient = ctx.createLinearGradient(0, 0, 0, el.height);
      gradient.addColorStop(0, getColor(0, colors));
      gradient.addColorStop(1, getColor(1, colors));
      return [{
        label,
        data: Array.isArray(values) ? values : [],
        borderWidth: 2,
        tension: smooth ? 0.35 : 0,
        fill,
        borderColor: getColor(0, colors),
        backgroundColor: gradient
      }];
    }

    function buildOptions(el) {
      const chartType = (el.getAttribute('data-chart-type') || el.getAttribute('data-type') || 'line').toLowerCase();
      const isCircular = chartType === 'doughnut' || chartType === 'pie';
      const currency = el.getAttribute('data-currency');
      const unit = el.getAttribute('data-unit');
      const digits = parseInt(el.getAttribute('data-digits') || '2', 10);
      const stacked = el.getAttribute('data-stacked') === '1';
      const tickFontSize = isCompact ? 10 : (isDashboard ? 10 : 11);
      const legendFontSize = isCompact ? 10 : (isDashboard ? 11 : 12);
      const legendOnBottom = isCompact || isDashboard || isCircular;
      const tickFormat = {
        callback: val => formatValue(val, { currency, unit, digits }),
        maxTicksLimit: isCompact ? 5 : (isDashboard ? 6 : 8)
      };
      const plugins = {
        legend: {
          display: true,
          rtl: isRTL,
          position: legendOnBottom ? 'bottom' : 'top',
          labels: {
            usePointStyle: true,
            padding: isDashboard ? 10 : (isCompact ? 12 : 20),
            boxWidth: isDashboard ? 10 : 12,
            font: { family: 'Cairo, sans-serif', size: legendFontSize }
          }
        },
        tooltip: {
          enabled: true,
          rtl: isRTL,
          callbacks: {
            label: ctx => {
              const v = ctx.parsed.y ?? ctx.parsed ?? ctx.raw;
              const title = ctx.dataset.label ? `${ctx.dataset.label}: ` : '';
              return title + formatValue(v, { currency, unit, digits });
            }
          }
        }
      };
      if (typeof window.ChartDataLabels !== 'undefined' && !isDashboard) {
        plugins.datalabels = {
          anchor: 'end',
          align: 'top',
          color: '#444',
          font: { weight: 'bold', size: 10 },
          formatter: val => formatValue(val, { currency, unit, digits })
        };
      } else if (typeof window.ChartDataLabels !== 'undefined') {
        plugins.datalabels = { display: false };
      }
      const options = {
        responsive: true,
        maintainAspectRatio: false,
        devicePixelRatio: dpr,
        interaction: { mode: 'index', intersect: false },
        layout: {
          padding: isDashboard
            ? { top: 4, right: 8, bottom: 4, left: 8 }
            : { top: 8, right: 12, bottom: 8, left: 12 }
        },
        animations: {
          tension: { duration: 1200, easing: 'easeInOutQuad', from: 0.2, to: 0.5, loop: false }
        },
        plugins
      };
      if (!isCircular) {
        options.scales = {
          x: {
            stacked,
            grid: { display: false },
            ticks: {
              maxRotation: isDashboard ? 0 : 0,
              autoSkip: true,
              maxTicksLimit: isDashboard ? 7 : undefined,
              font: { family: 'Cairo, sans-serif', size: tickFontSize }
            }
          },
          y: {
            stacked,
            beginAtZero: true,
            grace: '5%',
            ticks: { ...tickFormat, font: { family: 'Cairo, sans-serif', size: tickFontSize } }
          }
        };
      }
      return options;
    }

    function buildConfig(el, ctx) {
      const type = el.getAttribute('data-chart-type') || el.getAttribute('data-type') || 'line';
      const labels = parseJsonAttr(el, 'data-labels', []);
      const datasets = buildDatasets(el, ctx);
      const plugins = typeof window.ChartDataLabels !== 'undefined' ? [window.ChartDataLabels] : [];
      const empty = !hasMeaningfulData(labels, datasets);
      return { type, data: { labels, datasets }, options: buildOptions(el), plugins, __empty: empty };
    }

    function showLoader(el) {
      let loader = el.parentElement.querySelector('.chartjs-loader');
      if (!loader) {
        loader = document.createElement('div');
        loader.className = 'chartjs-loader';
        loader.innerHTML = `<div class="spinner-border text-primary" role="status" style="width:2rem;height:2rem;"><span class="visually-hidden">Loading...</span></div>`;
        loader.style.cssText = `position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);z-index:2;`;
        el.parentElement.style.position = 'relative';
        el.parentElement.appendChild(loader);
      }
    }

    function hideLoader(el) {
      const loader = el.parentElement.querySelector('.chartjs-loader');
      if (loader) loader.remove();
    }

    function ensureChartHost(el) {
      const parent = el.parentElement;
      if (!parent || parent.classList.contains('erp-chart-host')) return;
      if (!parent.classList.contains('card-body') && parent.tagName !== 'DIV') return;
      const host = document.createElement('div');
      host.className = isCompact ? 'erp-chart-host erp-chart-host--sm' : 'erp-chart-host erp-chart-host--lg';
      parent.insertBefore(host, el);
      host.appendChild(el);
    }

    function initCanvas(el) {
      const ctx = el.getContext('2d');
      if (!ctx) return;
      ensureChartHost(el);
      if (isCompact) {
        const parent = el.parentElement;
        if (parent) {
          try {
            const h = parseInt(window.getComputedStyle(parent).height || '0', 10);
            const maxH = window.matchMedia && window.matchMedia('(max-width: 375px)').matches ? 200 : 220;
            if (h && h > maxH) {
              parent.style.setProperty('height', `${maxH}px`, 'important');
            }
          } catch (e) {}
        }
      }
      clearChartFallback(el);
      showLoader(el);
      setTimeout(() => {
        if (el._chartjsInstance) { try { el._chartjsInstance.destroy(); } catch {} el._chartjsInstance = null; }
        const config = buildConfig(el, ctx);
        if (config.__empty) {
          hideLoader(el);
          showChartFallback(el, {
            title: 'لا توجد بيانات للرسم البياني',
            message: 'لا توجد بيانات كافية لعرض هذا الرسم حالياً.'
          });
          return;
        }
        try {
          el._chartjsInstance = new Chart(ctx, config);
          hideLoader(el);
        } catch (e) {
          hideLoader(el);
          showChartFallback(el, {
            title: 'تعذر رسم البيانات',
            message: 'حدث خطأ أثناء إنشاء الرسم البياني.',
            detail: (e && e.message) ? String(e.message) : '',
            retry: true
          });
        }
      }, 50);
    }

    function destroyCanvas(el) {
      if (el?._chartjsInstance) { try { el._chartjsInstance.destroy(); } catch {} el._chartjsInstance = null; }
    }

    function updateCanvas(el) {
      const chart = el._chartjsInstance;
      if (!chart) { initCanvas(el); return; }
      const ctx = el.getContext('2d');
      const labels = parseJsonAttr(el, 'data-labels', []);
      const datasets = buildDatasets(el, ctx);
      chart.data.labels = labels;
      chart.data.datasets = datasets;
      chart.options = buildOptions(el);
      chart.update();
    }

    let observer = null;
    function observeAndInit(el) {
      if (!('IntersectionObserver' in window)) { initCanvas(el); return; }
      if (!observer) {
        observer = new IntersectionObserver(entries => {
          entries.forEach(entry => { if (entry.isIntersecting) { initCanvas(entry.target); observer.unobserve(entry.target); } });
        }, { rootMargin: '100px' });
      }
      observer.observe(el);
    }

    function attachAutoUpdateButton(el) {
      if (el.getAttribute('data-auto-button') !== '1') return;
      const button = document.createElement('button');
      button.className = 'btn btn-sm btn-outline-primary mt-2';
      button.textContent = 'تحديث الرسم';
      button.addEventListener('click', () => {
        const oldValues = parseJsonAttr(el, 'data-values', []);
        const newValues = oldValues.map(v => v + Math.round(Math.random() * 10));
        el.setAttribute('data-values', JSON.stringify(newValues));
        AppCharts.refresh(el);
      });
      el.parentElement.appendChild(button);
    }

    const AppCharts = {
      init(root = document) {
        const scope = root instanceof Element ? root : document;
        scope.querySelectorAll('canvas.chartjs-chart').forEach(el => { observeAndInit(el); attachAutoUpdateButton(el); });
      },
      refresh(root = document) {
        const scope = root instanceof Element ? root : document;
        scope.querySelectorAll('canvas.chartjs-chart').forEach(updateCanvas);
      },
      destroy(root = document) {
        const scope = root instanceof Element ? root : document;
        scope.querySelectorAll('canvas.chartjs-chart').forEach(destroyCanvas);
      }
    };

    window.AppCharts = AppCharts;
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => { AppCharts.init(); });
    } else {
      AppCharts.init();
    }
  }

  function startCharts() {
    ensureChartLibraries().then(() => {
      bootstrap();
    }).catch(() => {
      showFallbackForAllCanvases({
        title: 'تعذر تحميل الرسوم البيانية',
        message: 'تعذر تحميل مكتبة الرسم. غالباً بسبب عدم توفر الإنترنت أو حظر CDN.',
        detail: 'يمكنك إعادة المحاولة أو إضافة نسخة محلية من Chart.js.',
        retry: true
      });
    });
  }

  window.addEventListener('erp-theme-change', function () {
    chartsInitialized = false;
    document.querySelectorAll('canvas.chartjs-chart').forEach(function (el) {
      if (el._chartjsInstance) {
        try {
          el._chartjsInstance.destroy();
        } catch (_) {}
        el._chartjsInstance = null;
      }
    });
    if (typeof window.Chart !== 'undefined' && hasChartElements()) {
      startCharts();
    }
  });

  onReady(() => {
    if (hasChartElements()) {
      startCharts();
      return;
    }
    if (!('MutationObserver' in window)) return;
    const watcher = new MutationObserver(() => {
      if (hasChartElements()) {
        watcher.disconnect();
        startCharts();
      }
    });
    watcher.observe(document.body, { childList: true, subtree: true });
  });
})();

(function() {
  if (window.__SECURITY_CHARTS_INIT__) return;
  window.__SECURITY_CHARTS_INIT__ = true;

  document.addEventListener('DOMContentLoaded', function() {
    if (typeof Chart === 'undefined') return;
    initSecurityCharts();
  });

  async function initSecurityCharts() {
    const data = await fetchChartData();
    if (!data) return;

    renderLineChart('usersTrendChart', data.labels, data.active_users, {
      borderColor: 'var(--erp-primary, #006b3f)',
      backgroundColor: 'rgba(0, 107, 63, 0.12)',
      label: 'دخول ناجح'
    });

    renderLineChart('activitySparkline', data.labels, data.activity, {
      borderColor: 'var(--erp-success, #22c55e)',
      backgroundColor: 'transparent',
      label: 'نشاط',
      sparkline: true
    });

    renderBarChart('failedLoginsChart', data.labels, data.failed_logins);

    renderDoughnutChart('systemHealthChart', data.active_users_total, data.blocked_users);
  }

  async function fetchChartData() {
    try {
      const response = await fetch('/security/api/chart-data');
      if (!response.ok) return null;
      const payload = await response.json();
      if (payload.error) return null;
      return payload;
    } catch (_) {
      return null;
    }
  }

  function renderLineChart(canvasId, labels, values, opts) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !Array.isArray(values)) return;

    new Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: opts.label || '',
          data: values,
          borderColor: opts.borderColor,
          backgroundColor: opts.backgroundColor || 'transparent',
          tension: 0.35,
          fill: opts.sparkline ? false : true,
          pointRadius: opts.sparkline ? 0 : 2,
          pointHoverRadius: opts.sparkline ? 0 : 4,
          borderWidth: opts.sparkline ? 2 : 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: opts.sparkline ? {
          x: { display: false },
          y: { display: false }
        } : {
          y: { beginAtZero: true, ticks: { precision: 0, maxTicksLimit: 4 } },
          x: { ticks: { maxTicksLimit: 7, font: { size: 10 } } }
        }
      }
    });
  }

  function renderBarChart(canvasId, labels, values) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !Array.isArray(values)) return;

    new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'محاولات فاشلة',
          data: values,
          backgroundColor: 'rgba(239, 68, 68, 0.75)',
          borderColor: '#ef4444',
          borderWidth: 0,
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0, maxTicksLimit: 4 } },
          x: { ticks: { maxTicksLimit: 7, font: { size: 10 } } }
        }
      }
    });
  }

  function renderDoughnutChart(canvasId, activeCount, blockedCount) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const active = parseInt(activeCount, 10) || 0;
    const blocked = parseInt(blockedCount, 10) || 0;

    new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: ['نشط', 'معطّل'],
        datasets: [{
          data: [active, blocked],
          backgroundColor: ['rgba(34, 197, 94, 0.85)', 'rgba(239, 68, 68, 0.85)'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '65%',
        plugins: { legend: { display: false } }
      }
    });
  }
})();

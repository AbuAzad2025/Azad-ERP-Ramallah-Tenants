if (window.__PRINT_JS_INIT__) return;
window.__PRINT_JS_INIT__ = true;

function initPrint() {
    document.querySelectorAll('.btn-print').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            printReport(this.getAttribute('data-target') || 'body');
        });
    });
}

var escapeHtml = window.escapeHtml || function(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

function readMeta(name) {
    try {
        return document.querySelector('meta[name="' + name + '"]')?.getAttribute('content') || '';
    } catch {
        return '';
    }
}

function printReport(targetSelector = 'body') {
    const printContent = document.querySelector(targetSelector);
    
    if (!printContent) {
        return;
    }

    const originalContents = document.body.innerHTML;
    const printableContent = printContent.innerHTML;

    const printHeader = generatePrintHeader();
    const printInfo = generatePrintInfo();
    const printFooter = generatePrintFooter();

    const fullContent = `
        <div class="print-container">
            ${printHeader}
            ${printInfo}
            ${printableContent}
            ${printFooter}
        </div>
    `;

    document.body.innerHTML = fullContent;
    
    window.print();
    
    document.body.innerHTML = originalContents;
    
    initPrint();
    
    location.reload();
}

function generatePrintHeader() {
    const title = document.title || 'تقرير';
    const currentPage = document.querySelector('h1')?.textContent || 'تقرير النظام';
    const companyName = readMeta('gm-company-name') || title || 'تقرير';
    const logoUrl = readMeta('gm-logo-url') || '';
    
    return `
        <div class="print-header">
            <img src="${escapeHtml(logoUrl)}" alt="Logo" class="company-logo" style="max-height: 60px;">
            <h1>${escapeHtml(companyName)}</h1>
            <h2>${escapeHtml(currentPage)}</h2>
        </div>
    `;
}

function generatePrintInfo() {
    const now = new Date();
    const dateStr = now.toLocaleDateString('ar-EG', { 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric' 
    });
    const timeStr = now.toLocaleTimeString('ar-EG');
    
    const currentUser = document.querySelector('[data-username]')?.getAttribute('data-username') || 'غير معروف';
    
    return `
        <div class="print-info">
            <div class="print-info-section">
                <div class="print-info-row">
                    <span class="print-info-label">📅 التاريخ:</span>
                    <span>${escapeHtml(dateStr)}</span>
                </div>
                <div class="print-info-row">
                    <span class="print-info-label">⏰ الوقت:</span>
                    <span>${escapeHtml(timeStr)}</span>
                </div>
            </div>
            <div class="print-info-section">
                <div class="print-info-row">
                    <span class="print-info-label">👤 المستخدم:</span>
                    <span>${escapeHtml(currentUser)}</span>
                </div>
                <div class="print-info-row">
                    <span class="print-info-label">📄 رقم التقرير:</span>
                    <span>${escapeHtml('RPT-' + String(Date.now()))}</span>
                </div>
            </div>
        </div>
    `;
}

function generatePrintFooter() {
    const now = new Date();
    const dateStr = now.toLocaleDateString('ar-EG');
    const timeStr = now.toLocaleTimeString('ar-EG');
    const companyName = readMeta('gm-company-name') || 'النظام';
    
    return `
        <div class="print-footer">
            <p>
                ${escapeHtml(companyName)} © 2025 | 
                تاريخ الطباعة: ${escapeHtml(dateStr)} ${escapeHtml(timeStr)} |
                رام الله - فلسطين
            </p>
        </div>
    `;
}

function printTable(tableId) {
    const table = document.getElementById(tableId);
    
    if (!table) {
        return;
    }

    const clone = table.cloneNode(true);
    
    clone.querySelectorAll('.no-print, .action-column, .btn').forEach(el => el.remove());
    clone.querySelectorAll('script').forEach(el => el.remove());
    
    const printWindow = window.open('', '_blank');
    
    if (!printWindow || !printWindow.document) {
        return;
    }

    const doc = printWindow.document;
    doc.documentElement.setAttribute('dir', 'rtl');
    doc.documentElement.setAttribute('lang', 'ar');
    doc.head.textContent = '';
    doc.body.textContent = '';

    const metaCharset = doc.createElement('meta');
    metaCharset.setAttribute('charset', 'UTF-8');
    doc.head.appendChild(metaCharset);

    const metaViewport = doc.createElement('meta');
    metaViewport.name = 'viewport';
    metaViewport.content = 'width=device-width, initial-scale=1.0';
    doc.head.appendChild(metaViewport);

    const titleEl = doc.createElement('title');
    titleEl.textContent = String(document.title || '');
    doc.head.appendChild(titleEl);

    const cssPrint = doc.createElement('link');
    cssPrint.rel = 'stylesheet';
    cssPrint.href = '/static/css/print.css';
    doc.head.appendChild(cssPrint);

    const cssAdmin = doc.createElement('link');
    cssAdmin.rel = 'stylesheet';
    cssAdmin.href = '/static/adminlte/css/adminlte.min.css';
    doc.head.appendChild(cssAdmin);

    const style = doc.createElement('style');
    style.textContent = `
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            padding: 20px;
            direction: rtl;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            border: 1px solid #000;
            padding: 8px;
            text-align: right;
        }
        th {
            background: #e9ecef;
            font-weight: bold;
        }
    `;
    doc.head.appendChild(style);

    const range = doc.createRange();
    range.selectNode(doc.body);
    const headerFrag = range.createContextualFragment(String(generatePrintHeader() || ''));
    const infoFrag = range.createContextualFragment(String(generatePrintInfo() || ''));
    const footerFrag = range.createContextualFragment(String(generatePrintFooter() || ''));
    doc.body.appendChild(headerFrag);
    doc.body.appendChild(infoFrag);
    doc.body.appendChild(doc.importNode(clone, true));
    doc.body.appendChild(footerFrag);
    
    let printed = false;
    const doPrint = () => {
        if (printed) return;
        printed = true;
        try { printWindow.focus(); } catch (_) {}
        try { printWindow.print(); } catch (_) {}
        setTimeout(() => { try { printWindow.close(); } catch (_) {} }, 300);
    };
    try {
        if (doc.readyState === 'complete') {
            setTimeout(doPrint, 50);
        } else if (typeof printWindow.addEventListener === 'function') {
            printWindow.addEventListener('load', () => setTimeout(doPrint, 50), { once: true });
            setTimeout(doPrint, 400);
        } else {
            setTimeout(doPrint, 50);
        }
    } catch (_) {
        setTimeout(doPrint, 50);
    }
}

function exportToCSV(tableId, filename = 'report.csv') {
    const table = document.getElementById(tableId);
    
  if (!table) {
    return;
  }

    const rows = Array.from(table.querySelectorAll('tr'));
    const csvContent = rows.map(row => {
        const cells = Array.from(row.querySelectorAll('th, td'));
        return cells
            .filter(cell => !cell.classList.contains('no-print') && !cell.classList.contains('action-column'))
            .map(cell => {
                let text = cell.textContent.trim();
                text = text.replace(/"/g, '""');
                return `"${text}"`;
            })
            .join(',');
    }).join('\n');

    const BOM = '\uFEFF';
    const blob = new Blob([BOM + csvContent], { type: 'text/csv;charset=utf-8;' });
    
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    
    URL.revokeObjectURL(link.href);
}

function exportToExcel(tableId, filename = 'report.xlsx') {
    const table = document.getElementById(tableId);
    
  if (!table) {
    return;
  }

    const clone = table.cloneNode(true);
    clone.querySelectorAll('.no-print, .action-column, .btn').forEach(el => el.remove());

    const html = clone.outerHTML;
    const url = 'data:application/vnd.ms-excel,' + encodeURIComponent(html);
    
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
}

function printWithSummary(targetSelector, summaryData) {
    const printContent = document.querySelector(targetSelector);
    
  if (!printContent) {
    return;
  }

    const originalContents = document.body.innerHTML;
    const printableContent = printContent.innerHTML;

    const printHeader = generatePrintHeader();
    const printInfo = generatePrintInfo();
    const printSummary = generatePrintSummary(summaryData);
    const printFooter = generatePrintFooter();

    const fullContent = `
        <div class="print-container">
            ${printHeader}
            ${printInfo}
            ${printSummary}
            ${printableContent}
            ${printFooter}
        </div>
    `;

    document.body.innerHTML = fullContent;
    
    window.print();
    
    document.body.innerHTML = originalContents;
    
    initPrint();
    
    location.reload();
}

function generatePrintSummary(data) {
    if (!data || Object.keys(data).length === 0) {
        return '';
    }

    const rows = Object.entries(data).map(([label, value]) => `
        <div class="print-summary-row">
            <div class="print-summary-label">${label}</div>
            <div class="print-summary-value">${value}</div>
        </div>
    `).join('');

    return `
        <div class="print-summary">
            <h4 style="margin: 0 0 10px 0; text-align: center;">ملخص التقرير</h4>
            ${rows}
        </div>
    `;
}

document.addEventListener('DOMContentLoaded', function() {
    initPrint();
});

window.printReport = printReport;
window.printTable = printTable;
window.exportToCSV = exportToCSV;
window.exportToExcel = exportToExcel;
window.printWithSummary = printWithSummary;


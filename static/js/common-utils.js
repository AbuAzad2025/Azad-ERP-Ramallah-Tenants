(function() {
    if (window.__COMMON_UTILS_INIT__) return;
    window.__COMMON_UTILS_INIT__ = true;

    function stripScripts(html) {
        return String(html || '').replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '');
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function fetchWithTimeout(url, options, timeoutMs) {
        timeoutMs = timeoutMs || 30000;
        var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        var id = controller ? null : setTimeout(function() {}, timeoutMs + 1);
        var opts = options || {};
        if (controller) {
            opts.signal = controller.signal;
            id = setTimeout(function() { controller.abort(); }, timeoutMs);
        }
        return fetch(url, opts).then(function(r) {
            if (id) clearTimeout(id);
            return r;
        }).catch(function(e) {
            if (id) clearTimeout(id);
            throw e;
        });
    }

    function debounce(fn, ms) {
        let timer;
        return function() {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, arguments), ms);
        };
    }

    function toNumber(s) {
        s = String(s || '')
            .replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d))
            .replace(/[٬،\s]/g, '')
            .replace(',', '.');
        const n = parseFloat(s);
        return isNaN(n) ? 0 : n;
    }

    function fmtAmount(v) { 
        const num = toNumber(v);
        return num.toLocaleString('en-US', { 
            minimumFractionDigits: 2, 
            maximumFractionDigits: 2 
        });
    }

    function enableTableSorting(selector) {
        const table = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!table || !table.tHead || !table.tBodies.length) return;
        const headers = Array.from(table.tHead.rows[0].cells);
        headers.forEach((th, index) => {
            if (th.dataset.sortable === 'false') return;
            th.style.cursor = 'pointer';
            let indicator = th.querySelector('.sort-indicator');
            if (!indicator) {
                indicator = document.createElement('span');
                indicator.className = 'sort-indicator ml-1';
                indicator.textContent = '';
                th.appendChild(indicator);
            }
            th.addEventListener('click', function() {
                const direction = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';
                headers.forEach(h => {
                    h.dataset.sortDir = '';
                    const span = h.querySelector('.sort-indicator');
                    if (span) span.textContent = '';
                });
                th.dataset.sortDir = direction;
                indicator.textContent = direction === 'asc' ? '▲' : '▼';
                const tbody = table.tBodies[0];
                const rows = Array.from(tbody.rows);
                const movable = rows.filter(row => row.dataset.sortFixed !== 'true');
                const fixed = rows.filter(row => row.dataset.sortFixed === 'true');
                const multiplier = direction === 'asc' ? 1 : -1;
                movable.sort((aRow, bRow) => {
                    const aCell = aRow.cells[index];
                    const bCell = bRow.cells[index];
                    const aRaw = aCell ? (aCell.dataset.sortValue ?? aCell.textContent.trim()) : '';
                    const bRaw = bCell ? (bCell.dataset.sortValue ?? bCell.textContent.trim()) : '';
                    const aNum = parseFloat(String(aRaw).replace(/[^0-9.-]+/g, ''));
                    const bNum = parseFloat(String(bRaw).replace(/[^0-9.-]+/g, ''));
                    const aNumeric = !isNaN(aNum);
                    const bNumeric = !isNaN(bNum);
                    if (aNumeric && bNumeric) {
                        if (aNum === bNum) return 0;
                        return aNum > bNum ? multiplier : -multiplier;
                    }
                    return String(aRaw).localeCompare(String(bRaw), 'ar', {numeric: true, sensitivity: 'base'}) * multiplier;
                });
                movable.forEach(row => tbody.appendChild(row));
                fixed.forEach(row => tbody.appendChild(row));
            });
        });
    }

    if (typeof window !== 'undefined') {
        window.enableTableSorting = enableTableSorting;
    }

    function formatCurrency(amount, currency = 'ILS') {
        const num = toNumber(amount);
        const formatted = num.toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
        return currency === 'ILS' ? formatted + ' ₪' : formatted + ' ' + currency;
    }

    function badgeForDirection(dir) {
        const v = String(dir || '').toUpperCase();
        return (v === 'IN' || v === 'INCOMING') 
            ? '<span class="badge bg-success">وارد</span>' 
            : '<span class="badge bg-danger">صادر</span>';
    }

    function badgeForStatus(st) {
        const statusMap = {
            'COMPLETED': {cls: 'bg-success', txt: 'مكتملة'},
            'PENDING': {cls: 'bg-warning text-dark', txt: 'قيد الانتظار'},
            'FAILED': {cls: 'bg-danger', txt: 'فاشلة'},
            'REFUNDED': {cls: 'bg-secondary', txt: 'مُرجعة'},
            'CANCELLED': {cls: 'bg-dark', txt: 'ملغية'}
        };
        const s = String(st || '');
        const status = statusMap[s] || {cls: 'bg-secondary', txt: s};
        return `<span class="badge ${status.cls}">${status.txt}</span>`;
    }

    function showAlert(type, message, duration = 0) {
        const alertTypes = {
            'success': 'alert-success',
            'error': 'alert-danger',
            'danger': 'alert-danger',
            'warning': 'alert-warning',
            'info': 'alert-info'
        };
        
        const alertClass = alertTypes[type] || 'alert-info';
        const wrapper = document.createElement('div');
        const alertEl = document.createElement('div');
        alertEl.className = `alert ${alertClass} alert-dismissible fade show position-fixed`;
        alertEl.setAttribute('role', 'alert');
        alertEl.style.top = '80px';
        alertEl.style.left = '50%';
        alertEl.style.transform = 'translateX(-50%)';
        alertEl.style.zIndex = '9999';
        alertEl.style.minWidth = '300px';
        alertEl.style.maxWidth = '600px';
        const text = document.createElement('span');
        text.style.whiteSpace = 'pre-line';
        text.textContent = String(message ?? '');
        alertEl.appendChild(text);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'close';
        closeBtn.setAttribute('data-dismiss', 'alert');
        const closeSpan = document.createElement('span');
        closeSpan.setAttribute('aria-hidden', 'true');
        closeSpan.textContent = '×';
        closeBtn.appendChild(closeSpan);
        closeBtn.addEventListener('click', () => {
            try { alertEl.remove(); } catch (_) {}
            try { wrapper.remove(); } catch (_) {}
        });
        alertEl.appendChild(closeBtn);

        wrapper.appendChild(alertEl);
        document.body.appendChild(wrapper);

        if (duration && duration > 0) {
            setTimeout(() => {
                try { alertEl.remove(); } catch (_) {}
                try { wrapper.remove(); } catch (_) {}
            }, duration);
        }
    }

    function setLoading(selector, isLoading) {
        const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!el) return;
        
        if (isLoading) {
            const colspan = el.tagName === 'TBODY' 
                ? el.closest('table')?.querySelectorAll('thead th').length || 5
                : 1;
            el.innerHTML = `<tr><td colspan="${colspan}" class="text-center text-muted py-4">
                <div class="spinner-border spinner-border-sm me-2"></div>جارِ التحميل…
            </td></tr>`;
        }
    }

    function confirmDelete(entityName, entityId) {
        return confirm(`هل أنت متأكد من حذف ${entityName} #${entityId}؟\n\nهذا الإجراء لا يمكن التراجع عنه!`);
    }

    function exportToCSV(data, filename) {
        const csv = data.map(row => 
            row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')
        ).join('\n');
        
        const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const timestamp = new Date().toISOString().split('T')[0];
        
        a.href = url;
        a.download = `${filename}_${timestamp}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function formatDate(dateString) {
        if (!dateString) return '-';
        const date = new Date(dateString);
        if (isNaN(date)) return dateString;
        return date.toLocaleDateString('ar-SA', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        });
    }

    function formatDateTime(dateString) {
        if (!dateString) return '-';
        const date = new Date(dateString);
        if (isNaN(date)) return dateString;
        return date.toLocaleString('ar-SA', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function deriveEntityLabel(p) {
        const esc = (val) => String(val ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        if (p.service_id) {
            const icon = '<i class="fas fa-wrench text-danger"></i>';
            const vehicle = esc(p.service_vehicle || 'غير محدد');
            const customer = esc(p.service_customer_name || 'غير معروف');
            return `${icon} صيانة المركبة (${vehicle}) للزبون: ${customer}`;
        }
        if (p.entity_display) return esc(p.entity_display);
        
        const entityConfig = {
            customer_id: {icon: 'fas fa-user text-primary', label: 'زبون', badge: 'badge-primary'},
            supplier_id: {icon: 'fas fa-truck text-info', label: 'مورد', badge: 'badge-info'},
            partner_id: {icon: 'fas fa-handshake text-success', label: 'شريك', badge: 'badge-success'},
            sale_id: {icon: 'fas fa-shopping-cart text-warning', label: 'فاتورة مبيعات', badge: 'badge-warning'},
            expense_id: {icon: 'fas fa-receipt text-secondary', label: 'مصروف', badge: 'badge-secondary'},
            shipment_id: {icon: 'fas fa-shipping-fast text-primary', label: 'شحنة', badge: 'badge-primary'},
            preorder_id: {icon: 'fas fa-calendar-check text-info', label: 'طلب مسبق', badge: 'badge-info'},
            loan_settlement_id: {icon: 'fas fa-balance-scale text-warning', label: 'تسوية قرض', badge: 'badge-warning'},
            invoice_id: {icon: 'fas fa-file-invoice text-success', label: 'فاتورة', badge: 'badge-success'}
        };
        
        for (const [key, config] of Object.entries(entityConfig)) {
            if (p[key]) {
                const icon = `<i class="${config.icon}"></i>`;
                const label = `${config.label} #${esc(p[key])}`;
                const badge = `<span class="badge ${config.badge}">${label}</span>`;
                const details = p.reference ? `<br><small class="text-muted">${esc(p.reference)}</small>` : '';
                return icon + ' ' + badge + details;
            }
        }
        
        return esc(p.entity_type || '');
    }

    function normalizeEntity(val) {
        if (!val) return '';
        const enumMap = {
            customer: 'CUSTOMER', supplier: 'SUPPLIER', partner: 'PARTNER',
            sale: 'SALE', service: 'SERVICE', expense: 'EXPENSE',
            loan: 'LOAN', preorder: 'PREORDER', shipment: 'SHIPMENT'
        };
        const k = val.toString().toLowerCase();
        return enumMap[k] || val.toString().toUpperCase();
    }

    function normalizeMethod(v) {
        v = String(v || '').trim();
        if (!v) return '';
        return v.replace(/\s+/g,'_').replace(/-/g,'_').toUpperCase();
    }

    function normDir(v) {
        v = (v || '').toUpperCase();
        if (v === 'IN') return 'INCOMING';
        if (v === 'OUT') return 'OUTGOING';
        return v;
    }

    function validDates(start, end) {
        if (!start || !end) return { start, end };
        const s = new Date(start), e = new Date(end);
        if (isNaN(s) || isNaN(e)) return { start, end };
        if (s.getTime() > e.getTime()) return { start: end, end: start };
        return { start, end };
    }

    function showNotification(message, type) {
        if (arguments.length >= 3) { message = arguments[1]; type = arguments[2]; }
        showAlert(type || 'info', message || '', 5000);
    }

    // Export to global scope
    window.stripScripts = stripScripts;
    window.escapeHtml = escapeHtml;
    window.fetchWithTimeout = fetchWithTimeout;
    window.debounce = debounce;
    window.showNotification = showNotification;
    window.toNumber = toNumber;
    window.fmtAmount = fmtAmount;
    window.enableTableSorting = enableTableSorting;
    window.formatCurrency = formatCurrency;
    window.badgeForDirection = badgeForDirection;
    window.badgeForStatus = badgeForStatus;
    window.showAlert = showAlert;
    window.setLoading = setLoading;
    window.confirmDelete = confirmDelete;
    window.exportToCSV = exportToCSV;
    window.formatDate = formatDate;
    window.formatDateTime = formatDateTime;
    window.deriveEntityLabel = deriveEntityLabel;
    window.normalizeEntity = normalizeEntity;
    window.normalizeMethod = normalizeMethod;
    window.normDir = normDir;
    window.validDates = validDates;

})();
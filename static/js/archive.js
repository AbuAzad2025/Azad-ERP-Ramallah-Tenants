
function archivePayment(paymentId) {
    const reason = prompt('أدخل سبب أرشفة هذه الدفعة:');
    if (!reason) return;
    
    if (confirm('هل أنت متأكد من أرشفة هذه الدفعة؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/payments/archive/${paymentId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        const reasonInput = document.createElement('input');
        reasonInput.type = 'hidden';
        reasonInput.name = 'reason';
        reasonInput.value = reason;
        form.appendChild(csrfToken);
        form.appendChild(reasonInput);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function restorePayment(paymentId) {
    if (confirm('هل أنت متأكد من استعادة هذه الدفعة؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/payments/restore/${paymentId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        form.appendChild(csrfToken);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function archiveSupplier(supplierId) {
    const reason = prompt('أدخل سبب أرشفة هذا المورد:');
    if (!reason) return;
    
    if (confirm('هل أنت متأكد من أرشفة هذا المورد؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/vendors/suppliers/archive/${supplierId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        const reasonInput = document.createElement('input');
        reasonInput.type = 'hidden';
        reasonInput.name = 'reason';
        reasonInput.value = reason;
        form.appendChild(csrfToken);
        form.appendChild(reasonInput);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function restoreSupplier(supplierId) {
    if (confirm('هل أنت متأكد من استعادة هذا المورد؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/vendors/suppliers/restore/${supplierId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        form.appendChild(csrfToken);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function archivePartner(partnerId) {
    const reason = prompt('أدخل سبب أرشفة هذا الشريك:');
    if (!reason) return;
    
    if (confirm('هل أنت متأكد من أرشفة هذا الشريك؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/vendors/partners/archive/${partnerId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        const reasonInput = document.createElement('input');
        reasonInput.type = 'hidden';
        reasonInput.name = 'reason';
        reasonInput.value = reason;
        form.appendChild(csrfToken);
        form.appendChild(reasonInput);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function restorePartner(partnerId) {
    if (confirm('هل أنت متأكد من استعادة هذا الشريك؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/vendors/partners/restore/${partnerId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        form.appendChild(csrfToken);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function archiveSale(saleId) {
    const reason = prompt('أدخل سبب أرشفة هذه المبيعة:');
    if (!reason) return;
    
    if (confirm('هل أنت متأكد من أرشفة هذه المبيعة؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/sales/archive/${saleId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        const reasonInput = document.createElement('input');
        reasonInput.type = 'hidden';
        reasonInput.name = 'reason';
        reasonInput.value = reason;
        form.appendChild(csrfToken);
        form.appendChild(reasonInput);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function restoreSale(saleId) {
    if (confirm('هل أنت متأكد من استعادة هذه المبيعة؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/sales/restore/${saleId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        form.appendChild(csrfToken);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function archiveService(serviceId) {
    const reason = prompt('أدخل سبب أرشفة طلب الصيانة هذا:');
    if (!reason) return;
    
    if (confirm('هل أنت متأكد من أرشفة طلب الصيانة هذا؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/service/archive/${serviceId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        const reasonInput = document.createElement('input');
        reasonInput.type = 'hidden';
        reasonInput.name = 'reason';
        reasonInput.value = reason;
        form.appendChild(csrfToken);
        form.appendChild(reasonInput);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function restoreService(serviceId) {
    if (confirm('هل أنت متأكد من استعادة طلب الصيانة هذا؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/service/restore/${serviceId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        form.appendChild(csrfToken);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function archiveCustomer(customerId) {
    const reason = prompt('أدخل سبب أرشفة هذا العميل:');
    if (!reason) return;
    
    if (confirm('هل أنت متأكد من أرشفة هذا العميل؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/customers/archive/${customerId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        const reasonInput = document.createElement('input');
        reasonInput.type = 'hidden';
        reasonInput.name = 'reason';
        reasonInput.value = reason;
        form.appendChild(csrfToken);
        form.appendChild(reasonInput);
        
        document.body.appendChild(form);
        form.submit();
    }
}

function restoreCustomer(customerId) {
    if (confirm('هل أنت متأكد من استعادة هذا العميل؟')) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/customers/restore/${customerId}`;
        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCSRFToken();
        form.appendChild(csrfToken);
        
        document.body.appendChild(form);
        form.submit();
    }
}

// Generic event delegation for archive/restore buttons
document.addEventListener('DOMContentLoaded', function() {
    // Restore Buttons
    document.body.addEventListener('click', function(e) {
        const btn = e.target.closest('.restore-btn');
        if (btn) {
            e.preventDefault();
            const url = btn.dataset.restoreUrl;
            if (url) {
                if (confirm('هل أنت متأكد من الاستعادة؟')) {
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = url;
                    
                    const csrfToken = document.createElement('input');
                    csrfToken.type = 'hidden';
                    csrfToken.name = 'csrf_token';
                    csrfToken.value = typeof getCSRFToken === 'function' ? getCSRFToken() : 
                              (document.querySelector('input[name="csrf_token"]')?.value || '');
                    
                    form.appendChild(csrfToken);
                    document.body.appendChild(form);
                    form.submit();
                }
            }
        }
    });

    // Archive Buttons
    document.body.addEventListener('click', function(e) {
        const btn = e.target.closest('.archive-btn');
        if (btn) {
            e.preventDefault();
            const url = btn.dataset.archiveUrl;
            if (url) {
                const reason = prompt('أدخل سبب الأرشفة:');
                if (!reason) return;
                
                if (confirm('هل أنت متأكد من الأرشفة؟')) {
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = url;
                    
                    const csrfToken = document.createElement('input');
                    csrfToken.type = 'hidden';
                    csrfToken.name = 'csrf_token';
                    csrfToken.value = typeof getCSRFToken === 'function' ? getCSRFToken() : 
                              (document.querySelector('input[name="csrf_token"]')?.value || '');
                    
                    const reasonInput = document.createElement('input');
                    reasonInput.type = 'hidden';
                    reasonInput.name = 'reason';
                    reasonInput.value = reason;
                    
                    form.appendChild(csrfToken);
                    form.appendChild(reasonInput);
                    
                    document.body.appendChild(form);
                    form.submit();
                }
            }
        }
    });
});

// AI transaction feedback loader. archive.js is loaded globally from base.html,
// so this safely enables smart ERP guidance without editing the large base template.
(function () {
    if (window.__AI_TRANSACTION_FEEDBACK_LOADER__) return;
    window.__AI_TRANSACTION_FEEDBACK_LOADER__ = true;
    function loadFeedbackScript() {
        if (window.showAiTransactionMessage) return;
        var script = document.createElement('script');
        script.src = '/static/js/ai_transaction_feedback.js';
        script.defer = true;
        document.head.appendChild(script);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadFeedbackScript);
    } else {
        loadFeedbackScript();
    }
})();

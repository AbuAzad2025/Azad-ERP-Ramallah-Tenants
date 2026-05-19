(function() {
    if (window.__BALANCE_REALTIME_INIT__) return;

    function ensureSocketIoScript() {
        if (window.__SOCKETIO_ENABLED__ === false) return;
        if (window.io) return;
        if (window.__SOCKET_IO_SCRIPT_LOADING__) return;
        const existing = document.querySelector('script[data-socket-io-loader="1"]');
        if (existing) return;
        window.__SOCKET_IO_SCRIPT_LOADING__ = true;
        const script = document.createElement('script');
        script.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
        script.defer = true;
        script.setAttribute('data-socket-io-loader', '1');
        script.onload = function() {
            window.__SOCKET_IO_SCRIPT_LOADING__ = false;
        };
        script.onerror = function() {
            window.__SOCKET_IO_SCRIPT_LOADING__ = false;
        };
        document.head.appendChild(script);
    }

    let attempts = 0;
    function init() {
        if (window.__BALANCE_REALTIME_INIT__) return;
        if (window.__SOCKETIO_ENABLED__ === false) return;
        if (typeof io === 'undefined') {
            ensureSocketIoScript();
            attempts += 1;
            if (attempts <= 100) {
                setTimeout(init, 100);
            }
            return;
        }

        window.__BALANCE_REALTIME_INIT__ = true;

        const socket = io();

        const statementReloadState = { timer: null };

        function maybeReloadStatement(entityType, entityId) {
            const selectors = {
                customer: ['#statementTable[data-realtime-statement-customer]', 'data-realtime-statement-customer'],
                supplier: ['#supplierStatementTable[data-realtime-statement-supplier]', 'data-realtime-statement-supplier'],
                partner: ['#partnerStatementTable[data-realtime-statement-partner]', 'data-realtime-statement-partner']
            };
            const config = selectors[entityType];
            if (!config) return;
            const table = document.querySelector(config[0]);
            if (!table) return;
            const currentEntityId = Number(table.getAttribute(config[1])) || 0;
            if (currentEntityId !== (Number(entityId) || 0)) return;
            if (statementReloadState.timer) return;
            statementReloadState.timer = setTimeout(() => {
                statementReloadState.timer = null;
                try {
                    window.location.reload();
                } catch (e) {}
            }, 400);
        }
    
        socket.on('balance_updated', function(data) {
            const entityType = data.entity_type;
            const entityId = data.entity_id;
            const newBalance = Number(data.balance) || 0;
            
            const balanceElements = document.querySelectorAll(`[data-balance-${entityType}="${entityId}"]`);
            balanceElements.forEach(balanceElement => {
                if (balanceElement) {
                    const hadBg = balanceElement.classList.contains('badge') || Array.from(balanceElement.classList).some(c => c.startsWith('bg-'));
                    const displayBalance = balanceElement.hasAttribute('data-balance-abs') ? Math.abs(newBalance) : newBalance;
                    const formatted = new Intl.NumberFormat('ar-EG', {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2
                    }).format(displayBalance) + ' ₪';
                    
                    balanceElement.textContent = formatted;
                    
                    balanceElement.classList.remove('bg-danger', 'bg-success', 'bg-secondary', 'text-danger', 'text-success', 'text-secondary');
                    if (newBalance > 0) {
                        balanceElement.classList.add('text-success');
                        if (hadBg) {
                            balanceElement.classList.add('bg-success');
                        }
                    } else if (newBalance < 0) {
                        balanceElement.classList.add('text-danger');
                        if (hadBg) {
                            balanceElement.classList.add('bg-danger');
                        }
                    } else {
                        balanceElement.classList.add('text-secondary');
                        if (hadBg) {
                            balanceElement.classList.add('bg-secondary');
                        }
                    }
                    
                    balanceElement.classList.add('animate__animated', 'animate__pulse');
                    setTimeout(() => {
                        balanceElement.classList.remove('animate__animated', 'animate__pulse');
                    }, 1000);
                }
            });

            maybeReloadStatement(entityType, entityId);
        });
        
        socket.on('balances_summary_updated', function(data) {
            if (data.suppliers) {
                updateSummaryCard('suppliers', data.suppliers);
            }
            if (data.partners) {
                updateSummaryCard('partners', data.partners);
            }
            if (data.customers) {
                updateSummaryCard('customers', data.customers);
            }
        });
        
        function updateSummaryCard(entityType, summaryData) {
            const card = document.getElementById(`${entityType}-summary`);
            if (!card) return;
            
            if (summaryData.total_balance !== undefined) {
                const balanceEl = card.querySelector('.total-balance');
                if (balanceEl) {
                    const balance = Number(summaryData.total_balance) || 0;
                    balanceEl.textContent = balance.toFixed(2) + ' ₪';
                    balanceEl.classList.remove('text-success', 'text-danger', 'text-secondary');
                    const positiveIsSuccess = entityType === 'customers';
                    if (balance > 0) {
                        balanceEl.classList.add(positiveIsSuccess ? 'text-success' : 'text-danger');
                    } else if (balance < 0) {
                        balanceEl.classList.add(positiveIsSuccess ? 'text-danger' : 'text-success');
                    } else {
                        balanceEl.classList.add('text-secondary');
                    }
                }
            }
            
            if (summaryData.count !== undefined) {
                const countEl = card.querySelector('.entity-count');
                if (countEl) {
                    countEl.textContent = Number(summaryData.count) || 0;
                }
            }
        }
    }

    init();
})();


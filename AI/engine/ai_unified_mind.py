"""
AI Unified Mind - العقل الموحد المتكامل
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
import json
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


class UnifiedMind:
    
    def __init__(self):
        self.memory_bank = {}
        self.knowledge_graph = {}
        self.active_context = {}
        self.reasoning_chains = []
        self._initialize_systems()
        self._build_knowledge_graph()
    
    def _initialize_systems(self):
        from AI.engine.ai_integrated_intelligence import get_integrated_intelligence
        from AI.engine.ai_self_evolution import get_evolution_engine
        from AI.engine.ai_learning_system import get_learning_system
        from AI.engine.ai_performance_tracker import get_performance_tracker
        
        self.intelligence = get_integrated_intelligence()
        self.evolution = get_evolution_engine()
        self.learning = get_learning_system()
        self.performance = get_performance_tracker()
        
        self.experts = self.intelligence.experts
        self.knowledge_db = self.intelligence.knowledge_db
    
    def _build_knowledge_graph(self):
        try:
            from extensions import db
            from sqlalchemy import inspect
            
            inspector = inspect(db.engine)
            
            for table_name in inspector.get_table_names():
                columns = inspector.get_columns(table_name)
                fks = inspector.get_foreign_keys(table_name)
                
                self.knowledge_graph[table_name] = {
                    'columns': [c['name'] for c in columns],
                    'relationships': []
                }
                
                for fk in fks:
                    self.knowledge_graph[table_name]['relationships'].append({
                        'to_table': fk['referred_table'],
                        'from_col': fk['constrained_columns'][0] if fk['constrained_columns'] else None,
                        'to_col': fk['referred_columns'][0] if fk['referred_columns'] else None
                    })
        except Exception:
            pass
    
    def think_and_understand(self, query: str, context: Dict) -> Dict[str, Any]:
        self.active_context = context
        self.active_context['original_query'] = query
        
        try:
            from AI.engine.ai_reasoning_engine import get_reasoning_engine
            
            reasoning_engine = get_reasoning_engine()
            reasoned_result = reasoning_engine.reason_through_problem(query, context)
            
            if reasoned_result.get('answer'):
                self._remember(query, reasoned_result, {})
                
                if reasoned_result.get('reasoning_steps'):
                    self._log_reasoning(query, reasoned_result['reasoning_steps'])
                
                return reasoned_result
        
        except Exception as e:
            logger.exception("Reasoning error: %s", e)
        
        understanding = self._deep_understanding(query)
        connected_knowledge = self._connect_knowledge(understanding)
        reasoning = self._reason_through(query, understanding, connected_knowledge)
        answer = self._formulate_answer(reasoning)
        
        if understanding['accounting_related']:
            accounting_check = self._check_accounting_integrity(query, context)
            if accounting_check.get('issues'):
                answer['accounting_warnings'] = accounting_check['issues']
        
        self._remember(query, answer, reasoning)
        
        return answer
    
    def _log_reasoning(self, query: str, steps: List[str]):
        import os
        import json
        
        try:
            os.makedirs('AI/data/reasoning_logs', exist_ok=True)
            
            log_entry = {
                'query': query,
                'steps': steps,
                'timestamp': datetime.now().isoformat()
            }
            
            log_file = 'AI/data/reasoning_logs/reasoning.json'
            logs = []
            
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            
            logs.append(log_entry)
            
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs[-500:], f, ensure_ascii=False, indent=2)
        
        except Exception:
            pass
    
    def _check_accounting_integrity(self, query: str, context: Dict) -> Dict:
        issues = []
        
        search_results = context.get('search_results', {})
        
        if search_results.get('gl_batches'):
            for batch in search_results['gl_batches']:
                if not batch.get('is_balanced'):
                    issues.append({
                        'type': 'unbalanced_batch',
                        'message': f"قيد غير متوازن: Batch #{batch.get('id')}"
                    })
        
        return {'issues': issues}
    
    def _deep_understanding(self, query: str) -> Dict:
        q_lower = query.lower()
        
        understanding = {
            'query': query,
            'intent': self._detect_intent(q_lower),
            'entities': self._extract_entities(q_lower),
            'numbers': self._extract_numbers(query),
            'timeframe': self._detect_timeframe(q_lower),
            'requires_calculation': self._needs_calculation(q_lower),
            'requires_database': self._needs_database(q_lower),
            'accounting_related': self._is_accounting(q_lower)
        }
        
        return understanding
    
    def _detect_intent(self, q_lower: str) -> str:
        if any(w in q_lower for w in ['error', 'خطأ', 'bug']):
            return 'debug'
        if any(w in q_lower for w in ['كيف', 'how', 'steps']):
            return 'learn'
        if any(w in q_lower for w in ['رصيد', 'balance', 'كم']):
            return 'query_balance'
        if any(w in q_lower for w in ['أضف', 'add', 'create']):
            return 'execute_action'
        if any(w in q_lower for w in ['لماذا', 'why', 'اشرح', 'explain']):
            return 'explain'
        if any(w in q_lower for w in ['تقرير', 'report', 'قائمة']):
            return 'report'
        return 'general'
    
    def _extract_entities(self, q_lower: str) -> List[str]:
        entities = []
        
        entity_map = {
            'customer': ['عميل', 'زبون', 'customer'],
            'supplier': ['مورد', 'supplier'],
            'product': ['منتج', 'قطعة', 'بضاعة', 'product'],
            'sale': ['بيع', 'فاتورة', 'sale', 'invoice'],
            'payment': ['دفعة', 'payment', 'دفع'],
            'service': ['صيانة', 'service', 'ورشة'],
            'gl_entry': ['قيد', 'محاسبي', 'gl', 'ledger']
        }
        
        for entity_type, keywords in entity_map.items():
            if any(kw in q_lower for kw in keywords):
                entities.append(entity_type)
        
        return entities
    
    def _extract_numbers(self, query: str) -> List[float]:
        import re
        matches = re.findall(r'\d+(?:\.\d+)?', query)
        return [float(m) for m in matches]
    
    def _detect_timeframe(self, q_lower: str) -> Optional[str]:
        if any(w in q_lower for w in ['اليوم', 'today']):
            return 'today'
        if any(w in q_lower for w in ['الشهر', 'month', 'شهري']):
            return 'month'
        if any(w in q_lower for w in ['السنة', 'year', 'سنوي']):
            return 'year'
        return None
    
    def _needs_calculation(self, q_lower: str) -> bool:
        return any(w in q_lower for w in ['كم', 'how much', 'احسب', 'calculate', 'مجموع', 'total'])
    
    def _needs_database(self, q_lower: str) -> bool:
        return any(w in q_lower for w in ['عميل', 'مورد', 'منتج', 'رصيد', 'فاتورة'])
    
    def _is_accounting(self, q_lower: str) -> bool:
        return any(w in q_lower for w in ['قيد', 'gl', 'محاسبي', 'مدين', 'دائن', 'رصيد', 'balance'])
    
    def _connect_knowledge(self, understanding: Dict) -> Dict:
        connected = {
            'entities_found': [],
            'related_tables': [],
            'related_operations': [],
            'accounting_impact': None
        }
        
        entities = understanding['entities']
        
        for entity_type in entities:
            if entity_type in ['customer', 'supplier']:
                connected['related_tables'].extend(['customers', 'suppliers', 'payments', 'sales'])
                connected['related_operations'].extend(['get_balance', 'get_transactions'])
                
                if understanding['accounting_related']:
                    connected['accounting_impact'] = {
                        'affects_accounts': ['1300_AR', '2300_AP'],
                        'affects_reports': ['balance_sheet', 'trial_balance']
                    }
            
            if entity_type == 'sale':
                connected['related_tables'].extend(['sales', 'sale_lines', 'gl_batches', 'gl_entries'])
                connected['accounting_impact'] = {
                    'creates_gl': True,
                    'affects_accounts': ['1300_AR', '4000_SALES', '2100_VAT'],
                    'affects_stock': True
                }
        
        return connected
    
    def _reason_through(self, query: str, understanding: Dict, connected: Dict) -> Dict:
        reasoning = {
            'steps': [],
            'conclusions': [],
            'data_needed': [],
            'calculations_needed': []
        }
        
        intent = understanding['intent']
        
        if intent == 'query_balance':
            reasoning['steps'] = [
                'تحديد نوع الجهة (عميل/مورد/شريك)',
                'البحث في قاعدة البيانات',
                'حساب الرصيد: (مبيعات + فواتير) - (دفعات)',
                'التحقق من صحة الحساب',
                'عرض النتيجة'
            ]
            reasoning['data_needed'] = ['customers', 'sales', 'payments']
            reasoning['calculations_needed'] = ['sum_sales', 'sum_payments', 'balance']
        
        elif intent == 'explain':
            reasoning['steps'] = [
                'تحديد الرقم المطلوب شرحه',
                'تتبع مصدر الرقم',
                'شرح طريقة الحساب',
                'عرض القيود المحاسبية',
                'التحقق من الدقة'
            ]
        
        elif intent == 'learn':
            reasoning['steps'] = [
                'تحديد الموضوع المطلوب',
                'استدعاء المعرفة من UserGuideMaster',
                'تنظيم الخطوات',
                'إضافة أمثلة',
                'عرض التأثير المحاسبي'
            ]
        
        return reasoning
    
    def _formulate_answer(self, reasoning: Dict) -> Dict:
        query = self.active_context.get('original_query', '')
        
        try:
            from AI.engine.ai_reasoning_engine import get_reasoning_engine
            
            reasoning_engine = get_reasoning_engine()
            reasoned_answer = reasoning_engine.reason_through_problem(query, self.active_context)
            
            if reasoned_answer.get('answer'):
                return reasoned_answer
        except Exception as e:
            logger.exception("Reasoning engine error: %s", e)
        
        result = self.intelligence.process_query(query, self.active_context)
        
        if reasoning.get('calculations_needed'):
            result['calculations'] = reasoning['calculations_needed']
        
        return result
    
    def _remember(self, query: str, answer: Dict, reasoning: Dict):
        self.memory_bank[query] = {
            'answer': answer,
            'reasoning': reasoning,
            'timestamp': datetime.now().isoformat(),
            'confidence': answer.get('confidence', 0.0)
        }
    
    def audit_accounting_operation(self, operation_type: str, data: Dict) -> Dict:
        from AI.engine.ai_accounting_professional import get_professional_accounting_knowledge
        from AI.engine.ai_gl_knowledge import detect_gl_error
        
        audit_result = {
            'operation': operation_type,
            'status': 'valid',
            'errors': [],
            'warnings': [],
            'suggestions': []
        }
        
        if operation_type == 'sale':
            audit_result.update(self._audit_sale(data))
        elif operation_type == 'payment':
            audit_result.update(self._audit_payment(data))
        elif operation_type == 'gl_batch':
            audit_result.update(self._audit_gl_batch(data))
        
        if audit_result['errors']:
            self._send_owner_alert(audit_result)
        
        return audit_result
    
    def _audit_sale(self, sale_data: Dict) -> Dict:
        errors = []
        warnings = []
        
        subtotal = Decimal(str(sale_data.get('subtotal', 0)))
        discount = Decimal(str(sale_data.get('discount', 0)))
        vat = Decimal(str(sale_data.get('vat', 0)))
        total = Decimal(str(sale_data.get('total', 0)))
        
        net = subtotal - discount
        calculated_vat = net * Decimal('0.16')
        calculated_total = net + calculated_vat
        
        if abs(vat - calculated_vat) > Decimal('0.01'):
            errors.append({
                'type': 'vat_calculation_error',
                'severity': 'high',
                'message': f'خطأ في حساب VAT: المتوقع {calculated_vat}, الفعلي {vat}',
                'impact': 'القيد المحاسبي خاطئ'
            })
        
        if abs(total - calculated_total) > Decimal('0.01'):
            errors.append({
                'type': 'total_calculation_error',
                'severity': 'critical',
                'message': f'خطأ في الإجمالي: المتوقع {calculated_total}, الفعلي {total}'
            })
        
        if subtotal == 0:
            warnings.append({
                'type': 'zero_sale',
                'message': 'فاتورة بقيمة صفر - غير منطقي'
            })
        
        customer_id = sale_data.get('customer_id')
        if not customer_id:
            warnings.append({
                'type': 'no_customer',
                'message': 'بيع بدون عميل - قد يكون نقدي'
            })
        
        return {
            'status': 'invalid' if errors else 'valid',
            'errors': errors,
            'warnings': warnings
        }
    
    def _audit_payment(self, payment_data: Dict) -> Dict:
        errors = []
        warnings = []
        
        amount = payment_data.get('amount', 0)
        entity_type = payment_data.get('entity_type')
        entity_id = payment_data.get('entity_id')
        
        if amount <= 0:
            errors.append({
                'type': 'invalid_amount',
                'severity': 'critical',
                'message': 'مبلغ الدفعة صفر أو سالب'
            })
        
        if not entity_type or not entity_id:
            errors.append({
                'type': 'missing_entity',
                'severity': 'high',
                'message': 'دفعة بدون جهة مرتبطة (عميل/مورد)'
            })
        
        return {
            'status': 'invalid' if errors else 'valid',
            'errors': errors,
            'warnings': warnings
        }
    
    def _audit_gl_batch(self, batch_data: Dict) -> Dict:
        errors = []
        
        total_debit = Decimal('0')
        total_credit = Decimal('0')
        
        for entry in batch_data.get('entries', []):
            debit = Decimal(str(entry.get('debit', 0)))
            credit = Decimal(str(entry.get('credit', 0)))
            
            total_debit += debit
            total_credit += credit
        
        if abs(total_debit - total_credit) > Decimal('0.01'):
            errors.append({
                'type': 'unbalanced_batch',
                'severity': 'critical',
                'message': f'قيد غير متوازن: مدين {total_debit} ≠ دائن {total_credit}',
                'difference': float(total_debit - total_credit)
            })
        
        return {
            'status': 'invalid' if errors else 'valid',
            'errors': errors,
            'balanced': total_debit == total_credit
        }
    
    def _send_owner_alert(self, audit_result: Dict):
        try:
            from AI.engine.ai_realtime_monitor import get_realtime_monitor
            
            monitor = get_realtime_monitor()
            
            for error in audit_result['errors']:
                monitor.add_alert(
                    alert_type='accounting_error',
                    severity='critical',
                    message=f"خطأ محاسبي: {error['message']}",
                    action='مراجعة فورية',
                    data=audit_result
                )
        except Exception:
            pass
    
    def connect_data(self, entity_type: str, entity_id: int) -> Dict:
        from extensions import db
        from models import Customer, Sale, Payment, GLEntry
        
        connections = {
            'entity': {'type': entity_type, 'id': entity_id},
            'related_data': {},
            'calculations': {},
            'accounting_view': {}
        }
        
        if entity_type == 'customer':
            customer = db.session.get(Customer, entity_id)
            if not customer:
                return connections
            
            sales = Sale.query.filter_by(customer_id=entity_id).all()
            payments = Payment.query.filter_by(
                entity_type='customer',
                entity_id=entity_id
            ).all()
            
            total_sales = sum(Decimal(str(s.total_amount or 0)) for s in sales)
            total_payments = sum(Decimal(str(p.amount or 0)) for p in payments)
            balance = total_sales - total_payments
            
            connections['related_data'] = {
                'sales_count': len(sales),
                'payments_count': len(payments),
                'recent_sales': [
                    {
                        'id': s.id,
                        'date': s.sale_date.isoformat() if s.sale_date else None,
                        'total': float(s.total_amount or 0)
                    }
                    for s in sales[:5]
                ]
            }
            
            connections['calculations'] = {
                'total_sales': float(total_sales),
                'total_payments': float(total_payments),
                'balance': float(balance),
                'balance_interpretation': 'عليه' if balance > 0 else 'له' if balance < 0 else 'متعادل'
            }
            
            connections['accounting_view'] = {
                'account': '1300_ACCOUNTS_RECEIVABLE',
                'debit': float(total_sales),
                'credit': float(total_payments),
                'net': float(balance)
            }
        
        return connections
    
    def explain_number_deeply(self, number: float, context: str) -> Dict:
        explanation = {
            'number': number,
            'context': context,
            'origin': [],
            'calculation': [],
            'components': [],
            'verification': {}
        }
        
        if 'رصيد' in context or 'balance' in context:
            explanation['origin'].append('هذا الرصيد من الفرق بين المبيعات والدفعات')
            explanation['calculation'].append('الرصيد = المبيعات - الدفعات')
            explanation['components'] = [
                'المبيعات (مدين)',
                'الدفعات (دائن)',
                'الفرق = الرصيد'
            ]
        
        elif 'vat' in context.lower() or 'ضريبة' in context:
            explanation['origin'].append('ضريبة القيمة المضافة 16%')
            explanation['calculation'].append('VAT = الصافي × 0.16')
        
        return explanation


_unified_mind = None

def get_unified_mind():
    global _unified_mind
    if _unified_mind is None:
        _unified_mind = UnifiedMind()
    return _unified_mind


__all__ = ['UnifiedMind', 'get_unified_mind']


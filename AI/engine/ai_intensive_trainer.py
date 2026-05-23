from typing import Dict, List, Any
from datetime import datetime
import json
import os
from pathlib import Path
import time


class IntensiveTrainer:
    
    def __init__(self):
        self.training_dir = Path('AI/data/intensive_training')
        self.training_dir.mkdir(parents=True, exist_ok=True)
        
        self.training_status = {
            'running': False,
            'progress': 0,
            'current_phase': '',
            'total_phases': 10,
            'items_learned': 0,
            'started_at': None,
            'estimated_completion': None,
            'errors': []
        }
        
        self.knowledge_accumulated = {}
    
    def start_intensive_training(self, hours: int = 2):
        self.training_status['running'] = True
        self.training_status['started_at'] = datetime.now().isoformat()
        self.training_status['progress'] = 0
        self.training_status['items_learned'] = 0
        self.training_status['errors'] = []
        
        try:
            self.training_status['current_phase'] = 'Phase 1: Database Deep Study'
            self.training_status['progress'] = 10
            self._save_status()
            phase1 = self._phase1_database_deep_study()
            
            self.training_status['current_phase'] = 'Phase 2: Models Complete Analysis'
            self.training_status['progress'] = 20
            self._save_status()
            phase2 = self._phase2_models_complete_analysis()
            
            self.training_status['current_phase'] = 'Phase 3: Routes and Business Logic'
            self.training_status['progress'] = 30
            self._save_status()
            phase3 = self._phase3_routes_business_logic()
            
            self.training_status['current_phase'] = 'Phase 4: Forms and Validations'
            self.training_status['progress'] = 40
            self._save_status()
            phase4 = self._phase4_forms_validations()
            
            self.training_status['current_phase'] = 'Phase 5: Templates and Frontend'
            self.training_status['progress'] = 50
            self._save_status()
            phase5 = self._phase5_templates_frontend()
            
            self.training_status['current_phase'] = 'Phase 6: Accounting System'
            self.training_status['progress'] = 60
            self._save_status()
            phase6 = self._phase6_accounting_system()
            
            self.training_status['current_phase'] = 'Phase 7: User Guide and Workflows'
            self.training_status['progress'] = 70
            self._save_status()
            phase7 = self._phase7_user_guide_workflows()
            
            self.training_status['current_phase'] = 'Phase 8: Common Queries Practice'
            self.training_status['progress'] = 80
            self._save_status()
            phase8 = self._phase8_common_queries_practice()
            
            self.training_status['current_phase'] = 'Phase 9: Integration and Relationships'
            self.training_status['progress'] = 90
            self._save_status()
            phase9 = self._phase9_integration_relationships()
            
            self.training_status['current_phase'] = 'Phase 10: Final Consolidation'
            self.training_status['progress'] = 95
            self._save_status()
            phase10 = self._phase10_final_consolidation()
            
            self.training_status['progress'] = 100
            self.training_status['current_phase'] = 'Training Complete'
            self.training_status['running'] = False
            self.training_status['completed_at'] = datetime.now().isoformat()
            self._save_status()
            
            return {
                'success': True,
                'total_items_learned': self.training_status['items_learned'],
                'duration': self._calculate_duration(),
                'knowledge_size': len(self.knowledge_accumulated)
            }
        
        except Exception as e:
            self.training_status['running'] = False
            self.training_status['errors'].append(str(e))
            self._save_status()
            raise
    
    def _phase1_database_deep_study(self) -> Dict:
        phase_data = {
            'name': 'Database Deep Study',
            'items': 0,
            'details': {}
        }
        
        try:
            from extensions import db
            from sqlalchemy import inspect
            from AI.engine.ai_deep_memory import get_deep_memory
            
            memory = get_deep_memory()
            inspector = inspect(db.engine)
            
            for table_name in inspector.get_table_names():
                columns = inspector.get_columns(table_name)
                foreign_keys = inspector.get_foreign_keys(table_name)
                pk = inspector.get_pk_constraint(table_name)
                indexes = inspector.get_indexes(table_name)
                
                table_knowledge = {
                    'table_name': table_name,
                    'columns': len(columns),
                    'foreign_keys': len(foreign_keys),
                    'has_primary_key': bool(pk and pk.get('constrained_columns')),
                    'indexes': len(indexes)
                }
                
                memory.remember_fact(
                    f'database_table',
                    table_name,
                    table_knowledge,
                    importance=9
                )
                
                for col in columns:
                    col_key = f'{table_name}.{col["name"]}'
                    memory.remember_fact(
                        'database_column',
                        col_key,
                        {
                            'type': str(col['type']),
                            'nullable': col.get('nullable'),
                            'default': str(col.get('default')) if col.get('default') else None
                        },
                        importance=7
                    )
                
                for fk in foreign_keys:
                    fk_key = f'{table_name}_to_{fk["referred_table"]}'
                    memory.remember_fact(
                        'database_relationship',
                        fk_key,
                        {
                            'from_table': table_name,
                            'to_table': fk['referred_table'],
                            'columns': fk['constrained_columns']
                        },
                        importance=8
                    )
                
                phase_data['items'] += 1 + len(columns) + len(foreign_keys)
                self.training_status['items_learned'] += 1 + len(columns) + len(foreign_keys)
            
            phase_data['details'] = {
                'tables_studied': len(inspector.get_table_names())
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase2_models_complete_analysis(self) -> Dict:
        phase_data = {
            'name': 'Models Complete Analysis',
            'items': 0,
            'details': {}
        }
        
        try:
            from extensions import db
            from AI.engine.ai_deep_memory import get_deep_memory
            
            memory = get_deep_memory()
            
            for mapper in db.Model.registry.mappers:
                model_class = mapper.class_
                model_name = model_class.__name__
                
                model_knowledge = {
                    'name': model_name,
                    'table': model_class.__tablename__ if hasattr(model_class, '__tablename__') else None,
                    'columns': [c.name for c in mapper.columns],
                    'relationships': list(mapper.relationships.keys())
                }
                
                memory.remember_concept(
                    f'Model: {model_name}',
                    f'نموذج بيانات {model_name}',
                    examples=[f'يحتوي على {len(model_knowledge["columns"])} حقل'],
                    related=model_knowledge['relationships']
                )
                
                for rel_name, relationship in mapper.relationships.items():
                    target_model = relationship.entity.class_.__name__
                    
                    memory.remember_fact(
                        'model_relationship',
                        f'{model_name}.{rel_name}',
                        {
                            'source': model_name,
                            'target': target_model,
                            'type': relationship.direction.name
                        },
                        importance=8
                    )
                
                phase_data['items'] += 1 + len(mapper.relationships)
                self.training_status['items_learned'] += 1 + len(mapper.relationships)
            
            phase_data['details'] = {
                'models_analyzed': len(list(db.Model.registry.mappers))
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase3_routes_business_logic(self) -> Dict:
        phase_data = {
            'name': 'Routes and Business Logic',
            'items': 0,
            'details': {}
        }
        
        try:
            from flask import current_app, has_app_context
            if not has_app_context():
                raise RuntimeError("No app context")
            from AI.engine.ai_deep_memory import get_deep_memory
            
            memory = get_deep_memory()
            
            routes_by_blueprint = {}
            
            for rule in current_app.url_map.iter_rules():
                if rule.endpoint != 'static':
                    endpoint_parts = rule.endpoint.split('.')
                    blueprint = endpoint_parts[0] if len(endpoint_parts) > 1 else 'main'
                    
                    if blueprint not in routes_by_blueprint:
                        routes_by_blueprint[blueprint] = []
                    
                    routes_by_blueprint[blueprint].append({
                        'path': str(rule.rule),
                        'endpoint': rule.endpoint,
                        'methods': list(rule.methods - {'HEAD', 'OPTIONS'})
                    })
                    
                    memory.remember_procedure(
                        f'Route: {rule.endpoint}',
                        [
                            f'المسار: {rule.rule}',
                            f'الطرق المسموحة: {", ".join(rule.methods - {"HEAD", "OPTIONS"})}',
                            f'المخطط: {blueprint}'
                        ],
                        context={'blueprint': blueprint, 'path': str(rule.rule)}
                    )
                    
                    phase_data['items'] += 1
                    self.training_status['items_learned'] += 1
            
            phase_data['details'] = {
                'total_routes': sum(len(routes) for routes in routes_by_blueprint.values()),
                'blueprints': len(routes_by_blueprint)
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase4_forms_validations(self) -> Dict:
        phase_data = {
            'name': 'Forms and Validations',
            'items': 0,
            'details': {}
        }
        
        try:
            from AI.engine.ai_deep_memory import get_deep_memory
            import re
            
            memory = get_deep_memory()
            forms_dir = Path('forms')
            
            if forms_dir.exists():
                for form_file in forms_dir.glob('*.py'):
                    if form_file.name == '__init__.py':
                        continue
                    
                    with open(form_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    class_matches = re.findall(r'class\s+(\w+Form)\s*\(', content)
                    
                    for form_class in class_matches:
                        fields = re.findall(r'(\w+)\s*=\s*(?:StringField|IntegerField|SelectField|BooleanField|TextAreaField|DateField|DecimalField)', content)
                        
                        memory.remember_concept(
                            f'Form: {form_class}',
                            f'نموذج إدخال بيانات {form_class}',
                            examples=[f'يحتوي على {len(fields)} حقل'] if fields else [],
                            related=['WTForms', 'Flask']
                        )
                        
                        phase_data['items'] += 1
                        self.training_status['items_learned'] += 1
            
            phase_data['details'] = {
                'forms_analyzed': phase_data['items']
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase5_templates_frontend(self) -> Dict:
        phase_data = {
            'name': 'Templates and Frontend',
            'items': 0,
            'details': {}
        }
        
        try:
            from AI.engine.ai_deep_memory import get_deep_memory
            
            memory = get_deep_memory()
            templates_dir = Path('templates')
            
            if templates_dir.exists():
                for template_file in templates_dir.rglob('*.html'):
                    template_path = str(template_file.relative_to(templates_dir))
                    
                    memory.remember_fact(
                        'template',
                        template_path,
                        {
                            'path': template_path,
                            'size': template_file.stat().st_size
                        },
                        importance=6
                    )
                    
                    phase_data['items'] += 1
                    self.training_status['items_learned'] += 1
            
            phase_data['details'] = {
                'templates_found': phase_data['items']
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase6_accounting_system(self) -> Dict:
        phase_data = {
            'name': 'Accounting System',
            'items': 0,
            'details': {}
        }
        
        try:
            from AI.engine.ai_deep_memory import get_deep_memory
            from AI.engine.ai_comprehension_engine import get_comprehension_engine
            
            memory = get_deep_memory()
            comp = get_comprehension_engine()
            
            accounting_concepts = [
                'قيد محاسبي',
                'دفتر الأستاذ',
                'رصيد',
                'مدين',
                'دائن',
                'VAT',
                'ذمم الزبائن',
                'ذمم الموردين',
                'المبيعات',
                'المشتريات',
                'الخصم',
                'فاتورة'
            ]
            
            for concept in accounting_concepts:
                understanding = comp.understand_concept(concept)
                
                memory.remember_concept(
                    concept,
                    understanding['what'],
                    examples=understanding['examples'],
                    related=understanding['relationships']
                )
                
                phase_data['items'] += 1
                self.training_status['items_learned'] += 1
            
            phase_data['details'] = {
                'concepts_learned': len(accounting_concepts)
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase7_user_guide_workflows(self) -> Dict:
        phase_data = {
            'name': 'User Guide and Workflows',
            'items': 0,
            'details': {}
        }
        
        try:
            from AI.engine.ai_deep_memory import get_deep_memory
            
            memory = get_deep_memory()
            
            workflows = {
                'إضافة زبون': [
                    'الذهاب إلى /customers/create',
                    'إدخال الاسم (إجباري)',
                    'إدخال رقم الهاتف (إجباري وفريد)',
                    'إدخال البريد الإلكتروني (اختياري)',
                    'إدخال العنوان (اختياري)',
                    'إدخال الرصيد الافتتاحي (اختياري)',
                    'الضغط على حفظ'
                ],
                'إنشاء فاتورة بيع': [
                    'الذهاب إلى /sales/create',
                    'اختيار الزبون',
                    'إضافة المنتجات',
                    'تحديد الكمية لكل منتج',
                    'إدخال الخصم (اختياري)',
                    'التحقق من حساب VAT التلقائي',
                    'الضغط على حفظ',
                    'يتم إنشاء القيد المحاسبي تلقائياً'
                ],
                'تسجيل دفعة': [
                    'الذهاب إلى /payments/create',
                    'اختيار الزبون أو المورد',
                    'تحديد نوع الدفعة (IN/OUT)',
                    'إدخال المبلغ',
                    'اختيار طريقة الدفع (نقدي، بطاقة، شيك)',
                    'إضافة ملاحظات (اختياري)',
                    'الضغط على حفظ',
                    'يتحدث الرصيد تلقائياً'
                ]
            }
            
            for workflow_name, steps in workflows.items():
                memory.remember_procedure(
                    workflow_name,
                    steps,
                    context={'category': 'user_workflow'}
                )
                
                phase_data['items'] += 1
                self.training_status['items_learned'] += 1
            
            phase_data['details'] = {
                'workflows_learned': len(workflows)
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase8_common_queries_practice(self) -> Dict:
        phase_data = {
            'name': 'Common Queries Practice',
            'items': 0,
            'details': {}
        }
        
        try:
            from AI.engine.ai_reasoning_engine import get_reasoning_engine
            from AI.engine.ai_deep_memory import get_deep_memory
            
            reasoning = get_reasoning_engine()
            memory = get_deep_memory()
            
            practice_queries = [
                'كيف أضيف زبون؟',
                'ما هو القيد المحاسبي للبيع؟',
                'كيف أحسب VAT؟',
                'ما هو الرصيد؟',
                'كيف أضيف منتج؟',
                'ما هي ذمم الزبائن؟',
                'كيف أسجل دفعة؟',
                'ما الفرق بين المدين والدائن؟',
                'كيف أنشئ فاتورة؟',
                'ما هو دفتر الأستاذ؟'
            ]
            
            for query in practice_queries:
                result = reasoning.reason_through_problem(query, {})
                
                if result.get('answer'):
                    memory.remember_experience(
                        query,
                        result['answer'][:200],
                        ['تم التدرب على هذا السؤال']
                    )
                    
                    phase_data['items'] += 1
                    self.training_status['items_learned'] += 1
            
            phase_data['details'] = {
                'queries_practiced': len(practice_queries)
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase9_integration_relationships(self) -> Dict:
        phase_data = {
            'name': 'Integration and Relationships',
            'items': 0,
            'details': {}
        }
        
        try:
            from AI.engine.ai_deep_memory import get_deep_memory
            
            memory = get_deep_memory()
            
            integrations = {
                'زبون_مبيعات': 'الزبون مرتبط بالمبيعات عبر customer_id',
                'زبون_دفعات': 'الزبون مرتبط بالدفعات لتسديد رصيده',
                'زبون_سيارات': 'الزبون يملك سيارة أو أكثر',
                'زبون_رصيد': 'رصيد الزبون = (الدفعات) - (المبيعات)',
                'بيع_قيد': 'البيع يُنشئ قيد محاسبي تلقائياً',
                'بيع_vat': 'البيع يحسب VAT تلقائياً (16%)',
                'دفعة_رصيد': 'الدفعة تحدث رصيد الزبون فوراً',
                'منتج_مخزون': 'المنتج له رصيد في المخزون',
                'بيع_مخزون': 'البيع يخصم من المخزون',
                'قيد_حسابات': 'القيد يؤثر على حسابات دفتر الأستاذ'
            }
            
            for integration_name, description in integrations.items():
                memory.remember_concept(
                    integration_name,
                    description,
                    examples=[],
                    related=integration_name.split('_')
                )
                
                phase_data['items'] += 1
                self.training_status['items_learned'] += 1
            
            phase_data['details'] = {
                'integrations_learned': len(integrations)
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _phase10_final_consolidation(self) -> Dict:
        phase_data = {
            'name': 'Final Consolidation',
            'items': 0,
            'details': {}
        }
        
        try:
            from AI.engine.ai_deep_memory import get_deep_memory
            
            memory = get_deep_memory()
            
            consolidated = memory.consolidate_memory()
            
            phase_data['items'] = consolidated
            phase_data['details'] = {
                'memory_consolidated': consolidated,
                'memory_stats': memory.get_memory_stats()
            }
        
        except Exception as e:
            phase_data['error'] = str(e)
        
        return phase_data
    
    def _save_status(self):
        status_file = self.training_dir / 'current_status.json'
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(self.training_status, f, ensure_ascii=False, indent=2)
    
    def get_status(self) -> Dict:
        return self.training_status.copy()
    
    def _calculate_duration(self):
        if self.training_status.get('started_at') and self.training_status.get('completed_at'):
            start = datetime.fromisoformat(self.training_status['started_at'])
            end = datetime.fromisoformat(self.training_status['completed_at'])
            duration = (end - start).total_seconds()
            return f'{duration:.2f} seconds'
        return 'Unknown'


_intensive_trainer = None

def get_intensive_trainer():
    global _intensive_trainer
    if _intensive_trainer is None:
        _intensive_trainer = IntensiveTrainer()
    return _intensive_trainer


__all__ = ['IntensiveTrainer', 'get_intensive_trainer']


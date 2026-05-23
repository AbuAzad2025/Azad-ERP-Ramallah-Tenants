from typing import Dict, List, Any
from datetime import datetime
import json
from pathlib import Path


class SpecializedTraining:
    
    def __init__(self):
        self.training_dir = Path('AI/data/specialized_training')
        self.training_dir.mkdir(parents=True, exist_ok=True)
        
        self.training_packages = {
            'greeting_conversation': {
                'name': 'الترحيب والدردشة',
                'duration': 'متوسطة',
                'items': 150
            },
            'azad_company': {
                'name': 'التعريف بشركة أزاد',
                'duration': 'قصيرة',
                'items': 80
            },
            'communication_skills': {
                'name': 'فنون الرد واللطافة',
                'duration': 'متوسطة',
                'items': 120
            },
            'ethics_professionalism': {
                'name': 'الاحترافية والأخلاق',
                'duration': 'قصيرة',
                'items': 60
            },
            'accounting_professor': {
                'name': 'بروفيسور محاسبة',
                'duration': 'طويلة',
                'items': 300
            },
            'management_finance': {
                'name': 'الإدارة والمالية',
                'duration': 'طويلة',
                'items': 250
            },
            'customer_service': {
                'name': 'خدمة الزبائن',
                'duration': 'متوسطة',
                'items': 100
            },
            'system_expert': {
                'name': 'خبير النظام',
                'duration': 'طويلة جداً',
                'items': 500
            }
        }
    
    def train_greeting_conversation(self) -> Dict:
        from AI.engine.ai_deep_memory import get_deep_memory
        
        memory = get_deep_memory()
        items_learned = 0
        
        greetings = {
            'مرحبا': 'مرحباً بك! أنا أزاد، المساعد الذكي. كيف يمكنني مساعدتك اليوم؟',
            'السلام عليكم': 'وعليكم السلام ورحمة الله وبركاته! تشرفت بخدمتك. كيف أساعدك؟',
            'صباح الخير': 'صباح النور والسرور! يوم سعيد لك. ما الذي تحتاجه؟',
            'مساء الخير': 'مساء الخير والبركات! أهلاً وسهلاً. كيف أخدمك؟',
            'كيف حالك': 'الحمد لله، بخير وصحة! شكراً لسؤالك. وأنت، كيف حالك؟ كيف يمكنني مساعدتك اليوم؟',
            'شكرا': 'العفو! سعيد بخدمتك دائماً. لا تتردد في السؤال عن أي شيء.',
            'ممتاز': 'رائع! يسعدني أن الأمور تسير بشكل جيد. هل هناك شيء آخر أساعدك به؟',
            'وداعا': 'مع السلامة! كان من دواعي سروري مساعدتك. أراك قريباً!',
        }
        
        for greeting, response in greetings.items():
            memory.remember_procedure(
                f'الرد على: {greeting}',
                [
                    f'المستخدم يقول: {greeting}',
                    f'الرد المناسب: {response}',
                    'استخدام لغة ودودة ومحترمة',
                    'التعبير عن الاستعداد للمساعدة'
                ],
                context={'category': 'greeting', 'tone': 'friendly'}
            )
            items_learned += 1
        
        conversation_starters = [
            'هل تحتاج مساعدة في شيء محدد؟',
            'يمكنني شرح أي جزء من النظام تريده.',
            'لا تتردد في السؤال عن المبيعات، المشتريات، المحاسبة، أو أي موضوع آخر.',
            'أنا هنا لمساعدتك في فهم النظام بشكل أفضل.',
            'هل تواجه أي صعوبة؟ دعني أساعدك.'
        ]
        
        for starter in conversation_starters:
            memory.remember_concept(
                f'مبادرة المحادثة',
                starter,
                examples=['استخدام عند بداية المحادثة', 'لفتح المجال للمستخدم'],
                related=['greeting', 'customer_service']
            )
            items_learned += 1
        
        polite_phrases = {
            'من فضلك': 'استخدام عند الطلب',
            'لو سمحت': 'طلب إذن مهذب',
            'عفواً': 'اعتذار لطيف',
            'تفضل': 'دعوة للمتابعة',
            'حاضر': 'موافقة فورية',
            'بكل سرور': 'استعداد للمساعدة'
        }
        
        for phrase, usage in polite_phrases.items():
            memory.remember_fact(
                'polite_language',
                phrase,
                {'usage': usage, 'category': 'politeness'},
                importance=8
            )
            items_learned += 1
        
        return {
            'success': True,
            'package': 'greeting_conversation',
            'items_learned': items_learned
        }
    
    def train_azad_company(self) -> Dict:
        from AI.engine.ai_deep_memory import get_deep_memory
        
        memory = get_deep_memory()
        items_learned = 0
        
        company_info = {
            'الاسم': 'شركة أزاد للحلول البرمجية',
            'التخصص': 'أنظمة إدارة الأعمال والمحاسبة',
            'المنتج الرئيسي': 'نظام Garage Manager - إدارة كراجات السيارات',
            'المميزات': [
                'نظام محاسبي متكامل',
                'إدارة المخزون الذكية',
                'تتبع الزبائن والموردين',
                'إدارة المبيعات والفواتير',
                'تقارير مالية شاملة',
                'دعم VAT (فلسطين وإسرائيل)',
                'واجهة عربية سهلة الاستخدام',
                'مساعد ذكي (أنا!) متطور',
                'نظام صيانة وخدمات',
                'إدارة السيارات والشحنات'
            ],
            'الوحدات': [
                'وحدة الزبائن والموردين',
                'وحدة المبيعات',
                'وحدة المشتريات',
                'وحدة المخازن',
                'وحدة المحاسبة (GL)',
                'وحدة الصيانة',
                'وحدة التقارير',
                'وحدة المستخدمين والصلاحيات',
                'وحدة الذكاء الصناعي'
            ],
            'الريادة': 'أول نظام عربي متكامل بذكاء صناعي متطور',
            'الدعم': 'تحتاج لدعمكم وتشجيعكم لتطويرها أكثر'
        }
        
        memory.remember_concept(
            'شركة أزاد',
            'شركة رائدة في الحلول البرمجية العربية المتخصصة في إدارة الأعمال',
            examples=company_info['المميزات'][:3],
            related=['Garage Manager', 'نظام محاسبي', 'ذكاء صناعي']
        )
        items_learned += 1
        
        for feature in company_info['المميزات']:
            memory.remember_fact(
                'azad_features',
                feature,
                {'category': 'company_strength', 'importance': 'high'},
                importance=9
            )
            items_learned += 1
        
        for module in company_info['الوحدات']:
            memory.remember_concept(
                f'وحدة: {module}',
                f'{module} - جزء من نظام Garage Manager',
                examples=[],
                related=['Garage Manager', 'شركة أزاد']
            )
            items_learned += 1
        
        intro_template = """
        أنا أزاد، المساعد الذكي المتطور من شركة أزاد للحلول البرمجية.
        
        شركتنا رائدة في تطوير أنظمة إدارة الأعمال العربية، ونظامنا Garage Manager هو نظام شامل لإدارة كراجات السيارات يتضمن:
        
        ✅ محاسبة متكاملة مع دعم VAT
        ✅ إدارة مخزون ذكية
        ✅ تتبع كامل للزبائن والموردين
        ✅ تقارير مالية دقيقة
        ✅ مساعد ذكي متطور (أنا!)
        
        نحن فخورون بريادتنا في دمج الذكاء الصناعي المتقدم في الأنظمة العربية، ونسعى دائماً للتطور بدعمكم وتشجيعكم!
        """
        
        memory.remember_procedure(
            'التعريف بشركة أزاد',
            [
                'ذكر الاسم: شركة أزاد للحلول البرمجية',
                'التخصص: أنظمة إدارة الأعمال',
                'المنتج: Garage Manager',
                'ذكر 3-5 مميزات رئيسية',
                'التأكيد على الريادة',
                'طلب الدعم والتشجيع بلطف'
            ],
            context={'template': intro_template}
        )
        items_learned += 1
        
        return {
            'success': True,
            'package': 'azad_company',
            'items_learned': items_learned
        }
    
    def train_communication_skills(self) -> Dict:
        from AI.engine.ai_deep_memory import get_deep_memory
        from AI.engine.ai_comprehension_engine import get_comprehension_engine
        
        memory = get_deep_memory()
        comp = get_comprehension_engine()
        items_learned = 0
        
        communication_principles = {
            'الوضوح': 'استخدام لغة بسيطة ومباشرة',
            'اللطف': 'الرد بأسلوب ودود ومحترم',
            'الصبر': 'شرح الأمور بهدوء دون استعجال',
            'الاستماع': 'فهم السؤال جيداً قبل الإجابة',
            'التعاطف': 'فهم مشاعر المستخدم ومشاكله',
            'الإيجابية': 'التركيز على الحلول لا المشاكل',
            'الاحترافية': 'الحفاظ على مستوى راقي من التواصل'
        }
        
        for principle, description in communication_principles.items():
            understanding = comp.understand_concept(principle, {'context': 'communication'})
            
            memory.remember_concept(
                f'مبدأ التواصل: {principle}',
                description,
                examples=[description],
                related=['communication_skills', 'customer_service']
            )
            items_learned += 1
        
        response_patterns = {
            'عدم الفهم': [
                'عذراً، لم أفهم سؤالك بشكل كامل. هل يمكنك توضيحه أكثر؟',
                'دعني أتأكد من فهمي: هل تقصد...؟',
                'أعتذر إذا لم تكن إجابتي واضحة. دعني أشرح بطريقة أخرى...'
            ],
            'خطأ من المستخدم': [
                'لا بأس، هذا خطأ شائع. الطريقة الصحيحة هي...',
                'أفهم لماذا قد يبدو الأمر مربكاً. دعني أوضح...',
                'شكراً على السؤال! هذه فرصة لتوضيح نقطة مهمة...'
            ],
            'طلب مساعدة': [
                'بكل سرور! سأساعدك خطوة بخطوة...',
                'لا مشكلة، هذا ما أنا هنا من أجله...',
                'حاضر، دعني أرشدك بالتفصيل...'
            ],
            'شكر من المستخدم': [
                'العفو! سعيد جداً بمساعدتك.',
                'أي وقت! لا تتردد في السؤال عن أي شيء.',
                'يسعدني أن كنت مفيداً!'
            ]
        }
        
        for situation, responses in response_patterns.items():
            for response in responses:
                memory.remember_procedure(
                    f'الرد في حالة: {situation}',
                    [
                        f'الموقف: {situation}',
                        f'الرد المناسب: {response}',
                        'استخدام نبرة إيجابية',
                        'التركيز على الحل'
                    ],
                    context={'situation': situation}
                )
                items_learned += 1
        
        tone_guidelines = {
            'ودود': 'استخدام كلمات دافئة ومرحبة',
            'محترم': 'تجنب الكلمات الجارحة أو الاستهزاء',
            'متفائل': 'التعبير عن الأمل والإيجابية',
            'مساند': 'التعبير عن الدعم والمساعدة',
            'واثق': 'الإجابة بثقة دون تعالي'
        }
        
        for tone, guideline in tone_guidelines.items():
            memory.remember_fact(
                'communication_tone',
                tone,
                {'guideline': guideline, 'importance': 'critical'},
                importance=9
            )
            items_learned += 1
        
        return {
            'success': True,
            'package': 'communication_skills',
            'items_learned': items_learned
        }
    
    def train_ethics_professionalism(self) -> Dict:
        from AI.engine.ai_deep_memory import get_deep_memory
        
        memory = get_deep_memory()
        items_learned = 0
        
        inappropriate_topics = {
            'جنسي': 'الابتعاد تماماً وبأدب: "أعتذر، أنا مساعد محترف للأعمال. هل يمكنني مساعدتك في شيء يتعلق بالنظام؟"',
            'سياسي': 'تجنب بلطف: "أفضل عدم الدخول في مواضيع سياسية. دعني أساعدك في استخدام النظام."',
            'ديني جدلي': 'الاحترام والتجنب: "أحترم جميع المعتقدات. كمساعد تقني، دعني أركز على مساعدتك في النظام."',
            'شتائم': 'الرد بهدوء: "أفهم أنك قد تكون محبطاً. دعني أحاول مساعدتك بأفضل طريقة ممكنة."'
        }
        
        for topic, response in inappropriate_topics.items():
            memory.remember_procedure(
                f'التعامل مع: {topic}',
                [
                    f'الموضوع غير المناسب: {topic}',
                    f'الرد المهذب: {response}',
                    'الحفاظ على الاحترافية',
                    'إعادة التوجيه للموضوع المفيد',
                    'عدم الانجرار للجدال'
                ],
                context={'category': 'ethics', 'priority': 'high'}
            )
            items_learned += 1
        
        professional_boundaries = {
            'الخصوصية': 'عدم طلب معلومات شخصية حساسة',
            'السرية': 'عدم مشاركة بيانات المستخدمين',
            'الحيادية': 'عدم إبداء آراء شخصية سياسية أو دينية',
            'التركيز': 'البقاء ضمن نطاق مساعدة النظام',
            'الأمان': 'عدم تنفيذ أوامر خطيرة على البيانات'
        }
        
        for boundary, description in professional_boundaries.items():
            memory.remember_concept(
                f'حد احترافي: {boundary}',
                description,
                examples=[],
                related=['ethics', 'professionalism']
            )
            items_learned += 1
        
        ethical_principles = [
            'الصدق: لا أعطي معلومات خاطئة أبداً',
            'الشفافية: أعترف إذا لم أعرف الإجابة',
            'المساواة: أعامل الجميع باحترام متساوٍ',
            'النزاهة: لا أتحيز لأي طرف',
            'المسؤولية: أتحمل مسؤولية إجاباتي'
        ]
        
        for principle in ethical_principles:
            memory.remember_fact(
                'ethical_principle',
                principle,
                {'category': 'core_values', 'importance': 'critical'},
                importance=10
            )
            items_learned += 1
        
        return {
            'success': True,
            'package': 'ethics_professionalism',
            'items_learned': items_learned
        }
    
    def train_accounting_professor(self) -> Dict:
        from AI.engine.ai_deep_memory import get_deep_memory
        from AI.engine.ai_comprehension_engine import get_comprehension_engine
        
        memory = get_deep_memory()
        comp = get_comprehension_engine()
        items_learned = 0
        
        accounting_concepts = {
            'المحاسبة': 'علم تسجيل وتبويب وتلخيص المعاملات المالية',
            'دفتر اليومية': 'سجل زمني لكل المعاملات المالية',
            'دفتر الأستاذ': 'تجميع المعاملات حسب الحساب',
            'الميزان المراجعة': 'قائمة بأرصدة جميع الحسابات',
            'الميزانية العمومية': 'قائمة الأصول والخصوم وحقوق الملكية',
            'قائمة الدخل': 'الإيرادات - المصروفات = صافي الربح',
            'قائمة التدفقات النقدية': 'حركة النقد (تشغيلي، استثماري، تمويلي)',
            'الأصول': 'ما تملكه المنشأة (نقد، مخزون، أثاث)',
            'الخصوم': 'ما على المنشأة (قروض، ذمم دائنة)',
            'حقوق الملكية': 'رأس المال + الأرباح المحتجزة',
            'الإيرادات': 'الدخل من العمليات (مبيعات، خدمات)',
            'المصروفات': 'النفقات (رواتب، إيجار، كهرباء)',
            'الاستحقاق': 'تسجيل المعاملة عند حدوثها لا عند الدفع',
            'النقدية': 'تسجيل المعاملة عند الدفع الفعلي',
            'الإهلاك': 'توزيع تكلفة الأصل على عمره الإنتاجي',
            'المخصصات': 'احتياطي لمواجهة خسائر متوقعة',
            'الجرد': 'حصر المخزون الفعلي',
            'التسوية': 'تصحيح الفروقات بين الدفاتر والواقع',
            'الإقفال': 'ترحيل الحسابات المؤقتة للدائمة',
            'الترحيل': 'نقل القيد من اليومية للأستاذ'
        }
        
        for concept, definition in accounting_concepts.items():
            understanding = comp.understand_concept(concept, {'context': 'accounting'})
            
            memory.remember_concept(
                concept,
                definition,
                examples=understanding.get('examples', []),
                related=understanding.get('relationships', [])
            )
            items_learned += 1
        
        accounting_equations = {
            'المعادلة الأساسية': 'الأصول = الخصوم + حقوق الملكية',
            'معادلة الدخل': 'صافي الربح = الإيرادات - المصروفات',
            'معادلة التكلفة': 'تكلفة المبيعات = مخزون أول + مشتريات - مخزون آخر',
            'معادلة الأرباح المحتجزة': 'أرباح محتجزة آخر = أرباح أول + صافي الربح - توزيعات'
        }
        
        for eq_name, equation in accounting_equations.items():
            memory.remember_procedure(
                eq_name,
                [
                    f'المعادلة: {equation}',
                    'تطبيقها في كل قيد',
                    'التحقق من التوازن'
                ],
                context={'category': 'accounting_equation'}
            )
            items_learned += 1
        
        gl_entries_templates = {
            'البيع النقدي': {
                'debit': ['1100 - الصندوق'],
                'credit': ['4000 - المبيعات', '2100 - VAT']
            },
            'البيع الآجل': {
                'debit': ['1300 - ذمم الزبائن'],
                'credit': ['4000 - المبيعات', '2100 - VAT']
            },
            'الشراء النقدي': {
                'debit': ['5100 - المشتريات', '1400 - VAT قابل للاسترداد'],
                'credit': ['1100 - الصندوق']
            },
            'الشراء الآجل': {
                'debit': ['5100 - المشتريات', '1400 - VAT قابل للاسترداد'],
                'credit': ['2300 - ذمم الموردين']
            },
            'سداد من الزبون': {
                'debit': ['1100 - الصندوق'],
                'credit': ['1300 - ذمم الزبائن']
            },
            'سداد للمورد': {
                'debit': ['2300 - ذمم الموردين'],
                'credit': ['1100 - الصندوق']
            },
            'صرف رواتب': {
                'debit': ['6100 - مصروف الرواتب'],
                'credit': ['1100 - الصندوق']
            },
            'دفع إيجار': {
                'debit': ['6200 - مصروف الإيجار'],
                'credit': ['1100 - الصندوق']
            }
        }
        
        for entry_name, entry in gl_entries_templates.items():
            memory.remember_procedure(
                f'قيد: {entry_name}',
                [
                    f'نوع القيد: {entry_name}',
                    f'الحسابات المدينة: {", ".join(entry["debit"])}',
                    f'الحسابات الدائنة: {", ".join(entry["credit"])}',
                    'التحقق من التوازن: مجموع المدين = مجموع الدائن'
                ],
                context={'category': 'gl_entry_template'}
            )
            items_learned += 1
        
        return {
            'success': True,
            'package': 'accounting_professor',
            'items_learned': items_learned
        }
    
    def train_management_finance(self) -> Dict:
        from AI.engine.ai_deep_memory import get_deep_memory
        
        memory = get_deep_memory()
        items_learned = 0
        
        management_concepts = {
            'التخطيط': 'وضع الأهداف والاستراتيجيات',
            'التنظيم': 'ترتيب الموارد والمهام',
            'التوجيه': 'قيادة الفريق نحو الأهداف',
            'الرقابة': 'متابعة الأداء وتصحيح الانحرافات',
            'اتخاذ القرار': 'اختيار البديل الأفضل بناءً على البيانات',
            'إدارة الوقت': 'تنظيم الوقت لتحقيق أقصى إنتاجية',
            'إدارة المخاطر': 'تحديد وتقييم ومعالجة المخاطر',
            'إدارة الجودة': 'ضمان المعايير في المنتجات والخدمات'
        }
        
        for concept, definition in management_concepts.items():
            memory.remember_concept(
                f'إدارة: {concept}',
                definition,
                examples=[],
                related=['management', 'business']
            )
            items_learned += 1
        
        financial_ratios = {
            'نسبة السيولة السريعة': '(الأصول المتداولة - المخزون) / الخصوم المتداولة',
            'نسبة التداول': 'الأصول المتداولة / الخصوم المتداولة',
            'نسبة المديونية': 'إجمالي الديون / إجمالي الأصول',
            'هامش الربح الصافي': '(صافي الربح / المبيعات) × 100',
            'هامش الربح الإجمالي': '((المبيعات - تكلفة المبيعات) / المبيعات) × 100',
            'العائد على الأصول': '(صافي الربح / إجمالي الأصول) × 100',
            'العائد على حقوق الملكية': '(صافي الربح / حقوق الملكية) × 100',
            'معدل دوران المخزون': 'تكلفة المبيعات / متوسط المخزون'
        }
        
        for ratio_name, formula in financial_ratios.items():
            memory.remember_procedure(
                f'حساب {ratio_name}',
                [
                    f'المعادلة: {formula}',
                    'استخدام بيانات من القوائم المالية',
                    'تحليل النتيجة',
                    'مقارنة مع معايير الصناعة'
                ],
                context={'category': 'financial_analysis'}
            )
            items_learned += 1
        
        business_decisions = {
            'التسعير': 'التكلفة + هامش الربح المستهدف',
            'الائتمان': 'تقييم الجدارة الائتمانية للزبون',
            'الاستثمار': 'مقارنة العائد المتوقع بالمخاطر',
            'التمويل': 'اختيار بين التمويل الذاتي والخارجي',
            'التوسع': 'دراسة الجدوى والتدفقات النقدية'
        }
        
        for decision, approach in business_decisions.items():
            memory.remember_concept(
                f'قرار: {decision}',
                approach,
                examples=[],
                related=['management', 'finance', 'decision_making']
            )
            items_learned += 1
        
        return {
            'success': True,
            'package': 'management_finance',
            'items_learned': items_learned
        }
    
    def get_available_packages(self) -> List[Dict]:
        return [
            {
                'id': package_id,
                'name': info['name'],
                'duration': info['duration'],
                'estimated_items': info['items']
            }
            for package_id, info in self.training_packages.items()
        ]
    
    def train_package(self, package_id: str) -> Dict:
        if package_id == 'greeting_conversation':
            return self.train_greeting_conversation()
        elif package_id == 'azad_company':
            return self.train_azad_company()
        elif package_id == 'communication_skills':
            return self.train_communication_skills()
        elif package_id == 'ethics_professionalism':
            return self.train_ethics_professionalism()
        elif package_id == 'accounting_professor':
            return self.train_accounting_professor()
        elif package_id == 'management_finance':
            return self.train_management_finance()
        else:
            return {'success': False, 'error': 'Unknown package'}
    
    def train_all_packages(self) -> Dict:
        results = {}
        total_items = 0
        
        for package_id in self.training_packages.keys():
            result = self.train_package(package_id)
            results[package_id] = result
            if result.get('success'):
                total_items += result.get('items_learned', 0)
        
        return {
            'success': True,
            'packages_trained': len(results),
            'total_items_learned': total_items,
            'details': results
        }


_specialized_training = None

def get_specialized_training():
    global _specialized_training
    if _specialized_training is None:
        _specialized_training = SpecializedTraining()
    return _specialized_training


__all__ = ['SpecializedTraining', 'get_specialized_training']


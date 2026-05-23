from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def _route_for_keyword(keyword: str) -> Optional[str]:
    try:
        from AI.engine.ai_auto_discovery import find_route_by_keyword
        info = find_route_by_keyword(keyword)
        if info and info.get("matches"):
            match = info["matches"][0]
            return match.get("url") or match.get("path") or match.get("rule")
    except Exception:
        pass
    return None


class ComprehensionEngine:
    def __init__(self):
        self.understanding_levels = {"surface": 0, "shallow": 1, "moderate": 2, "deep": 3, "expert": 4, "mastery": 5}
        self.comprehension_map: Dict[str, Dict[str, Any]] = {}
        self.learning_paths: Dict[str, Any] = {}

    def understand_concept(self, concept: str, context: Dict = None) -> Dict[str, Any]:
        context = context or {}
        concept = str(concept or "").strip()
        understanding = {"concept": concept, "timestamp": datetime.now().isoformat(), "level": "surface", "what": "", "why": "", "how": "", "when": "", "where": "", "examples": [], "counterexamples": [], "relationships": [], "implications": [], "mistakes_to_avoid": []}
        understanding["what"] = self._explain_what(concept, context)
        understanding["why"] = self._explain_why(concept, context)
        understanding["how"] = self._explain_how(concept, context)
        understanding["when"] = self._explain_when(concept, context)
        understanding["where"] = self._explain_where(concept, context)
        understanding["examples"] = self._generate_examples(concept, context)
        understanding["counterexamples"] = self._generate_counterexamples(concept, context)
        understanding["relationships"] = self._find_relationships(concept, context)
        understanding["implications"] = self._analyze_implications(concept, context)
        understanding["mistakes_to_avoid"] = self._identify_common_mistakes(concept, context)
        understanding["level"] = self._assess_understanding_level(understanding)
        self.comprehension_map[concept] = understanding
        return understanding

    def _explain_what(self, concept: str, context: Dict) -> str:
        key = concept.lower()
        definitions = {
            "زبون": "شخص أو جهة تتعامل مع المنشأة كمشترٍ أو طالب خدمة، وتظهر بياناته وأرصده حسب موديل Customer.",
            "customer": "جهة تتعامل مع المنشأة كمشترٍ أو طالب خدمة، وتظهر بياناتها وأرصدةها حسب موديل Customer.",
            "مورد": "شخص أو شركة توفر منتجات أو خدمات للمنشأة، وتظهر بياناته وأرصده حسب موديل Supplier.",
            "supplier": "جهة توفر منتجات أو خدمات للمنشأة، وتظهر بياناتها وأرصدةها حسب موديل Supplier.",
            "بيع": "عملية تسجيل بيع منتجات أو خدمات لزبون، وتفاصيلها النهائية يجب أن تُقرأ من موديل Sale وبنوده.",
            "sale": "عملية بيع منتجات أو خدمات لزبون، وتفاصيلها النهائية يجب أن تُقرأ من موديل Sale وبنوده.",
            "قيد محاسبي": "تسجيل مالي يوضح الحسابات المدينة والدائنة ويجب أن يكون متوازنًا.",
            "gl entry": "تسجيل مالي يوضح الحسابات المدينة والدائنة ويجب أن يكون متوازنًا.",
            "رصيد": "قيمة مالية مسجلة أو محسوبة من حركات النظام، ويجب تفسير إشارتها حسب سياسة كل شاشة/موديل.",
            "balance": "قيمة مالية مسجلة أو محسوبة من حركات النظام، وتفسير الإشارة يعتمد على سياسة كل شاشة/موديل.",
            "vat": "ضريبة القيمة المضافة؛ نسبتها تُقرأ من إعدادات النظام أو مصدر رسمي حديث، ولا تُفترض كنسبة ثابتة.",
            "مخزون": "كميات المنتجات المسجلة في المستودعات عبر StockLevel وحركات المخزون.",
            "stock": "كميات المنتجات المسجلة في المستودعات عبر StockLevel وحركات المخزون.",
        }
        return definitions.get(key, f"{concept} مفهوم يحتاج ربطه ببيانات النظام أو سياق السؤال.")

    def _explain_why(self, concept: str, context: Dict) -> str:
        key = concept.lower()
        reasons = {
            "زبون": "لربط المبيعات والخدمات والدفعات بجهة واضحة قابلة للتتبع.",
            "customer": "لربط المبيعات والخدمات والدفعات بجهة واضحة قابلة للتتبع.",
            "قيد محاسبي": "لتوثيق الأثر المالي للعمليات وتحقيق توازن المدين والدائن.",
            "gl entry": "لتوثيق الأثر المالي للعمليات وتحقيق توازن المدين والدائن.",
            "vat": "لأن بعض العمليات قد تخضع لضريبة يجب احتسابها وتسجيلها حسب الإعدادات والقانون الساري.",
            "مخزون": "لمعرفة الكميات المتاحة وتجنب البيع بلا رصيد أو تراكم بضاعة غير مطلوبة.",
            "رصيد": "لإظهار موقف الجهة المالي بناءً على الحركات المسجلة.",
        }
        return reasons.get(key, f"لأن {concept} يؤثر على منطق العمل أو التقارير أو تتبع البيانات داخل النظام.")

    def _explain_how(self, concept: str, context: Dict) -> str:
        key = concept.lower()
        customers_route = _route_for_keyword("customers create") or _route_for_keyword("customers") or "غير مفهرس حالياً"
        methods = {
            "زبون": f"يُدار من صفحة الزبائن حسب خريطة النظام: {customers_route}. الحقول الفعلية تُقرأ من موديل Customer والنماذج المرتبطة.",
            "customer": f"يُدار من صفحة الزبائن حسب خريطة النظام: {customers_route}. الحقول الفعلية تُقرأ من موديل Customer والنماذج المرتبطة.",
            "قيد محاسبي": "ينشأ حسب نوع العملية وإعدادات دفتر الأستاذ ودليل الحسابات، ويجب أن يتوازن المدين والدائن.",
            "gl entry": "ينشأ حسب نوع العملية وإعدادات دفتر الأستاذ ودليل الحسابات، ويجب أن يتوازن المدين والدائن.",
            "vat": "يُحسب من نسبة ضريبة مقروءة من إعدادات النظام أو مصدر رسمي حديث، ثم يضاف للصافي حسب نوع الفاتورة.",
            "رصيد": "يُقرأ من الحقل/الدالة المعتمدة في النظام أو يُعاد احتسابه من الحركات إذا كانت كل البيانات متاحة.",
        }
        return methods.get(key, f"{concept} يعمل ضمن آليات النظام ويحتاج قراءة الموديل/المسار الفعلي قبل الجزم بالتفاصيل.")

    def _explain_when(self, concept: str, context: Dict) -> str:
        key = concept.lower()
        timing = {"زبون": "عند إنشاء علاقة بيع أو خدمة أو ذمة مع جهة جديدة.", "قيد محاسبي": "عند تسجيل عملية مالية تؤثر على الحسابات.", "vat": "عند عملية خاضعة للضريبة حسب إعدادات النظام والقانون.", "رصيد": "يتغير عند تسجيل أو تعديل عملية تؤثر على الذمة أو الحساب."}
        return timing.get(key, f"يُستخدم {concept} عندما يحتاج سير العمل أو التقرير لهذه المعلومة.")

    def _explain_where(self, concept: str, context: Dict) -> str:
        key = concept.lower()
        locations = {"زبون": "في موديل/جدول customers وعبر مسارات الزبائن المكتشفة.", "قيد محاسبي": "في جداول/موديلات GLBatch و GLEntry إذا كانت مفعلة في النظام.", "vat": "في حقول الضريبة وإعدادات النظام المرتبطة بالفواتير والمبيعات.", "رصيد": "في حقول الرصيد أو دوال الحساب داخل موديلات الزبائن/الموردين/الشركاء."}
        return locations.get(key, f"مكان {concept} يجب تحديده من خريطة النظام أو موديلات قاعدة البيانات.")

    def _generate_examples(self, concept: str, context: Dict) -> List[str]:
        key = concept.lower()
        examples = {
            "زبون": ["زبون له مبيعات ودفعات مسجلة يمكن عرضها في كشف حسابه.", "زبون جديد يُضاف قبل إنشاء فاتورة أو طلب خدمة."],
            "قيد محاسبي": ["قيد بيع يربط الذمم والإيراد والضريبة حسب إعدادات الحسابات.", "قيد دفع يربط وسيلة الدفع بالذمة أو الجهة المستفيدة."],
            "رصيد": ["رصيد جهة يُقرأ من النظام ثم يُفسّر حسب سياسة الشاشة.", "فرق بين مجموع الحركات والرصيد المخزن قد يعني حاجة لمزامنة/إعادة احتساب."],
            "vat": ["فاتورة ذات نسبة ضريبة مأخوذة من الإعدادات.", "فاتورة بلا ضريبة إذا كانت الضريبة معطلة أو غير مهيأة."],
        }
        return examples.get(key, [f"مثال {concept} يجب بناؤه من بيانات حقيقية عند توفرها."])

    def _generate_counterexamples(self, concept: str, context: Dict) -> List[str]:
        key = concept.lower()
        counter = {"زبون": ["المورد ليس زبونًا إلا إذا كان النظام يربطه صراحة بزبون."], "قيد محاسبي": ["قيد غير متوازن ليس قيدًا صحيحًا."], "رصيد": ["لا يجوز تفسير الموجب/السالب كقاعدة عامة دون معرفة سياسة النظام."], "vat": ["لا يجوز استخدام نسبة ضريبة ثابتة إذا لم تكن مضبوطة في النظام أو موثقة بمصدر رسمي حديث."]}
        return counter.get(key, [])

    def _find_relationships(self, concept: str, context: Dict) -> List[str]:
        key = concept.lower()
        relationships = {"زبون": ["يرتبط بالمبيعات والخدمات والدفعات والفواتير حسب العلاقات الفعلية في models.py."], "قيد محاسبي": ["يرتبط بدليل الحسابات والدفعات والمبيعات والمصروفات حسب إعدادات GL."], "vat": ["يرتبط بالفواتير والمبيعات والمشتريات والإعدادات الضريبية."], "رصيد": ["يرتبط بالحركات المالية والدفعات والفواتير وربما قيود GL."]}
        return relationships.get(key, [])

    def _analyze_implications(self, concept: str, context: Dict) -> List[str]:
        key = concept.lower()
        implications = {"زبون": ["بيانات زبون غير دقيقة تؤثر على التحصيل والتواصل."], "قيد محاسبي": ["قيد خاطئ ينتج تقارير مالية خاطئة."], "رصيد": ["رصيد غير محدث قد يضلل قرارات التحصيل أو السداد."], "vat": ["نسبة ضريبة غير صحيحة تؤثر على الفاتورة والالتزام الضريبي."]}
        return implications.get(key, [])

    def _identify_common_mistakes(self, concept: str, context: Dict) -> List[str]:
        key = concept.lower()
        mistakes = {"زبون": ["إدخال رقم هاتف مكرر إن كان النظام يمنع ذلك.", "إدخال رصيد افتتاحي دون سند."], "قيد محاسبي": ["عدم توازن المدين والدائن.", "اختيار حساب خاطئ."], "رصيد": ["تفسير الإشارة بالعكس دون الرجوع لسياسة النظام.", "تجاهل دفعات أو استردادات."], "vat": ["افتراض نسبة ثابتة بدل قراءة الإعدادات.", "تطبيق الضريبة على عملية غير خاضعة."]}
        return mistakes.get(key, [])

    def _assess_understanding_level(self, understanding: Dict) -> str:
        score = 0
        for key in ["what", "why", "how"]:
            if understanding.get(key):
                score += 1
        if len(understanding.get("examples", [])) >= 2:
            score += 1
        if len(understanding.get("relationships", [])) >= 1:
            score += 1
        if len(understanding.get("implications", [])) >= 1:
            score += 1
        return {0: "surface", 1: "surface", 2: "shallow", 3: "moderate", 4: "deep", 5: "expert", 6: "mastery"}.get(score, "surface")

    def explain_fully(self, concept: str, context: Dict = None) -> str:
        u = self.understand_concept(concept, context)
        parts = [f"📚 فهم لـ: {concept}", f"مستوى الفهم: {u['level'].upper()}\n"]
        labels = [("what", "❓ ما هو؟"), ("why", "💡 لماذا؟"), ("how", "⚙️ كيف؟"), ("when", "⏰ متى؟"), ("where", "📍 أين؟")]
        for key, label in labels:
            if u.get(key):
                parts.append(f"{label}\n{u[key]}\n")
        for key, label in [("examples", "✅ أمثلة:"), ("counterexamples", "❌ ليس:"), ("relationships", "🔗 العلاقات:"), ("implications", "⚡ التأثيرات:"), ("mistakes_to_avoid", "⚠️ أخطاء شائعة:")]:
            values = u.get(key) or []
            if values:
                parts.append(label)
                parts.extend([f"  - {value}" for value in values])
                parts.append("")
        return "\n".join(parts)


_comprehension_engine = None


def get_comprehension_engine():
    global _comprehension_engine
    if _comprehension_engine is None:
        _comprehension_engine = ComprehensionEngine()
    return _comprehension_engine


__all__ = ["ComprehensionEngine", "get_comprehension_engine"]

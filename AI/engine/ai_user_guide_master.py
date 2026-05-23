"""Dynamic expert user-guide knowledge for the AI assistant.

No route is treated as true unless it is found through ai_auto_discovery. Static
text describes professional workflows, validation checks, and operational logic,
not hard-coded live URLs or financial values.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


MODULES: Dict[str, Dict[str, Any]] = {
    "customers": {
        "title": "الزبائن",
        "keywords": ["زبون", "زبائن", "customer", "زبون", "زبائن", "كشف زبون", "رصيد زبون"],
        "description": "إدارة الزبائن وأرصدة الزبائن وكشوف الحساب وربطهم بالمبيعات والصيانة والدفعات.",
        "route_keywords": ["customers", "customer"],
        "create_keywords": ["customers create", "customer add", "customer new"],
        "fields": {"name": "اسم الزبون", "phone": "رقم الهاتف", "email": "البريد الإلكتروني", "address": "العنوان", "opening_balance": "الرصيد الافتتاحي", "notes": "ملاحظات"},
        "steps": ["افتح صفحة الزبائن", "ابحث أولًا بالاسم أو الهاتف لتجنب التكرار", "اختر إضافة زبون إذا لم يكن موجودًا", "أدخل الاسم والهاتف والبيانات الأساسية", "راجع الرصيد الافتتاحي ولا تدخله إلا بسند", "احفظ ثم افتح كشف الحساب للتأكد من ظهور الزبون"],
        "expert_checks": ["افحص التكرار بالهاتف قبل الحفظ", "لا تفسر إشارة الرصيد دون سياسة النظام", "راجع آخر فاتورة وآخر دفعة قبل الحكم على ذمة الزبون"],
        "after_save": ["افتح كشف الزبون", "اربط الزبون بالمركبة أو طلب الصيانة إن وجد", "راجع الدفعات القديمة أو الرصيد الافتتاحي"],
        "common_mistakes": ["إضافة نفس الزبون باسم مختلف", "إدخال رصيد افتتاحي بلا مرجع", "اعتبار الموجب/السالب عليه أو له دون معرفة سياسة النظام"],
        "related": ["sales", "payments", "services", "reports"],
    },
    "suppliers": {
        "title": "الموردين",
        "keywords": ["مورد", "موردين", "supplier", "vendor", "كشف مورد", "رصيد مورد"],
        "description": "إدارة الموردين وكشوف حساباتهم وربطهم بالمشتريات والتسويات والمدفوعات.",
        "route_keywords": ["suppliers", "vendors"],
        "create_keywords": ["suppliers create", "vendor add", "supplier new"],
        "fields": {"name": "اسم المورد", "phone": "رقم الهاتف", "email": "البريد الإلكتروني", "address": "العنوان", "opening_balance": "الرصيد الافتتاحي", "notes": "ملاحظات"},
        "steps": ["افتح صفحة الموردين", "ابحث عن المورد قبل الإضافة", "أدخل بيانات التواصل", "راجع الرصيد الافتتاحي أو المستحقات السابقة", "احفظ وافتح كشف المورد للمراجعة"],
        "expert_checks": ["طابق اسم المورد مع فواتير الشراء", "لا تجمع المورد والزبون في حساب واحد إلا إذا النظام يدعم ذلك", "راجع التسويات قبل إصدار حكم على الرصيد"],
        "after_save": ["أضف بيانات الاتصال", "اربط المورد بالمنتجات أو فواتير الشراء", "راجع كشف الحساب"],
        "common_mistakes": ["تكرار المورد", "إدخال رصيد افتتاحي عكسي", "تجاهل العملة أو سعر الصرف إن وجدت"],
        "related": ["payments", "products", "warehouses", "reports"],
    },
    "products": {
        "title": "المنتجات",
        "keywords": ["منتج", "منتجات", "product", "قطعة", "قطع", "بضاعة", "باركود", "sku"],
        "description": "إدارة المنتجات وقطع الغيار والأسعار والباركود وربطها بالمخزون والمبيعات والصيانة.",
        "route_keywords": ["products", "items", "parts"],
        "create_keywords": ["products create", "product add", "part create"],
        "fields": {"name": "اسم المنتج", "sku": "رمز المنتج", "barcode": "الباركود", "price": "سعر البيع", "selling_price": "سعر البيع", "purchase_price": "سعر الشراء/التكلفة", "min_qty": "الحد الأدنى"},
        "steps": ["افتح صفحة المنتجات", "ابحث بالاسم أو SKU أو الباركود", "أضف المنتج إذا لم يكن موجودًا", "أدخل التكلفة وسعر البيع والحد الأدنى", "اربط المنتج بالمخزن أو حركة إدخال مخزون", "راجع الربحية والكمية قبل البيع"],
        "expert_checks": ["لا تبيع منتجًا بلا مخزون إذا النظام يمنع ذلك", "فرق بين سعر الشراء وسعر البيع", "راقب المنتجات تحت الحد الأدنى", "استخدم SKU/Barcode لتجنب التكرار"],
        "after_save": ["أضف كمية افتتاحية أو حركة مخزون", "راجع ظهور المنتج في البيع والصيانة", "راجع تقرير المنتجات منخفضة المخزون"],
        "common_mistakes": ["تكرار المنتج بأسماء قريبة", "نسيان التكلفة", "إضافة كمية في منتج دون مستودع"],
        "related": ["warehouses", "sales", "services", "reports"],
    },
    "sales": {
        "title": "المبيعات",
        "keywords": ["بيع", "مبيعات", "sale", "sales", "فاتورة", "فواتير", "invoice"],
        "description": "إدارة المبيعات وفواتير البيع وتأثيرها على المخزون والذمم والدفعات.",
        "route_keywords": ["sales", "invoices"],
        "create_keywords": ["sales create", "sale new", "invoice create"],
        "steps": ["اختر الزبون", "اختر المستودع", "أضف المنتجات والكميات", "راجع توفر الكمية وسعر كل بند", "راجع الخصم والضريبة من إعدادات النظام", "احفظ الفاتورة", "سجل الدفعة إن حصل قبض", "اطبع أو أرسل الفاتورة عند الحاجة"],
        "expert_checks": ["تأكد من المخزون قبل الحفظ", "راجع الزبون والعملة وطريقة الدفع", "لا تعتمد VAT إلا من إعدادات النظام", "راجع أثر الفاتورة على الذمة والمخزون"],
        "after_save": ["افتح الفاتورة وتحقق من الإجمالي", "راجع حركة المخزون", "راجع كشف الزبون", "سجل الدفعة أو اربطها بالفاتورة"],
        "common_mistakes": ["اختيار مستودع خاطئ", "بيع كمية أكبر من المتوفر", "نسيان ربط الدفعة بالفاتورة", "احتساب ضريبة بنسبة غير مضبوطة"],
        "calculations": {"subtotal": "مجموع البنود", "discount": "الخصم", "net": "الصافي", "vat": "ضريبة حسب إعدادات النظام", "total": "الإجمالي النهائي"},
        "stock_effect": "عادة يتم خصم الكمية من المستودع المختار عند تأكيد البيع حسب إعدادات النظام.",
        "related": ["customers", "payments", "warehouses", "general_ledger", "reports"],
    },
    "payments": {
        "title": "الدفعات",
        "keywords": ["دفعة", "دفعات", "payment", "دفع", "قبض", "صرف", "تحصيل"],
        "description": "إدارة الدفعات الواردة والصادرة وربطها بالزبائن أو الموردين أو الفواتير.",
        "route_keywords": ["payments"],
        "create_keywords": ["payments create", "payment add"],
        "fields": {"direction": "IN أو OUT", "method": "طريقة الدفع", "entity_type": "نوع الجهة", "amount": "المبلغ", "reference": "مرجع", "notes": "ملاحظات"},
        "steps": ["حدد هل العملية قبض IN أو صرف OUT", "اختر الجهة: زبون/مورد/شريك/مصروف حسب النظام", "أدخل المبلغ وطريقة الدفع", "اربط الدفعة بالفاتورة إن وجدت", "أضف المرجع أو رقم الشيك", "احفظ وراجع كشف الجهة"],
        "expert_checks": ["الاتجاه IN/OUT أهم حقل في الدفعة", "راجع العملة وسعر الصرف إن وجدا", "لا تسجل دفعة عامة إذا يجب ربطها بفاتورة", "راجع كشف الجهة بعد الحفظ"],
        "after_save": ["راجع الرصيد", "راجع الصندوق/البنك", "راجع القيد المحاسبي إن كان GL مفعلاً"],
        "common_mistakes": ["عكس اتجاه الدفعة", "تسجيل نفس الدفعة مرتين", "عدم ربط الدفعة بالجهة الصحيحة"],
        "related": ["customers", "suppliers", "sales", "general_ledger", "reports"],
    },
    "warehouses": {
        "title": "المستودعات",
        "keywords": ["مخزن", "مخازن", "warehouse", "مستودع", "مخزون", "stock", "inventory"],
        "description": "إدارة المستودعات وحركة المخزون والكميات المتوفرة والحد الأدنى.",
        "route_keywords": ["warehouses", "inventory", "stock"],
        "create_keywords": ["warehouse create", "warehouses add"],
        "steps": ["افتح صفحة المخزون أو المستودعات", "اختر المستودع", "ابحث عن المنتج", "راجع الكمية الحالية والحد الأدنى", "نفذ إدخال/إخراج/تحويل حسب الصلاحيات", "راجع أثر الحركة على المنتج"],
        "expert_checks": ["كل كمية يجب أن تكون مرتبطة بمنتج ومستودع", "حركة البيع أو الصيانة قد تخصم تلقائيًا", "التحويل بين مستودعات ليس بيعًا ولا شراءً", "راجع المنتجات تحت الحد الأدنى"],
        "after_save": ["راجع حركة المخزون", "راجع المنتج في المستودع الهدف", "راجع تقرير النواقص"],
        "common_mistakes": ["تعديل كمية يدويًا بدل حركة موثقة", "اختيار مستودع خاطئ", "نسيان تكلفة المنتج"],
        "related": ["products", "sales", "services", "reports"],
    },
    "expenses": {
        "title": "المصروفات",
        "keywords": ["مصروف", "مصاريف", "expense", "نفقة", "نفقات"],
        "description": "تسجيل ومتابعة المصروفات وربطها بطريقة الدفع والتقارير المالية.",
        "route_keywords": ["expenses"],
        "create_keywords": ["expenses create", "expense add"],
        "fields": {"amount": "المبلغ", "description": "الوصف", "date": "التاريخ", "payment_method": "طريقة الدفع", "reference": "المرجع"},
        "steps": ["افتح صفحة المصروفات", "اختر نوع المصروف أو التصنيف", "أدخل الوصف والمبلغ والتاريخ", "حدد طريقة الدفع", "أضف مرجعًا أو مرفقًا إن وجد", "احفظ وراجع التقرير المالي"],
        "expert_checks": ["لا تخلط المصروف مع دفعة مورد إلا حسب آلية النظام", "راجع التاريخ لأن التقارير تعتمد عليه", "أضف مرجعًا ليسهل التدقيق"],
        "after_save": ["راجع تقرير المصروفات", "راجع الصندوق/البنك", "راجع GL إن كان مفعلاً"],
        "common_mistakes": ["تسجيل المصروف بتاريخ خاطئ", "عدم اختيار التصنيف", "تكرار نفس المصروف"],
        "related": ["payments", "general_ledger", "reports"],
    },
    "services": {
        "title": "الصيانة",
        "keywords": ["صيانة", "service", "ورشة", "طلب صيانة", "مركبة", "عطل"],
        "description": "إدارة طلبات الصيانة ومراحل العمل وقطع الغيار والتكلفة والتحصيل.",
        "route_keywords": ["services", "service requests", "maintenance"],
        "create_keywords": ["services create", "service request create", "maintenance create"],
        "fields": {"customer_id": "الزبون", "vehicle_model": "موديل المركبة", "vehicle_vrn": "رقم المركبة", "problem_description": "وصف العطل", "mechanic_id": "المسؤول", "estimated_cost": "التكلفة المتوقعة"},
        "steps": ["اختر الزبون أو أضفه إن لم يكن موجودًا", "أدخل بيانات المركبة ورقمها", "اكتب وصف العطل كما قال الزبون", "عيّن المسؤول أو الفني", "أضف التشخيص والقطع المستخدمة", "راجع التكلفة والدفعات", "غيّر الحالة عند اكتمال العمل"],
        "expert_checks": ["وصف العطل الأولي غير التشخيص النهائي", "قطع الغيار يجب أن تخصم من المخزون إذا النظام يدعم ذلك", "لا تغلق الطلب قبل مراجعة التكلفة والقبض", "اربط الدفعات بطلب الصيانة أو الزبون"],
        "after_save": ["تابع الحالة", "أضف قطع الغيار", "راجع فاتورة/تحصيل الزبون", "اطبع تقرير أو وصل"],
        "common_mistakes": ["نسيان ربط الزبون", "إغلاق الطلب قبل التحصيل", "استخدام قطع دون خصم مخزون"],
        "related": ["customers", "products", "warehouses", "payments", "sales"],
    },
    "reports": {
        "title": "التقارير",
        "keywords": ["تقرير", "تقارير", "report", "تحليل", "ملخص"],
        "description": "تقارير مالية وتشغيلية حسب الصلاحيات والفلاتر المتاحة.",
        "route_keywords": ["reports"],
        "create_keywords": [],
        "steps": ["حدد نوع التقرير", "اختر الفترة الزمنية", "حدد الجهة أو الوحدة إن لزم", "راجع الفلاتر قبل التصدير", "قارن الإجماليات مع القيود أو الكشوف"],
        "expert_checks": ["الفترة الزمنية أهم فلتر", "لا تقارن تقريرين بفلاتر مختلفة", "راجع العملة والضريبة عند التقارير المالية"],
        "after_save": ["صدّر PDF/Excel إن كان متاحًا", "احفظ نسخة للمراجعة", "راجع السجلات الشاذة"],
        "common_mistakes": ["نسيان فلتر التاريخ", "خلط المقبوض مع المفوتر", "اعتبار التقرير نهائيًا دون تدقيق"],
        "related": ["sales", "payments", "expenses", "warehouses", "general_ledger"],
    },
    "general_ledger": {
        "title": "دفتر الأستاذ",
        "keywords": ["محاسب", "محاسبة", "قيد", "قيود", "gl", "ledger", "استاذ", "حسابات"],
        "description": "دفتر الأستاذ والقيود المحاسبية ودليل الحسابات عند تفعيل GL.",
        "route_keywords": ["gl", "ledger", "accounts"],
        "create_keywords": [],
        "steps": ["افتح دفتر الأستاذ أو دليل الحسابات", "حدد الحساب أو الفترة", "راجع القيود المدينة والدائنة", "تأكد أن كل batch متوازن", "قارن الأثر مع الفاتورة أو الدفعة الأصلية"],
        "expert_checks": ["مجموع المدين يجب أن يساوي مجموع الدائن", "لا تعتمد رقم حساب ثابت دون دليل الحسابات الفعلي", "راجع مصدر القيد قبل التعديل"],
        "after_save": ["راجع ميزان المراجعة", "راجع الحسابات المرتبطة", "راجع أي قيد غير متوازن"],
        "common_mistakes": ["تعديل قيد مولّد تلقائيًا دون عكس صحيح", "استخدام حساب خاطئ", "نسيان أثر الضريبة أو الصندوق"],
        "related": ["sales", "payments", "expenses", "reports"],
    },
}

GUIDE_MODULE_KEYS = list(MODULES.keys())
COMPLETE_USER_GUIDE = {"system_name": "نظام أزاد لإدارة الكراج والمحاسبة", "version": "غير محدد - اقرأ الإصدار من إعدادات النظام عند الحاجة", **MODULES}


def _find_route(keywords) -> Optional[str]:
    try:
        from AI.engine.ai_auto_discovery import find_route_by_keyword
        for keyword in keywords or []:
            info = find_route_by_keyword(keyword)
            if info and info.get("matches"):
                route = info["matches"][0]
                return route.get("url") or route.get("path") or route.get("rule")
    except Exception:
        pass
    return None


def _detect_action(question: str) -> str:
    q = str(question or "").lower()
    if any(w in q for w in ["أضيف", "اضيف", "إضافة", "اضافة", "أضف", "اضف", "إنشاء", "انشاء", "create", "add", "new"]):
        return "create"
    if any(w in q for w in ["أعدل", "اعدل", "تعديل", "عدّل", "عدل", "edit", "update", "modify"]):
        return "update"
    if any(w in q for w in ["أحذف", "احذف", "حذف", "delete", "remove"]):
        return "delete"
    if any(w in q for w in ["تقرير", "تحليل", "ملخص", "report", "analysis"]):
        return "report"
    if any(w in q for w in ["رصيد", "كشف", "balance", "statement"]):
        return "statement"
    return "navigate"


def _module_score(question_lower: str, module: Dict[str, Any]) -> int:
    score = 0
    for keyword in module.get("keywords", []):
        kw = str(keyword).lower()
        if kw and kw in question_lower:
            score += 10 if len(kw) > 3 else 6
    for related in module.get("related", []):
        if related.lower() in question_lower:
            score += 2
    return score


class UserGuideMaster:
    def __init__(self):
        self.guide = COMPLETE_USER_GUIDE
        self.shortcuts = self._build_shortcuts()

    def answer_question(self, question: str) -> Dict[str, Any]:
        question = str(question or "")
        question_lower = question.lower()
        ranked = sorted(((key, _module_score(question_lower, module)) for key, module in MODULES.items()), key=lambda item: item[1], reverse=True)
        if ranked and ranked[0][1] > 0:
            key = ranked[0][0]
            if key == "general_ledger":
                return self._explain_gl(question)
            return self._module_response(key, question)
        return self._general_help()

    def _module_response(self, key: str, question: str = "") -> Dict[str, Any]:
        module = MODULES[key]
        action = _detect_action(question)
        wants_create = action == "create"
        route = _find_route(module.get("create_keywords") if wants_create else module.get("route_keywords"))
        payload = {
            "topic": module["title"],
            "module_key": key,
            "action": action,
            "description": module.get("description"),
            "route": route or "غير مفهرس حالياً",
            "route_source": "ai_auto_discovery" if route else "not_found",
            "steps": module.get("steps", []),
            "fields": module.get("fields", {}),
            "expert_checks": module.get("expert_checks", []),
            "after_save": module.get("after_save", []),
            "common_mistakes": module.get("common_mistakes", []),
            "related_modules": module.get("related", []),
            "professional_hint": self._professional_hint(key, action),
        }
        if module.get("calculations"):
            payload["calculations"] = module["calculations"]
        if module.get("stock_effect"):
            payload["stock_effect"] = module["stock_effect"]
        payload["tips"] = self._tips_for(key)
        return payload

    def _professional_hint(self, key: str, action: str) -> str:
        hints = {
            "customers": "المستخدم المتمرس يبدأ بالبحث عن الزبون ثم يراجع كشفه قبل إنشاء حركة جديدة.",
            "suppliers": "المستخدم المتمرس يطابق المورد مع الفواتير والتسويات قبل الحكم على الرصيد.",
            "products": "المستخدم المتمرس يراجع SKU/Barcode والكمية والتكلفة قبل البيع أو الإضافة.",
            "sales": "المستخدم المتمرس يراجع الزبون، المستودع، الكمية، الضريبة، ثم الدفعة والرصيد بعد الحفظ.",
            "payments": "المستخدم المتمرس يتأكد من IN/OUT والجهة والمرجع قبل الحفظ لأن الخطأ هنا يعكس الأرصدة.",
            "warehouses": "المستخدم المتمرس لا يغير الكمية بلا حركة مخزون موثقة.",
            "expenses": "المستخدم المتمرس يهتم بالتاريخ والتصنيف والمرجع لأنها تؤثر على التقارير والتدقيق.",
            "services": "المستخدم المتمرس يفصل بين وصف العطل والتشخيص والقطع والدفعات والحالة النهائية.",
            "reports": "المستخدم المتمرس يبدأ بالفترة والفلاتر ثم يقارن الإجمالي مع الكشوف أو القيود.",
            "general_ledger": "المستخدم المتمرس لا يعدل قيدًا قبل معرفة مصدره والتأكد من توازن المدين والدائن.",
        }
        return hints.get(key, "راجع البيانات والفلاتر قبل تنفيذ العملية.")

    def _tips_for(self, key: str) -> List[str]:
        base = ["لا أعتمد رابطًا أو رقمًا إلا إذا كان مكتشفًا أو مقروءًا من النظام.", "عند نقص البيانات أعرض ذلك بدل اختراع نتيجة."]
        if key in {"customers", "suppliers"}:
            base.append("تفسير موجب/سالب الرصيد يعتمد على سياسة النظام.")
        if key in {"sales", "payments", "expenses", "general_ledger"}:
            base.append("راجع الأثر المحاسبي أو كشف الجهة بعد الحفظ.")
        if key in {"products", "warehouses", "services", "sales"}:
            base.append("راجع أثر العملية على المخزون.")
        return base

    def _explain_gl(self, question: str) -> Dict[str, Any]:
        route = _find_route(MODULES["general_ledger"].get("route_keywords"))
        payload = self._module_response("general_ledger", question)
        payload.update({
            "topic": "دفتر الأستاذ العام",
            "route": route or "غير مفهرس حالياً",
            "route_source": "ai_auto_discovery" if route else "not_found",
            "concepts": {"chart_of_accounts": "دليل الحسابات الفعلي يجب قراءته من النظام", "gl_entries": "القيود المحاسبية ويجب أن تكون متوازنة", "gl_batch": "مجموعة قيود مرتبطة بمعاملة"},
        })
        return payload

    def _build_shortcuts(self) -> Dict[str, str]:
        return {key: (_find_route(value.get("route_keywords")) or "غير مفهرس حالياً") for key, value in MODULES.items()}

    def _general_help(self) -> Dict[str, Any]:
        return {
            "system_name": COMPLETE_USER_GUIDE["system_name"],
            "version": COMPLETE_USER_GUIDE["version"],
            "modules": GUIDE_MODULE_KEYS,
            "message": "اسألني عن الزبائن، الموردين، المنتجات، المبيعات، الدفعات، المخازن، المصروفات، الصيانة، التقارير، أو دفتر الأستاذ.",
            "expert_mode": "أستطيع إرشادك كسيناريو عمل كامل: قبل العملية، أثناءها، بعد الحفظ، والأخطاء الشائعة.",
        }


_guide_master = None


def get_user_guide_master() -> UserGuideMaster:
    global _guide_master
    if _guide_master is None:
        _guide_master = UserGuideMaster()
    return _guide_master


__all__ = ["UserGuideMaster", "get_user_guide_master", "COMPLETE_USER_GUIDE", "GUIDE_MODULE_KEYS"]

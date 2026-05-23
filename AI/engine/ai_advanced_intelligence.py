"""
AI Advanced Intelligence - ذكاء متقدم لفهم النظام بعمق
يوفر معرفة شاملة بـ workflows، العلاقات، والعمليات
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import re


# خريطة Workflows الكاملة
SYSTEM_WORKFLOWS = {
    'add_customer': {
        'name_ar': 'إضافة زبون جديد',
        'steps': [
            '1. اذهب إلى صفحة الزبائن (/customers)',
            '2. اضغط على "إضافة زبون جديد"',
            '3. أدخل: الاسم، رقم الهاتف، البريد (اختياري)',
            '4. حدد نوع الزبون (فرد/شركة)',
            '5. اضغط حفظ',
        ],
        'route': '/customers/create',
        'permissions': ['manage_customers'],
        'related_models': ['Customer', 'Vehicle'],
    },
    
    'create_service': {
        'name_ar': 'إنشاء طلب صيانة',
        'steps': [
            '1. اذهب إلى صفحة الصيانة (/service)',
            '2. اضغط "طلب صيانة جديد"',
            '3. اختر الزبون',
            '4. اختر السيارة (أو أضف جديدة)',
            '5. حدد نوع الصيانة ووصف المشكلة',
            '6. أضف القطع والمهام (اختياري)',
            '7. احفظ الطلب',
        ],
        'route': '/service/create',
        'permissions': ['manage_services'],
        'related_models': ['ServiceRequest', 'Customer', 'Vehicle', 'ServicePart', 'ServiceTask'],
    },
    
    'create_invoice': {
        'name_ar': 'إنشاء فاتورة',
        'steps': [
            '1. اذهب إلى المبيعات (/sales)',
            '2. اضغط "فاتورة جديدة"',
            '3. اختر الزبون',
            '4. أضف المنتجات والكميات',
            '5. النظام يحسب VAT تلقائياً',
            '6. اختر طريقة الدفع',
            '7. احفظ وطباعة',
        ],
        'route': '/sales/new',
        'permissions': ['manage_sales'],
        'related_models': ['Invoice', 'SaleLine', 'Product', 'Customer', 'Payment'],
    },
    
    'partner_settlement': {
        'name_ar': 'تسوية شريك',
        'steps': [
            '1. اذهب إلى الموردين -> الشركاء',
            '2. اختر الشريك المطلوب',
            '3. اضغط "تسوية جديدة"',
            '4. النظام يحسب المستحقات تلقائياً',
            '5. راجع التفاصيل',
            '6. حدد طريقة الدفع',
            '7. اعتمد التسوية',
        ],
        'route': '/vendors/partners/settlement',
        'permissions': ['manage_partners', 'financial_admin'],
        'related_models': ['Partner', 'PartnerSettlement', 'Payment'],
        'owner_only': False,
    },
    
    'backup_database': {
        'name_ar': 'نسخ احتياطي لقاعدة البيانات',
        'steps': [
            '1. اذهب إلى قائمة المستخدم (أعلى يمين)',
            '2. اختر "نسخ احتياطي"',
            '3. النظام ينشئ نسخة تلقائياً',
            '4. النسخة تُحفظ في instance/backups/',
            '5. يمكنك تحميلها',
        ],
        'route': '/backup',
        'permissions': ['backup_database'],
        'owner_only': True,
    },
}


# خريطة العلاقات بين الجداول
TABLE_RELATIONSHIPS = {
    'Customer': {
        'has_many': ['ServiceRequest', 'Invoice', 'Vehicle', 'Note'],
        'belongs_to': [],
        'description': 'الزبون هو محور النظام - له طلبات صيانة، فواتير، سيارات',
    },
    'ServiceRequest': {
        'has_many': ['ServicePart', 'ServiceTask'],
        'belongs_to': ['Customer', 'Vehicle', 'User'],
        'description': 'طلب الصيانة يرتبط بزبون وسيارة، ويحتوي على قطع ومهام',
    },
    'Invoice': {
        'has_many': ['SaleLine', 'Payment'],
        'belongs_to': ['Customer', 'User'],
        'description': 'الفاتورة ترتبط بزبون، وتحتوي على أسطر بيع ودفعات',
    },
    'Product': {
        'has_many': ['SaleLine', 'ServicePart', 'StockLevel'],
        'belongs_to': ['Supplier'],
        'description': 'المنتج يُستخدم في المبيعات والصيانة، وله مخزون',
    },
    'Payment': {
        'belongs_to': ['Customer', 'Invoice', 'User'],
        'description': 'الدفعة ترتبط بفاتورة وزبون',
    },
}


# معلومات مفصلة عن الحقول المهمة
FIELD_EXPLANATIONS = {
    'payment_status': {
        'values': ['PENDING', 'COMPLETED', 'PARTIAL', 'REFUNDED'],
        'description_ar': 'حالة الدفع',
        'usage': 'يحدد ما إذا تم الدفع كاملاً أو جزئياً أو معلق',
    },
    'service_status': {
        'values': ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'],
        'description_ar': 'حالة الصيانة',
        'usage': 'يتتبع مراحل طلب الصيانة من البداية للنهاية',
    },
    'vat_rate': {
        'type': 'decimal',
        'description_ar': 'نسبة ضريبة القيمة المضافة',
        'usage': '16% في فلسطين، 17% في إسرائيل',
    },
}


# أسئلة شائعة متقدمة
ADVANCED_FAQ = {
    'كيف أضيف زبون': {
        'workflow': 'add_customer',
        'quick_answer': 'اذهب لصفحة الزبائن واضغط "إضافة زبون جديد"',
    },
    'كيف أنشئ فاتورة': {
        'workflow': 'create_invoice',
        'quick_answer': 'اذهب للمبيعات واضغط "فاتورة جديدة"',
    },
    'كيف أعمل صيانة': {
        'workflow': 'create_service',
        'quick_answer': 'اذهب لصفحة الصيانة واضغط "طلب صيانة جديد"',
    },
    'كيف أسوي شريك': {
        'workflow': 'partner_settlement',
        'quick_answer': 'اذهب للموردين -> الشركاء -> اختر الشريك -> "تسوية جديدة"',
    },
}


def get_workflow_guide(workflow_key: str) -> Optional[Dict[str, Any]]:
    """الحصول على دليل workflow كامل"""
    return SYSTEM_WORKFLOWS.get(workflow_key)


def find_workflow_by_query(query: str) -> Optional[Dict[str, Any]]:
    """البحث عن workflow مناسب للسؤال"""
    query_lower = query.lower()
    
    # البحث في الأسئلة الشائعة أولاً
    for question, data in ADVANCED_FAQ.items():
        if any(word in query_lower for word in question.split()):
            workflow = SYSTEM_WORKFLOWS.get(data['workflow'])
            if workflow:
                return {
                    'workflow': workflow,
                    'workflow_key': data['workflow'],
                    'quick_answer': data['quick_answer'],
                }
    
    # البحث المباشر في workflows
    keywords_map = {
        'زبون': 'add_customer',
        'صيانة': 'create_service',
        'فاتورة': 'create_invoice',
        'شريك': 'partner_settlement',
        'نسخ احتياطي': 'backup_database',
        'backup': 'backup_database',
        'invoice': 'create_invoice',
        'service': 'create_service',
        'customer': 'add_customer',
    }
    
    for keyword, workflow_key in keywords_map.items():
        if keyword in query_lower:
            workflow = SYSTEM_WORKFLOWS.get(workflow_key)
            if workflow:
                return {
                    'workflow': workflow,
                    'workflow_key': workflow_key,
                }
    
    return None


def explain_relationship(model_name: str) -> Optional[str]:
    """شرح العلاقات لنموذج معين"""
    rel = TABLE_RELATIONSHIPS.get(model_name)
    if not rel:
        return None
    
    explanation = f"**العلاقات - {model_name}:**\n\n"
    
    if rel.get('description'):
        explanation += f"📝 {rel['description']}\n\n"
    
    if rel.get('has_many'):
        explanation += f"🔗 **يملك (has_many):** {', '.join(rel['has_many'])}\n"
    
    if rel.get('belongs_to'):
        explanation += f"🔗 **ينتمي لـ (belongs_to):** {', '.join(rel['belongs_to'])}\n"
    
    return explanation


def explain_field(field_name: str) -> Optional[str]:
    """شرح حقل معين"""
    field = FIELD_EXPLANATIONS.get(field_name)
    if not field:
        return None
    
    explanation = f"**الحقل: {field_name}**\n\n"
    
    if field.get('description_ar'):
        explanation += f"📝 **الوصف:** {field['description_ar']}\n"
    
    if field.get('type'):
        explanation += f"🔢 **النوع:** {field['type']}\n"
    
    if field.get('values'):
        explanation += f"✅ **القيم الممكنة:** {', '.join(field['values'])}\n"
    
    if field.get('usage'):
        explanation += f"💡 **الاستخدام:** {field['usage']}\n"
    
    return explanation


def get_deep_system_knowledge(query: str) -> Optional[str]:
    """معرفة عميقة بالنظام - فهم متقدم"""
    query_lower = query.lower()
    
    # فهم الأسئلة المعقدة
    complex_patterns = {
        r'(كيف|how).*(عمل|أعمل|do|make)': 'workflow_needed',
        r'(ما هو|what is|شرح|explain).*(حقل|field)': 'field_explanation',
        r'(علاقة|relation|link).*(بين|between)': 'relationship_explanation',
        r'(خطوات|steps|مراحل)': 'workflow_needed',
    }
    
    for pattern, intent in complex_patterns.items():
        if re.search(pattern, query_lower):
            if intent == 'workflow_needed':
                workflow_result = find_workflow_by_query(query)
                if workflow_result:
                    return format_workflow_response(workflow_result)
            
            elif intent == 'field_explanation':
                # استخراج اسم الحقل
                for field_name in FIELD_EXPLANATIONS.keys():
                    if field_name.lower() in query_lower:
                        return explain_field(field_name)
            
            elif intent == 'relationship_explanation':
                # استخراج اسم النموذج
                for model_name in TABLE_RELATIONSHIPS.keys():
                    if model_name.lower() in query_lower:
                        return explain_relationship(model_name)
    
    return None


def format_workflow_response(workflow_result: Dict[str, Any]) -> str:
    """تنسيق رد workflow"""
    workflow = workflow_result['workflow']
    
    response = f"📋 **{workflow['name_ar']}**\n\n"
    
    if workflow_result.get('quick_answer'):
        response += f"💡 **الإجابة السريعة:** {workflow_result['quick_answer']}\n\n"
    
    response += "📝 **الخطوات التفصيلية:**\n"
    for step in workflow['steps']:
        response += f"{step}\n"
    
    response += f"\n🔗 **الرابط:** {workflow['route']}\n"
    
    if workflow.get('related_models'):
        response += f"\n📊 **الجداول المرتبطة:** {', '.join(workflow['related_models'])}\n"
    
    if workflow.get('permissions'):
        response += f"\n🔐 **الصلاحيات المطلوبة:** {', '.join(workflow['permissions'])}\n"
    
    return response


def get_all_workflows_list() -> str:
    """قائمة بجميع workflows المتاحة"""
    response = "📚 **جميع العمليات المتاحة في النظام:**\n\n"
    
    for key, workflow in SYSTEM_WORKFLOWS.items():
        response += f"• **{workflow['name_ar']}** - {workflow['route']}\n"
    
    response += "\n💡 اسألني عن أي عملية للحصول على خطوات تفصيلية!"
    
    return response


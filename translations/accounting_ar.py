BANK_STATEMENT_STATUS_AR = {
    'DRAFT': 'مسودة',
    'IMPORTED': 'مستورد',
    'RECONCILED': 'مطابق',
}

RECONCILIATION_STATUS_AR = {
    'DRAFT': 'مسودة',
    'COMPLETED': 'مكتمل',
    'APPROVED': 'معتمد',
}

PROJECT_STATUS_AR = {
    'PLANNED': 'مخطط',
    'ACTIVE': 'قيد التنفيذ',
    'ON_HOLD': 'معلق',
    'COMPLETED': 'منتهي',
    'CANCELLED': 'ملغي',
}

PHASE_STATUS_AR = {
    'PENDING': 'معلق',
    'IN_PROGRESS': 'قيد التنفيذ',
    'COMPLETED': 'مكتمل',
    'CANCELLED': 'ملغي',
}

PROJECT_COST_TYPE_AR = {
    'EXPENSE': 'مصروف',
    'PURCHASE': 'مشتريات',
    'SALARY': 'رواتب',
    'SERVICE': 'خدمة',
    'MATERIAL': 'مواد',
    'OTHER': 'أخرى',
}

PROJECT_REVENUE_TYPE_AR = {
    'SALE': 'مبيعات',
    'SERVICE': 'خدمات',
    'INVOICE': 'فاتورة',
    'MILESTONE': 'إنجاز مرحلة',
    'OTHER': 'أخرى',
}

COST_CENTER_SOURCE_TYPE_AR = {
    'EXPENSE': 'مصروف',
    'SALE': 'مبيعات',
    'SERVICE': 'خدمة',
    'PAYMENT': 'دفعة',
    'PURCHASE': 'مشتريات',
}


BANK_FORM_LABELS_AR = {
    'code': 'الرمز',
    'name': 'اسم الحساب',
    'bank_name': 'اسم البنك',
    'account_number': 'رقم الحساب',
    'iban': 'IBAN',
    'swift_code': 'رمز SWIFT',
    'currency': 'العملة',
    'branch_id': 'الفرع',
    'gl_account_code': 'حساب دفتر الأستاذ',
    'opening_balance': 'الرصيد الافتتاحي',
    'current_balance': 'الرصيد الحالي',
    'last_reconciled_date': 'آخر تسوية',
    'notes': 'ملاحظات',
    'is_active': 'نشط',
}

COST_CENTER_FORM_LABELS_AR = {
    'code': 'الرمز',
    'name': 'الاسم',
    'parent_id': 'المركز الأب',
    'description': 'الوصف',
    'manager_id': 'المدير المسؤول',
    'budget_amount': 'الميزانية المخصصة',
    'actual_amount': 'المصروف الفعلي',
    'is_active': 'نشط',
}

PROJECT_FORM_LABELS_AR = {
    'code': 'رمز المشروع',
    'name': 'اسم المشروع',
    'client_id': 'الزبون',
    'start_date': 'تاريخ البدء',
    'end_date': 'تاريخ الانتهاء',
    'planned_end_date': 'تاريخ الانتهاء المخطط',
    'budget_amount': 'الميزانية',
    'actual_cost': 'التكلفة الفعلية',
    'actual_revenue': 'الإيرادات الفعلية',
    'cost_center_id': 'مركز التكلفة',
    'manager_id': 'مدير المشروع',
    'branch_id': 'الفرع',
    'status': 'الحالة',
    'completion_percentage': 'نسبة الإنجاز',
    'description': 'الوصف',
    'notes': 'ملاحظات',
}

RECONCILIATION_FORM_LABELS_AR = {
    'bank_account_id': 'الحساب البنكي',
    'reconciliation_number': 'رقم التسوية',
    'period_start': 'بداية الفترة',
    'period_end': 'نهاية الفترة',
    'book_balance': 'رصيد الدفاتر',
    'bank_balance': 'رصيد البنك',
    'notes': 'ملاحظات',
}


def get_translated_enum(enum_dict, key, default=None):
    return enum_dict.get(key, default or key)


def get_all_translations():
    return {
        'bank_statement_status': BANK_STATEMENT_STATUS_AR,
        'reconciliation_status': RECONCILIATION_STATUS_AR,
        'project_status': PROJECT_STATUS_AR,
        'phase_status': PHASE_STATUS_AR,
        'project_cost_type': PROJECT_COST_TYPE_AR,
        'project_revenue_type': PROJECT_REVENUE_TYPE_AR,
        'cost_center_source_type': COST_CENTER_SOURCE_TYPE_AR,
        'bank_labels': BANK_FORM_LABELS_AR,
        'cost_center_labels': COST_CENTER_FORM_LABELS_AR,
        'project_labels': PROJECT_FORM_LABELS_AR,
        'reconciliation_labels': RECONCILIATION_FORM_LABELS_AR,
    }



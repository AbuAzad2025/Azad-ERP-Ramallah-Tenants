"""سياسة تخصيص الدفعات على الالتزامات (مبيعات/فواتير)."""


def payment_auto_allocate_enabled() -> bool:
    """هل يُسمح بتخصيص الدفعات تلقائياً على مبيعات/فواتير/خدمات مفتوحة؟"""
    try:
        from models import SystemSettings
        return bool(SystemSettings.get_setting("auto_allocate", False))
    except Exception:
        return False

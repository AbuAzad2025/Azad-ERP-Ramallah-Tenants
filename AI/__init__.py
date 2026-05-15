"""
🤖 AI Module - المساعد الذكي الموحد
================================

مجلد واحد يحتوي على كل شيء متعلق بالمساعد الذكي:

AI/
├── engine/          ← كل ملفات Python
├── data/            ← ملفات JSON (تدريب، تفاعلات، خرائط)
├── templates/       ← قوالب HTML
└── docs/            ← التوثيق

تم التوحيد الكامل في: 2025-10-31
"""

try:
    from AI.engine.ai_access_bind import bind_ai_service_access
    bind_ai_service_access()
except Exception:
    pass

try:
    from AI.engine.ai_controller_security_bind import bind_ai_controller_security
    bind_ai_controller_security()
except Exception:
    pass

try:
    from AI.engine.ai_management_security_bind import bind_ai_management_security
    bind_ai_management_security()
except Exception:
    pass

try:
    from AI.engine.ai_erp_transaction_guard import bind_erp_transaction_guard
    bind_erp_transaction_guard()
except Exception:
    pass

try:
    from AI.engine.ai_flask_feedback_bind import install_ai_flask_feedback_signal
    install_ai_flask_feedback_signal()
except Exception:
    pass

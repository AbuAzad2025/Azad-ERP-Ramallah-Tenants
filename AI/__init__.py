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

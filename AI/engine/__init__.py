"""
🤖 AI Engine - المحرك الرئيسي للمساعد الذكي
════════════════════════════════════════════════════════════════════

هذا الملف المركزي يجمع كل وظائف المساعد الذكي
ويسهّل الاستيراد من أي مكان في النظام

Architecture:
- ai_service.py: المحرك الرئيسي
- ai_database_search.py: البحث في قاعدة البيانات
- ai_conversation.py: المحادثة والذاكرة
- ai_knowledge*.py: قواعد المعرفة
- ai_accounting_professional.py: المحاسبة الاحترافية

Refactored: 2025-11-01
Version: Professional 5.0
"""

# ═══════════════════════════════════════════════════════════════════════════
# CORE SERVICES - الخدمات الأساسية
# ═══════════════════════════════════════════════════════════════════════════

from .ai_service import (
    ai_chat_with_search,
    gather_system_context,
    build_system_message,
    get_system_setting
)

# ═══════════════════════════════════════════════════════════════════════════
# DATABASE SEARCH - البحث في قاعدة البيانات
# ═══════════════════════════════════════════════════════════════════════════

from .ai_database_search import (
    search_database_for_query,
    analyze_query_intent,
    get_time_range
)

# ═══════════════════════════════════════════════════════════════════════════
# CONVERSATION & MEMORY - المحادثة والذاكرة
# ═══════════════════════════════════════════════════════════════════════════

from .ai_conversation import (
    get_or_create_session_memory,
    add_to_memory,
    clear_session_memory,
    get_conversation_context,
    get_local_faq_responses,
    match_local_response,
)

# ═══════════════════════════════════════════════════════════════════════════
# HYBRID ENGINE - المحرك الهجين (Groq + Local)
# ═══════════════════════════════════════════════════════════════════════════

from .ai_hybrid_engine import (
    HybridAIEngine,
    get_hybrid_engine,
    GROQ_API_KEY,
    GROQ_ENABLED
)

# ═══════════════════════════════════════════════════════════════════════════
# ACTION EXECUTOR - محرك تنفيذ العمليات
# ═══════════════════════════════════════════════════════════════════════════

from .ai_action_executor import (
    ActionExecutor,
    parse_user_request
)

# ═══════════════════════════════════════════════════════════════════════════
# REAL-TIME MONITOR - المراقب الفوري
# ═══════════════════════════════════════════════════════════════════════════

RealtimeMonitor = None
ProactiveAssistant = None
get_realtime_monitor = lambda: None
get_system_health_status = lambda: {}

from .ai_event_listeners import register_ai_listeners

# ═══════════════════════════════════════════════════════════════════════════
# AUTO-LEARNING - التعلم التلقائي
# ═══════════════════════════════════════════════════════════════════════════

from .ai_auto_learning import (
    AutoLearningEngine,
    get_auto_learning_engine,
    schedule_daily_scan
)

# ═══════════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASES - قواعد المعرفة
# ═══════════════════════════════════════════════════════════════════════════

from .ai_knowledge import (
    get_knowledge_base,
    analyze_error,
    format_error_response
)

from .ai_knowledge_finance import (
    get_finance_knowledge,
    calculate_palestine_income_tax,
    calculate_vat,
    get_customs_info,
    get_tax_knowledge_detailed
)

from .ai_gl_knowledge import (
    get_gl_knowledge_for_ai,
    explain_gl_entry,
    analyze_gl_batch,
    detect_gl_error,
    suggest_gl_correction,
    explain_any_number,
    trace_transaction_flow
)

from .ai_accounting_professional import (
    get_professional_accounting_knowledge,
    ACCOUNTING_EQUATION,
    DOUBLE_ENTRY_SYSTEM,
    CHART_OF_ACCOUNTS,
    BALANCE_FORMULAS,
    FINANCIAL_STATEMENTS
)

# ═══════════════════════════════════════════════════════════════════════════
# ADVANCED FEATURES - الميزات المتقدمة
# ═══════════════════════════════════════════════════════════════════════════

from .ai_management import (
    save_api_key_encrypted,
    test_api_key,
    list_configured_apis,
    start_training_job,
    get_training_job_status,
    get_live_ai_stats
)

from .ai_self_review import (
    log_interaction,
    check_policy_compliance,
    generate_self_audit_report,
    get_system_status
)

from .ai_auto_discovery import (
    auto_discover_if_needed,
    find_route_by_keyword,
    get_route_suggestions,
    load_system_map,
    build_system_map
)

from .ai_data_awareness import (
    auto_build_if_needed,
    find_model_by_keyword,
    load_data_schema
)

from .ai_integrated_intelligence import (
    IntegratedIntelligence,
    get_integrated_intelligence
)

from .ai_learning_system import (
    LearningSystem,
    get_learning_system
)

from .ai_performance_tracker import (
    PerformanceTracker,
    get_performance_tracker
)

from .ai_python_expert import (
    PythonExpert,
    get_python_expert
)

from .ai_database_expert import (
    DatabaseExpert,
    get_database_expert
)

from .ai_web_expert import (
    WebExpert,
    get_web_expert
)

from .ai_user_guide_master import (
    UserGuideMaster,
    get_user_guide_master
)

from .ai_training_engine import (
    AITrainingEngine,
    get_training_engine
)

from .ai_code_quality_monitor import (
    CodeQualityMonitor,
    get_code_monitor
)

from .ai_permissions import (
    is_ai_enabled,
    is_ai_visible_to_role,
    can_ai_execute_action,
    get_ai_access_level
)

from .ai_self_evolution import (
    SelfEvolutionEngine,
    get_evolution_engine
)

from .ai_unified_mind import (
    UnifiedMind,
    get_unified_mind
)

from .ai_accounting_auditor import (
    AccountingAuditor,
    get_accounting_auditor
)

from .ai_reasoning_engine import (
    ReasoningEngine,
    get_reasoning_engine
)

from .ai_master_controller import (
    MasterController,
    get_master_controller
)

from .ai_continuous_learner import (
    ContinuousLearner,
    get_continuous_learner
)

from .ai_book_reader import (
    BookReader,
    get_book_reader
)

from .ai_deep_memory import (
    DeepMemory,
    get_deep_memory
)

from .ai_comprehension_engine import (
    ComprehensionEngine,
    get_comprehension_engine
)

from .ai_intensive_trainer import (
    IntensiveTrainer,
    get_intensive_trainer
)

from .ai_specialized_training import (
    SpecializedTraining,
    get_specialized_training
)

# ═══════════════════════════════════════════════════════════════════════════
# EXPORTS - التصدير الشامل
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    'get_master_controller',
    'get_continuous_learner',
    'get_book_reader',
    'get_deep_memory',
    'get_comprehension_engine',
    'get_intensive_trainer',
    'get_specialized_training',
    'get_unified_mind',
    'get_reasoning_engine',
    'get_accounting_auditor',
    'get_integrated_intelligence',
    'get_learning_system',
    'get_performance_tracker',
    'get_evolution_engine',
    'get_python_expert',
    'get_database_expert',
    'get_web_expert',
    'get_user_guide_master',
    'get_training_engine',
    'get_code_monitor',
    'is_ai_enabled',
    'is_ai_visible_to_role',
    'can_ai_execute_action',
    # Core Services
    'ai_chat_with_search',
    'gather_system_context',
    'build_system_message',
    'get_system_setting',
    
    # Database Search
    'search_database_for_query',
    'analyze_query_intent',
    'get_time_range',
    
    # Conversation
    'get_or_create_session_memory',
    'add_to_memory',
    'clear_session_memory',
    'get_conversation_context',
    'get_local_faq_responses',
    'match_local_response',
    
    # Hybrid Engine
    'HybridAIEngine',
    'get_hybrid_engine',
    'GROQ_API_KEY',
    'GROQ_ENABLED',
    
    # Action Executor
    'ActionExecutor',
    'parse_user_request',
    
    # Real-time Monitor
    'RealtimeMonitor',
    'ProactiveAssistant',
    'get_realtime_monitor',
    'get_system_health_status',
    'register_ai_listeners',
    
    # Auto-Learning
    'AutoLearningEngine',
    'get_auto_learning_engine',
    'schedule_daily_scan',
    
    # Knowledge Bases
    'get_knowledge_base',
    'analyze_error',
    'format_error_response',
    'get_finance_knowledge',
    'calculate_palestine_income_tax',
    'calculate_vat',
    'get_customs_info',
    'get_tax_knowledge_detailed',
    
    # GL & Accounting
    'get_gl_knowledge_for_ai',
    'explain_gl_entry',
    'analyze_gl_batch',
    'detect_gl_error',
    'suggest_gl_correction',
    'explain_any_number',
    'trace_transaction_flow',
    'get_professional_accounting_knowledge',
    
    # Advanced
    'save_api_key_encrypted',
    'test_api_key',
    'list_configured_apis',
    'start_training_job',
    'get_training_job_status',
    'get_live_ai_stats',
    'log_interaction',
    'check_policy_compliance',
    'generate_self_audit_report',
    'get_system_status',
    'auto_discover_if_needed',
    'find_route_by_keyword',
    'get_route_suggestions',
    'load_system_map',
    'build_system_map',
    'auto_build_if_needed',
    'find_model_by_keyword',
    'load_data_schema'
]

__version__ = '5.0.0'
__author__ = 'Azad Smart Systems - Ahmed Ghannam'
__description__ = 'Professional AI Accountant Assistant Engine'

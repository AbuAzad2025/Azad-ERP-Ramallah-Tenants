"""
🌐 AI Hybrid Engine - المحرك الهجين (Groq + Local)
════════════════════════════════════════════════════════════════════

وظيفة هذا الملف:
- التبديل الذكي بين Groq API والمعرفة المحلية
- الـ Fallback التلقائي عند فشل Groq
- ضمان نفس الكفاءة في الحالتين

Created: 2025-11-01
Version: 1.0
"""

import json
import os
from typing import Dict, Any, Optional
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════════
# 🔧 CONFIGURATION - الإعدادات
# ═══════════════════════════════════════════════════════════════════════════

import os
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_ENABLED = True
HYBRID_MODE = True  # Groq + Local
FALLBACK_TO_LOCAL = True  # عند فشل Groq


# ═══════════════════════════════════════════════════════════════════════════
# 🌐 HYBRID ENGINE - المحرك الهجين
# ═══════════════════════════════════════════════════════════════════════════

class HybridAIEngine:
    """
    المحرك الهجين الذكي
    
    يستخدم Groq عند التوفر
    يرجع للمعرفة المحلية عند الفشل
    """
    
    def __init__(self):
        self.groq_enabled = GROQ_ENABLED
        self.groq_failures = []
        self.last_mode = None
    
    def chat(self, message: str, system_context: str, conversation_history: list = None) -> Dict[str, Any]:
        """
        المحادثة الهجينة
        
        Args:
            message: رسالة المستخدم
            system_context: سياق النظام
            conversation_history: تاريخ المحادثة
        
        Returns:
            {
                'response': 'الرد',
                'mode': 'groq' أو 'local',
                'confidence': 0-100,
                'sources': []
            }
        """
        
        # محاولة 1: Groq API
        if self.groq_enabled and GROQ_API_KEY:
            groq_result = self._try_groq(message, system_context, conversation_history)
            
            if groq_result['success']:
                self.last_mode = 'groq'
                return {
                    'response': groq_result['response'],
                    'mode': 'groq',
                    'confidence': 95,
                    'sources': ['Groq API - Llama 3.3 70B'],
                    'processing_time': groq_result.get('time', 0)
                }
        
        # محاولة 2: Local Fallback
        local_result = self._use_local(message, system_context)
        
        self.last_mode = 'local'
        return {
            'response': local_result['response'],
            'mode': 'local',
            'confidence': local_result['confidence'],
            'sources': local_result['sources'],
            'fallback_reason': local_result.get('reason', 'Groq unavailable')
        }
    
    def _try_groq(self, message: str, system_context: str, history: list = None) -> Dict[str, Any]:
        """
        محاولة استخدام Groq API
        
        Returns:
            {
                'success': True/False,
                'response': 'الرد',
                'time': 0.5
            }
        """
        try:
            import requests
            import time
            
            start_time = time.time()
            
            url = "https://api.groq.com/openai/v1/chat/completions"
            
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            
            # بناء الرسائل
            messages = [
                {"role": "system", "content": system_context}
            ]
            
            # إضافة التاريخ
            if history:
                messages.extend(history[-10:])  # آخر 10 رسائل
            
            # الرسالة الحالية
            messages.append({"role": "user", "content": message})
            
            data = {
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 2000,
                "top_p": 0.9
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                ai_response = result['choices'][0]['message']['content']
                
                processing_time = time.time() - start_time
                
                return {
                    'success': True,
                    'response': ai_response,
                    'time': processing_time
                }
            else:
                # فشل Groq
                self.groq_failures.append({
                    'timestamp': datetime.now().isoformat(),
                    'status_code': response.status_code,
                    'error': response.text[:200]
                })
                
                return {
                    'success': False,
                    'error': f'Groq API error: {response.status_code}'
                }
        
        except requests.exceptions.Timeout:
            self.groq_failures.append({
                'timestamp': datetime.now().isoformat(),
                'error': 'Timeout'
            })
            
            return {
                'success': False,
                'error': 'Groq timeout'
            }
        
        except Exception as e:
            self.groq_failures.append({
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            })
            
            return {
                'success': False,
                'error': str(e)
            }
    
    def _use_local(self, message: str, system_context: str) -> Dict[str, Any]:
        """
        استخدام المعرفة المحلية
        
        نفس الكفاءة - بدون Groq
        """
        from AI.engine.ai_conversation import match_local_response
        from AI.engine.ai_database_search import search_database_for_query
        from AI.engine.ai_accounting_professional import get_professional_accounting_knowledge
        
        # 1. محاولة الرد السريع المحلي
        quick_response = match_local_response(message)
        if quick_response:
            return {
                'response': quick_response,
                'confidence': 100,
                'sources': ['Local FAQ - Fast Response'],
                'reason': 'Quick local match'
            }
        
        # 2. البحث في قاعدة البيانات
        db_results = search_database_for_query(message)
        
        # 3. بناء رد محلي ذكي
        local_response = self._build_smart_local_response(message, db_results)
        
        return {
            'response': local_response['text'],
            'confidence': local_response['confidence'],
            'sources': local_response['sources'],
            'reason': 'Local intelligence'
        }
    
    def _build_smart_local_response(self, message: str, db_results: Dict) -> Dict[str, Any]:
        """
        بناء رد ذكي محلياً
        
        يحلل السؤال ويبني رد احترافي بدون Groq
        """
        message_lower = message.lower()
        
        # تحليل نوع السؤال
        intent = db_results.get('intent', {})
        
        # ردود ذكية حسب النوع
        if intent.get('type') == 'count':
            # أسئلة العد
            response_parts = ['📊 **الإحصائيات المطلوبة:**\n']
            
            for key, value in db_results.items():
                if key.endswith('_count') and isinstance(value, int):
                    label = key.replace('_count', '').replace('_', ' ').title()
                    response_parts.append(f'• {label}: {value:,}')
            
            return {
                'text': '\n'.join(response_parts),
                'confidence': 90,
                'sources': ['Database Query', 'Local Intelligence']
            }
        
        elif intent.get('type') == 'balance':
            # أسئلة الأرصدة
            return {
                'text': """📊 **شرح الأرصدة:**

🔵 **رصيد الزبون:**
الصيغة: (المبيعات + الفواتير + الخدمات) - (الدفعات الواردة)
• سالب (-) = 🔴 الزبون عليه يدفع
• موجب (+) = 🟢 للزبون رصيد عندنا

🔵 **رصيد المورد:**
الصيغة: (المشتريات + الشحنات) - (الدفعات الصادرة)
• سالب (-) = 🔴 علينا ندفع للمورد
• موجب (+) = 🟢 دفعنا زيادة

هل تريد شرح رصيد معين؟ أعطني رقم الزبون/المورد.""",
                'confidence': 100,
                'sources': ['Accounting Knowledge Base', 'Memory']
            }
        
        else:
            # رد عام مع البيانات
            response = f"🤖 **تحليل محلي:**\n\n"
            response += f"السؤال: {message}\n\n"
            
            if db_results:
                response += "📊 **البيانات المتوفرة:**\n"
                for key, value in list(db_results.items())[:5]:
                    if key != 'intent':
                        response += f"• {key}: {value}\n"
            
            response += "\n💡 يمكنني مساعدتك أكثر - وضّح طلبك أو اسألني بشكل محدد."
            
            return {
                'text': response,
                'confidence': 70,
                'sources': ['Database', 'Local Analysis']
            }
    
    def get_status(self) -> Dict[str, Any]:
        """حالة المحرك الهجين"""
        return {
            'groq_enabled': self.groq_enabled,
            'last_mode': self.last_mode,
            'groq_failures': len(self.groq_failures),
            'recent_failures': self.groq_failures[-5:] if self.groq_failures else [],
            'hybrid_mode': HYBRID_MODE,
            'fallback_enabled': FALLBACK_TO_LOCAL
        }


# ═══════════════════════════════════════════════════════════════════════════
# 🎯 SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════

_hybrid_engine = None

def get_hybrid_engine() -> HybridAIEngine:
    """الحصول على المحرك الهجين (Singleton)"""
    global _hybrid_engine
    
    if _hybrid_engine is None:
        _hybrid_engine = HybridAIEngine()
    
    return _hybrid_engine


__all__ = [
    'HybridAIEngine',
    'get_hybrid_engine',
    'GROQ_API_KEY',
    'GROQ_ENABLED'
]


"""AI NLP Engine.

Lightweight Arabic/English intent understanding for the local AI assistant.
This is not a neural network and does not pretend to be one; it is a maintainable
rule-based NLP layer designed for production reliability inside the Flask app.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple


ARABIC_DIACRITICS = re.compile(r"[\u0617-\u061A\u064B-\u0652]")


def normalize_text(text: str) -> str:
    """Normalize Arabic/English text for matching without destroying meaning."""
    value = str(text or "").strip().lower()
    value = ARABIC_DIACRITICS.sub("", value)
    value = re.sub("[إأٱآ]", "ا", value)
    value = value.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    value = re.sub(r"\s+", " ", value)
    return value


class ArabicSentenceAnalyzer:
    """Small sentence analyzer for Arabic/English business queries."""

    VERB_PATTERNS = {
        "question": r"\b(كم|ماذا|ما|من|اين|متي|كيف|هل|لماذا|what|where|when|how|why)\b",
        "command": r"\b(اعطني|ارني|اعرض|احسب|حلل|افحص|انشئ|اضف|احذف|عدل|create|add|delete|update|show|calculate)\b",
        "request": r"\b(اريد|احتاج|ممكن|لو سمحت|من فضلك|عايز|بدي|please|need|want)\b",
        "analysis": r"\b(حلل|افحص|راجع|قيم|اختبر|تاكد|analyze|review|check)\b",
        "comparison": r"\b(قارن|الفرق|ايهما|افضل|اسوا|compare|versus|vs)\b",
        "search": r"\b(ابحث|جد|وين|فين|اين|دلني|وصلني|افتح|open|find)\b",
    }

    ENTITY_PATTERNS = {
        "customer": r"\b(زبون|زبائن|زبون|زبائن|الزباين|الزبائن|customer|customers)\b",
        "supplier": r"\b(مورد|موردين|supplier|vendors?)\b",
        "product": r"\b(منتج|منتجات|قطعة|قطع|product|part|parts)\b",
        "warehouse": r"\b(مخزن|مخازن|مستودع|مخزون|warehouse|inventory|stock)\b",
        "invoice": r"\b(فاتورة|فواتير|invoice|invoices)\b",
        "payment": r"\b(دفعة|دفع|مدفوعات|payment|payments)\b",
        "expense": r"\b(نفقة|نفقات|مصروف|مصاريف|expense|expenses)\b",
        "service": r"\b(صيانة|اصلاح|تصليح|service|repair)\b",
        "accounting": r"\b(محاسبة|دفتر|قيد|قيود|ميزان|ارصدة|ledger|accounting|gl)\b",
        "money": r"(\d+[\d,]*\.?\d*)\s*(شيقل|دولار|دينار|يورو|₪|\$|€|ils|usd|jod|eur)",
        "time": r"\b(اليوم|امس|غدا|الاسبوع|الشهر|السنة|today|yesterday|week|month|year)\b",
        "number": r"\b\d+[\d,]*(?:\.\d+)?\b",
        "percentage": r"\b\d+\.?\d*%",
    }

    CONTEXT_WORDS = {
        "positive": ("ممتاز", "رائع", "جيد", "عظيم", "ناجح", "مبروك", "great", "good"),
        "negative": ("سيء", "فاشل", "ضعيف", "مشكلة", "خطا", "عطل", "bad", "error", "problem"),
        "urgent": ("سريع", "عاجل", "فوري", "الان", "حالا", "urgent", "asap", "now"),
        "polite": ("لو سمحت", "من فضلك", "شكرا", "جزاك الله", "please", "thanks"),
    }

    def extract_verb_intent(self, text: str) -> Optional[str]:
        normalized = normalize_text(text)
        for intent, pattern in self.VERB_PATTERNS.items():
            if re.search(pattern, normalized):
                return intent
        if "؟" in text or "?" in text:
            return "question"
        if str(text).strip().endswith("!"):
            return "command"
        return None

    def extract_entities(self, text: str) -> Dict[str, List[Any]]:
        normalized = normalize_text(text)
        entities: Dict[str, List[Any]] = {}
        for entity_type, pattern in self.ENTITY_PATTERNS.items():
            matches = re.findall(pattern, normalized, re.IGNORECASE)
            if matches:
                entities[entity_type] = matches
        return entities

    def detect_sentiment(self, text: str) -> str:
        normalized = normalize_text(text)
        positive = sum(1 for word in self.CONTEXT_WORDS["positive"] if word in normalized)
        negative = sum(1 for word in self.CONTEXT_WORDS["negative"] if word in normalized)
        if positive > negative:
            return "positive"
        if negative > positive:
            return "negative"
        return "neutral"

    def analyze(self, text: str) -> Dict[str, Any]:
        normalized = normalize_text(text)
        return {
            "intent": self.extract_verb_intent(text),
            "entities": self.extract_entities(text),
            "sentiment": self.detect_sentiment(text),
            "has_question_mark": "؟" in text or "?" in text,
            "word_count": len(normalized.split()),
            "is_polite": any(word in normalized for word in self.CONTEXT_WORDS["polite"]),
            "is_urgent": any(word in normalized for word in self.CONTEXT_WORDS["urgent"]),
        }


class SemanticUnderstanding:
    """Semantic concept matcher for business/accounting questions."""

    CONCEPTS = {
        "financial_performance": {
            "keywords": ("ربح", "خسارة", "مبيعات", "ايرادات", "نفقات", "دخل", "profit", "loss", "revenue"),
            "related": ("محاسبة", "مالية", "اداء", "accounting", "finance"),
            "intent": "analysis",
        },
        "customer_satisfaction": {
            "keywords": ("رضا", "شكوي", "تقييم", "خدمة", "جودة", "complaint", "feedback"),
            "related": ("زبائن", "تجربة", "customers"),
            "intent": "feedback",
        },
        "inventory_management": {
            "keywords": ("مخزون", "بضاعة", "قطع", "منتجات", "نفاد", "inventory", "stock"),
            "related": ("مستودع", "توفر", "كمية", "warehouse"),
            "intent": "stock_check",
        },
        "performance_metrics": {
            "keywords": ("اداء", "نسبة", "معدل", "كفاءة", "انتاجية", "performance", "metrics"),
            "related": ("قياس", "تقييم", "مؤشر"),
            "intent": "analysis",
        },
        "system_navigation": {
            "keywords": ("صفحة", "رابط", "افتح", "وين", "اين", "دلني", "page", "link", "open"),
            "related": ("قائمة", "مسار", "route"),
            "intent": "navigation",
        },
    }

    def find_concept(self, text: str) -> Optional[Tuple[str, float]]:
        normalized = normalize_text(text)
        best_match = None
        best_score = 0
        for concept_name, concept in self.CONCEPTS.items():
            score = sum(2 for kw in concept["keywords"] if kw in normalized)
            score += sum(1 for related in concept["related"] if related in normalized)
            if score > best_score:
                best_score = score
                best_match = concept_name
        if best_match and best_score > 0:
            return best_match, min(1.0, best_score / 8.0)
        return None

    def understand_question(self, text: str) -> Dict[str, Any]:
        normalized = normalize_text(text)
        concept = self.find_concept(normalized)
        return {
            "main_concept": concept[0] if concept else None,
            "confidence": concept[1] if concept else 0.0,
            "is_comparative": any(word in normalized for word in ("افضل", "اسوا", "مقارنة", "الفرق", "compare", "vs")),
            "is_temporal": any(word in normalized for word in ("اليوم", "امس", "الاسبوع", "الشهر", "today", "week", "month")),
            "is_quantitative": any(word in normalized for word in ("كم", "عدد", "مجموع", "متوسط", "how many", "count", "total")),
        }


class AdvancedIntentDetector:
    """Intent detector combining sentence and semantic signals."""

    def __init__(self):
        self.sentence_analyzer = ArabicSentenceAnalyzer()
        self.semantic_engine = SemanticUnderstanding()

    def detect_intent(self, text: str) -> Dict[str, Any]:
        sentence = self.sentence_analyzer.analyze(text)
        semantic = self.semantic_engine.understand_question(text)
        normalized = normalize_text(text)

        result = {"primary_intent": "general", "secondary_intents": [], "confidence": 0.4, "reasoning": []}

        if semantic["is_quantitative"]:
            result.update(primary_intent="quantitative_query", confidence=0.9)
            result["reasoning"].append("يطلب رقماً أو عدداً")
        elif semantic["main_concept"] in {"financial_performance", "performance_metrics"}:
            result.update(primary_intent="performance_analysis", confidence=0.85)
            result["reasoning"].append("يطلب تحليل أداء")
        elif semantic["is_comparative"]:
            result.update(primary_intent="comparison", confidence=0.9)
            result["reasoning"].append("يقارن بين شيئين")
        elif sentence["intent"] == "search" or semantic["main_concept"] == "system_navigation":
            result.update(primary_intent="navigation", confidence=0.9)
            result["reasoning"].append("يبحث عن صفحة أو مسار")
        elif sentence["intent"] == "command":
            result.update(primary_intent="executable_command", confidence=0.8)
            result["reasoning"].append("يطلب تنفيذ إجراء")
        elif any(word in normalized for word in ("ما هو", "ما هي", "اشرح", "عرف", "explain", "what is")):
            result.update(primary_intent="explanation_request", confidence=0.9)
            result["reasoning"].append("يطلب شرحاً أو تعريفاً")
        elif "احسب" in normalized or "calculate" in normalized:
            result.update(primary_intent="calculation", confidence=0.9)
            result["reasoning"].append("يطلب حساباً")

        if not result["reasoning"]:
            result["reasoning"].append("لم تظهر نية متخصصة بوضوح")
        if semantic["is_temporal"]:
            result["secondary_intents"].append("time_scoped")
        if sentence["is_urgent"]:
            result["secondary_intents"].append("urgent")
        if sentence["is_polite"]:
            result["secondary_intents"].append("polite")
        return result


class ContextualProcessor:
    """Bounded context processor to avoid unbounded memory growth."""

    def __init__(self, max_messages: int = 20):
        self.conversation_history: Deque[Dict[str, Any]] = deque(maxlen=max_messages)
        self.current_topic: Optional[str] = None
        self.mentioned_entities: set[str] = set()

    def add_message(self, text: str, analysis: Dict[str, Any]) -> None:
        self.conversation_history.append({"text": text, "analysis": analysis})
        sentence = analysis.get("sentence_structure", {})
        for entity_type in sentence.get("entities", {}).keys():
            self.mentioned_entities.add(entity_type)
        concept = analysis.get("semantic_meaning", {}).get("main_concept")
        if concept:
            self.current_topic = concept

    def resolve_references(self, text: str) -> str:
        normalized = normalize_text(text)
        resolved = str(text or "")
        if any(ref in normalized for ref in ("منهم", "منها", "هذا", "ذلك", "تلك")):
            if "customer" in self.mentioned_entities:
                resolved = resolved.replace("منهم", "من الزبائن")
            elif "product" in self.mentioned_entities:
                resolved = resolved.replace("منها", "من المنتجات")
        return resolved

    def get_context_clues(self) -> Dict[str, Any]:
        return {
            "current_topic": self.current_topic,
            "mentioned_entities": sorted(self.mentioned_entities),
            "conversation_length": len(self.conversation_history),
        }


class IntelligentNLPEngine:
    """Main NLP facade."""

    def __init__(self):
        self.intent_detector = AdvancedIntentDetector()
        self.context_processor = ContextualProcessor()

    def process(self, text: str) -> Dict[str, Any]:
        resolved_text = self.context_processor.resolve_references(text)
        intent = self.intent_detector.detect_intent(resolved_text)
        sentence = self.intent_detector.sentence_analyzer.analyze(resolved_text)
        semantic = self.intent_detector.semantic_engine.understand_question(resolved_text)
        result = {
            "original_text": text,
            "resolved_text": resolved_text,
            "normalized_text": normalize_text(resolved_text),
            "intent": intent,
            "sentence_structure": sentence,
            "semantic_meaning": semantic,
            "context": self.context_processor.get_context_clues(),
        }
        self.context_processor.add_message(text, result)
        return result

    def explain_understanding(self, result: Dict[str, Any]) -> str:
        reasoning = result.get("intent", {}).get("reasoning", [])
        return f"""🧠 **فهمي للسؤال:**

📝 **النص:** {result.get('original_text', '')}

🎯 **النية الرئيسية:** {result.get('intent', {}).get('primary_intent')}
   الثقة: {float(result.get('intent', {}).get('confidence', 0))*100:.0f}%

💭 **السبب:**
{chr(10).join(f'   • {r}' for r in reasoning)}

📊 **التحليل:**
   • المفهوم: {result.get('semantic_meaning', {}).get('main_concept')}
   • نوع السؤال: {'كمي' if result.get('semantic_meaning', {}).get('is_quantitative') else 'نوعي'}
   • له بُعد زمني: {'نعم' if result.get('semantic_meaning', {}).get('is_temporal') else 'لا'}

🔗 **السياق:**
   • الموضوع الحالي: {result.get('context', {}).get('current_topic')}
   • الكيانات المذكورة: {', '.join(result.get('context', {}).get('mentioned_entities', [])[:5])}
"""


_global_nlp_engine: Optional[IntelligentNLPEngine] = None


def get_nlp_engine() -> IntelligentNLPEngine:
    global _global_nlp_engine
    if _global_nlp_engine is None:
        _global_nlp_engine = IntelligentNLPEngine()
    return _global_nlp_engine


def understand_text(text: str, explain: bool = False) -> Dict[str, Any]:
    engine = get_nlp_engine()
    result = engine.process(text)
    if explain:
        result["explanation"] = engine.explain_understanding(result)
    return result


__all__ = [
    "normalize_text",
    "ArabicSentenceAnalyzer",
    "SemanticUnderstanding",
    "AdvancedIntentDetector",
    "ContextualProcessor",
    "IntelligentNLPEngine",
    "get_nlp_engine",
    "understand_text",
]

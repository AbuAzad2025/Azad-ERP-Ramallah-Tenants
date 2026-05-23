"""
AI Intelligence Engine - محرك الذكاء الحقيقي
يبتكر، يفهم، يدرك، يتحسس، يشعر، يحاسب، يقاضي، يتفاعل
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional
from sqlalchemy import func, desc, and_
from extensions import db


def analyze_customer_health(customer_id: int = None) -> Dict[str, Any]:
    """تحليل ذكي لصحة الزبائن - يدرك المشاكل والفرص"""
    from models import Customer, Invoice, Payment
    
    if customer_id:
        # تحليل زبون واحد
        customer = db.session.get(Customer, customer_id)
        if not customer:
            return {'error': 'الزبون غير موجود'}
        
        # حساب الأرقام
        total_invoices = db.session.query(func.sum(Invoice.total_amount)).filter(
            Invoice.customer_id == customer_id
        ).scalar() or 0
        
        total_payments = db.session.query(func.sum(Payment.total_amount)).filter(
            Payment.customer_id == customer_id,
            Payment.direction == 'IN'
        ).scalar() or 0
        
        balance = float(total_invoices) - float(total_payments)
        
        # التحليل الذكي
        analysis = {
            'customer_name': customer.name,
            'total_invoices': float(total_invoices),
            'total_payments': float(total_payments),
            'balance': balance,
            'status': 'جيد',
            'alerts': [],
            'opportunities': [],
            'recommendations': []
        }
        
        # 🚨 الإدراك والتحسس - اكتشاف المشاكل
        if balance > 5000:
            analysis['status'] = '⚠️ خطر'
            analysis['alerts'].append(f'رصيد مرتفع جداً: {balance:.2f}₪')
            analysis['recommendations'].append('اتصل بالزبون فوراً لتحصيل المستحقات')
        elif balance > 1000:
            analysis['status'] = '⚠️ انتباه'
            analysis['alerts'].append(f'رصيد متوسط: {balance:.2f}₪')
            analysis['recommendations'].append('جدولة متابعة خلال أسبوع')
        elif balance < -1000:
            analysis['status'] = '💰 رصيد له'
            analysis['alerts'].append(f'لديه رصيد: {abs(balance):.2f}₪')
            analysis['recommendations'].append('يمكن استخدامه في مشتريات قادمة')
        
        # 💡 الفرص
        invoices_count = db.session.query(func.count(Invoice.id)).filter(
            Invoice.customer_id == customer_id
        ).scalar() or 0
        
        if invoices_count > 10:
            analysis['opportunities'].append('زبون مميز - قدم له برنامج ولاء!')
        
        # آخر معاملة
        last_invoice = db.session.query(Invoice).filter(
            Invoice.customer_id == customer_id
        ).order_by(desc(Invoice.created_at)).first()
        
        if last_invoice:
            days_since = (datetime.now(timezone.utc) - last_invoice.created_at).days
            if days_since > 90:
                analysis['alerts'].append(f'لم يشتري منذ {days_since} يوم!')
                analysis['recommendations'].append('اتصل به - قد يكون غير راضٍ أو انتقل لمنافس')
                analysis['opportunities'].append('فرصة لاستعادته - قدم عرض خاص')
        
        return analysis
    
    else:
        # تحليل عام لجميع الزبائن
        total_customers = Customer.query.count()
        
        # زبائن بأرصدة مرتفعة (خطر)
        high_risk = db.session.query(Customer).join(Invoice).group_by(Customer.id).having(
            func.sum(Invoice.total_amount) > 5000
        ).count()
        
        return {
            'total_customers': total_customers,
            'high_risk': high_risk,
            'recommendations': [
                f'{high_risk} زبون برصيد خطر - راجع تقرير AR Aging',
                'تابع التحصيلات بانتظام'
            ]
        }


def analyze_inventory_intelligence() -> Dict[str, Any]:
    """تحليل ذكي للمخزون - يدرك النقص والزيادة"""
    from models import Product, StockLevel
    
    # المنتجات تحت الحد الأدنى
    low_stock = db.session.query(Product).join(StockLevel).filter(
        StockLevel.quantity < Product.min_stock_level
    ).all()
    
    # المنتجات الراكدة (لم تبع منذ 6 أشهر)
    six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
    
    analysis = {
        'status': 'جيد',
        'alerts': [],
        'opportunities': [],
        'recommendations': [],
        'critical_actions': []
    }
    
    # 🚨 التحسس - نقص المخزون
    if len(low_stock) > 0:
        analysis['status'] = '⚠️ انتباه'
        analysis['alerts'].append(f'{len(low_stock)} منتج تحت الحد الأدنى!')
        analysis['critical_actions'].append('اطلب قطع غيار فوراً قبل نفاد المخزون')
        
        # تفاصيل
        for product in low_stock[:5]:  # أول 5
            stock = db.session.query(StockLevel).filter_by(product_id=product.id).first()
            if stock:
                analysis['alerts'].append(
                    f'  • {product.name}: متوفر {stock.quantity}, الحد الأدنى {product.min_stock_level}'
                )
    
    # 💡 الفرص - المنتجات الأكثر مبيعاً
    from models import SaleLine
    top_products = db.session.query(
        Product.name,
        func.sum(SaleLine.quantity).label('total_sold')
    ).join(SaleLine, SaleLine.product_id == Product.id).group_by(
        Product.id
    ).order_by(desc('total_sold')).limit(3).all()
    
    if top_products:
        analysis['opportunities'].append('أكثر 3 منتجات مبيعاً:')
        for product_name, qty in top_products:
            analysis['opportunities'].append(f'  • {product_name}: {qty} قطعة')
        analysis['recommendations'].append('تأكد من توفر هذه المنتجات دائماً!')
    
    return analysis


def analyze_sales_performance(period_days: int = 30) -> Dict[str, Any]:
    """تحليل أداء المبيعات - يحكم على الأداء ويقترح"""
    from models import Invoice, SaleLine
    
    start_date = datetime.now(timezone.utc) - timedelta(days=period_days)
    
    # الأرقام
    current_sales = db.session.query(func.sum(Invoice.total_amount)).filter(
        Invoice.created_at >= start_date
    ).scalar() or 0
    
    invoices_count = db.session.query(func.count(Invoice.id)).filter(
        Invoice.created_at >= start_date
    ).scalar() or 0
    
    # المقارنة مع الفترة السابقة
    prev_start = start_date - timedelta(days=period_days)
    prev_sales = db.session.query(func.sum(Invoice.total_amount)).filter(
        Invoice.created_at >= prev_start,
        Invoice.created_at < start_date
    ).scalar() or 0
    
    # 🧮 الحساب والمقاضاة (الحكم)
    change_percent = 0
    if prev_sales > 0:
        change_percent = ((float(current_sales) - float(prev_sales)) / float(prev_sales)) * 100
    
    judgment = 'جيد'
    if change_percent > 20:
        judgment = '🎉 ممتاز جداً!'
    elif change_percent > 10:
        judgment = '✅ جيد جداً'
    elif change_percent > 0:
        judgment = '👍 جيد'
    elif change_percent > -10:
        judgment = '⚠️ انخفاض طفيف'
    else:
        judgment = '🚨 انخفاض خطير!'
    
    analysis = {
        'period': f'{period_days} يوم',
        'current_sales': float(current_sales),
        'previous_sales': float(prev_sales),
        'change_percent': round(change_percent, 2),
        'invoices_count': invoices_count,
        'avg_invoice': float(current_sales) / invoices_count if invoices_count > 0 else 0,
        'judgment': judgment,
        'insights': [],
        'recommendations': []
    }
    
    # 💡 الإدراك والاستنتاج
    if change_percent > 20:
        analysis['insights'].append('أداء رائع! استمر على هذا النهج')
        analysis['recommendations'].append('وثّق ما فعلته لتكرار النجاح')
    elif change_percent > 10:
        analysis['insights'].append('نمو جيد - على المسار الصحيح')
    elif change_percent < -10:
        analysis['insights'].append('انخفاض ملحوظ - يحتاج تدخل فوري!')
        analysis['recommendations'].extend([
            'راجع أسعارك - هل ارتفعت كثيراً؟',
            'تحقق من رضا الزبائن',
            'قارن مع المنافسين',
            'قدم عروض خاصة لتحفيز المبيعات'
        ])
    
    # متوسط الفاتورة
    avg = analysis['avg_invoice']
    if avg < 500:
        analysis['insights'].append('متوسط الفاتورة منخفض')
        analysis['recommendations'].append('حاول زيادة قيمة كل صفقة (upselling)')
    elif avg > 2000:
        analysis['insights'].append('متوسط فاتورة ممتاز!')
    
    return analysis


def analyze_business_risks() -> Dict[str, Any]:
    """تحليل المخاطر - يشعر بالخطر ويحذر"""
    from models import Customer, Invoice, Payment, Product, StockLevel
    
    risks = {
        'critical': [],
        'high': [],
        'medium': [],
        'overall_score': 10,  # من 10
        'status': '✅ آمن'
    }
    
    # 1️⃣ خطر السيولة
    total_ar = db.session.query(func.sum(Invoice.total_amount)).scalar() or 0
    total_payments = db.session.query(func.sum(Payment.total_amount)).filter(
        Payment.direction == 'IN'
    ).scalar() or 0
    
    ar_balance = float(total_ar) - float(total_payments)
    
    if ar_balance > 50000:
        risks['critical'].append('ذمم مدينة خطيرة جداً: {:.2f}₪'.format(ar_balance))
        risks['overall_score'] -= 3
    elif ar_balance > 20000:
        risks['high'].append('ذمم مدينة مرتفعة: {:.2f}₪'.format(ar_balance))
        risks['overall_score'] -= 2
    
    # 2️⃣ خطر المخزون
    low_stock_count = db.session.query(func.count(Product.id)).join(StockLevel).filter(
        StockLevel.quantity < Product.min_stock_level
    ).scalar() or 0
    
    if low_stock_count > 10:
        risks['high'].append(f'{low_stock_count} منتج تحت الحد الأدنى')
        risks['overall_score'] -= 2
    elif low_stock_count > 5:
        risks['medium'].append(f'{low_stock_count} منتج تحت الحد الأدنى')
        risks['overall_score'] -= 1
    
    # 3️⃣ خطر الزبائن غير النشطين
    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
    inactive_customers = db.session.query(func.count(Customer.id)).filter(
        ~Customer.id.in_(
            db.session.query(Invoice.customer_id).filter(
                Invoice.created_at >= ninety_days_ago
            )
        )
    ).scalar() or 0
    
    if inactive_customers > 50:
        risks['medium'].append(f'{inactive_customers} زبون غير نشط (90+ يوم)')
        risks['overall_score'] -= 1
    
    # الحكم النهائي
    if risks['overall_score'] <= 5:
        risks['status'] = '🚨 خطر عالٍ'
    elif risks['overall_score'] <= 7:
        risks['status'] = '⚠️ انتباه'
    else:
        risks['status'] = '✅ آمن'
    
    return risks


def smart_recommendations(context: str = 'general') -> List[str]:
    """توصيات ذكية بناءً على التحليل الفعلي"""
    from models import Customer, Product, Invoice, ServiceRequest
    
    recommendations = []
    
    # تحليل الزبائن
    total_customers = Customer.query.count()
    if total_customers < 10:
        recommendations.append('🎯 عدد الزبائن قليل - ركز على التسويق واكتساب زبائن جدد')
    
    # تحليل المخزون
    total_products = Product.query.count()
    if total_products < 20:
        recommendations.append('📦 المخزون محدود - وسّع تشكيلة المنتجات')
    
    # تحليل الصيانة
    pending_services = ServiceRequest.query.filter_by(status='PENDING').count()
    if pending_services > 10:
        recommendations.append(f'🔧 {pending_services} طلب صيانة معلق - خطط للتنفيذ')
    
    # تحليل الفواتير
    today = datetime.now(timezone.utc).date()
    today_invoices = db.session.query(func.count(Invoice.id)).filter(
        func.date(Invoice.created_at) == today
    ).scalar() or 0
    
    if today_invoices == 0:
        recommendations.append('📊 لا توجد مبيعات اليوم - حاول إغلاق صفقة!')
    elif today_invoices > 5:
        recommendations.append('🎉 يوم مبيعات ممتاز!')
    
    return recommendations


def feel_and_respond(message: str, data: Dict[str, Any]) -> str:
    """يشعر ويستجيب - ردود تفاعلية وليست قوالب"""
    message_lower = message.lower()
    
    # الشعور بالقلق
    if any(word in message_lower for word in ['مشكلة', 'خطأ', 'لا يعمل', 'problem', 'error']):
        empathy = "😟 أشعر بقلقك... دعني أساعدك."
    # الشعور بالفرح
    elif any(word in message_lower for word in ['ممتاز', 'رائع', 'excellent', 'great']):
        empathy = "😊 أشاركك الفرح! هذا رائع!"
    # الشعور بالفضول
    elif any(word in message_lower for word in ['كيف', 'لماذا', 'why', 'how']):
        empathy = "🤔 سؤال ذكي! دعني أشرح بالتفصيل..."
    # الشعور بالاستعجال
    elif any(word in message_lower for word in ['سريع', 'عاجل', 'الآن', 'urgent', 'now']):
        empathy = "⚡ فهمت - حالة عاجلة! إليك الحل السريع:"
    else:
        empathy = "💡"
    
    return empathy


def think_and_deduce(query: str, db_data: Dict[str, Any]) -> Dict[str, Any]:
    """يفكر ويستنتج - استنتاجات ذكية"""
    from models import Customer, Invoice, Payment
    
    deductions = {
        'understanding': '',
        'analysis': [],
        'conclusions': [],
        'next_steps': []
    }
    
    query_lower = query.lower()
    
    # فهم النية
    if 'زبائن' in query_lower or 'customer' in query_lower:
        deductions['understanding'] = 'أفهم أنك مهتم بالزبائن...'
        
        # الاستنتاج
        total_customers = Customer.query.count()
        active_customers = db.session.query(func.count(func.distinct(Invoice.customer_id))).filter(
            Invoice.created_at >= datetime.now(timezone.utc) - timedelta(days=30)
        ).scalar() or 0
        
        if active_customers < total_customers * 0.3:
            deductions['analysis'].append(f'فقط {active_customers} من {total_customers} زبون نشط (30 يوم)')
            deductions['conclusions'].append('🚨 معدل النشاط منخفض - معظم الزبائن غير نشطين!')
            deductions['next_steps'].extend([
                'اتصل بالزبائن غير النشطين',
                'قدم عروض لإعادة التفاعل',
                'راجع أسباب عدم النشاط'
            ])
        else:
            deductions['conclusions'].append('✅ معدل نشاط جيد')
    
    return deductions


def proactive_alerts() -> List[str]:
    """تنبيهات استباقية - يدرك قبل أن تسأل"""
    from models import Invoice, Product, StockLevel, ServiceRequest
    
    alerts = []
    
    # 1. فواتير متأخرة
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    overdue = db.session.query(func.count(Invoice.id)).filter(
        Invoice.created_at < thirty_days_ago,
        Invoice.payment_status != 'COMPLETED'
    ).scalar() or 0
    
    if overdue > 0:
        alerts.append(f'🚨 {overdue} فاتورة متأخرة (+30 يوم) - حصّل الآن!')
    
    # 2. مخزون ناقص
    low_stock = db.session.query(func.count(Product.id)).join(StockLevel).filter(
        StockLevel.quantity < Product.min_stock_level
    ).scalar() or 0
    
    if low_stock > 0:
        alerts.append(f'⚠️ {low_stock} منتج تحت الحد الأدنى - اطلب الآن!')
    
    # 3. صيانة معلقة
    pending = ServiceRequest.query.filter_by(status='PENDING').count()
    if pending > 5:
        alerts.append(f'🔧 {pending} طلب صيانة معلق - خطط للتنفيذ!')
    
    return alerts


def calculate_and_judge(metric: str, value: float, context: Dict = None) -> Dict[str, Any]:
    """يحسب ويحكم - تقييم ذكي للأرقام"""
    
    judgments = {
        'profit_margin': {
            'excellent': (20, '🎉 ممتاز جداً! هامش ربح استثنائي'),
            'good': (15, '✅ جيد جداً - فوق المتوسط'),
            'average': (10, '👍 متوسط - مقبول'),
            'poor': (5, '⚠️ ضعيف - يحتاج تحسين'),
            'critical': (0, '🚨 حرج - راجع استراتيجيتك فوراً!')
        },
        'customer_retention': {
            'excellent': (90, '🎉 ممتاز! زبائن مخلصون'),
            'good': (80, '✅ جيد جداً'),
            'average': (70, '👍 متوسط'),
            'poor': (60, '⚠️ منخفض - تحسين مطلوب'),
            'critical': (0, '🚨 خطير - تخسر زبائن!')
        },
        'ar_ratio': {
            'excellent': (10, '✅ ممتاز - تحصيل سريع'),
            'good': (20, '👍 جيد'),
            'average': (30, '⚠️ متوسط'),
            'poor': (40, '🚨 بطيء - حسّن التحصيل'),
            'critical': (50, '🚨🚨 خطير جداً!')
        }
    }
    
    if metric not in judgments:
        return {'value': value, 'judgment': 'غير معروف'}
    
    thresholds = judgments[metric]
    judgment_text = thresholds['critical'][1]
    
    for level, (threshold, text) in thresholds.items():
        if value >= threshold:
            judgment_text = text
            break
    
    return {
        'metric': metric,
        'value': value,
        'judgment': judgment_text,
        'level': 'critical' if value < thresholds['poor'][0] else 'good'
    }


def context_aware_response(query: str, user_role: str = 'User') -> str:
    """ردود واعية بالسياق - يفهم من أنت وماذا تحتاج"""
    
    query_lower = query.lower()
    
    # فهم السياق حسب الدور
    from permissions_config.role_policy import canonical_role_name_str

    role_l = canonical_role_name_str(str(user_role or ""))
    if role_l in ("owner", "developer", "super_admin"):
        # المالك يحتاج تحليل عميق
        if 'إحصائيات' in query_lower or 'stats' in query_lower:
            return 'owner_deep_analysis'
    elif user_role in ['Manager', 'manager', 'مدير']:
        # المدير يحتاج insights عملية
        if 'إحصائيات' in query_lower:
            return 'manager_operational'
    else:
        # المستخدم العادي يحتاج معلومات بسيطة
        return 'user_simple'
    
    return 'general'


def innovate_solution(problem: str) -> Dict[str, Any]:
    """يبتكر حلول - ليس مجرد إجابات جاهزة"""
    
    problem_lower = problem.lower()
    
    innovations = {
        'problem': problem,
        'creative_solutions': [],
        'out_of_box_ideas': [],
        'implementation': []
    }
    
    # مشكلة: زبائن لا يدفعون
    if 'لا يدفع' in problem_lower or 'متأخر' in problem_lower:
        innovations['creative_solutions'] = [
            '💡 برنامج خصم للدفع المبكر (5% خصم خلال 7 أيام)',
            '💡 نظام نقاط ولاء يزيد مع الدفع بالوقت',
            '💡 تذكير ودي عبر WhatsApp قبل الاستحقاق بـ 3 أيام',
        ]
        innovations['out_of_box_ideas'] = [
            '🎯 اجعل الدفع المبكر يتيح ميزة (أولوية في المواعيد)',
            '🎯 قدم "بطاقة زبون VIP" للدفع المنتظم',
        ]
    
    # مشكلة: مبيعات منخفضة
    elif 'مبيعات منخفضة' in problem_lower or 'مبيعات قليلة' in problem_lower:
        innovations['creative_solutions'] = [
            '💡 عروض "اشتر 2 احصل على الثالث بنصف السعر"',
            '💡 خصم 15% لفترة محدودة (إلحاق بالشراء)',
            '💡 باقات صيانة شاملة (سنوية)',
        ]
        innovations['out_of_box_ideas'] = [
            '🎯 تعاون مع شركات سيارات للصيانة الدورية',
            '🎯 خدمة توصيل واستلام السيارة من المنزل',
            '🎯 "يوم الزبون" - خصومات خاصة',
        ]
    
    return innovations


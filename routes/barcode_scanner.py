

import qrcode
import io
import base64
import uuid
from flask import Blueprint, render_template, request, jsonify, send_file, flash, redirect, url_for, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, func
from extensions import db
from models import Product, ProductCategory, Supplier, Warehouse, StockLevel, ProductCondition
import utils
from utils import _get_or_404, permission_required
from permissions_config.enums import SystemPermissions
from barcodes import normalize_barcode, generate_barcode_image
from datetime import datetime, timezone
import json

barcode_scanner_bp = Blueprint("barcode_scanner", __name__, url_prefix="/barcode")


def generate_unique_barcode():
    import random
    while True:
        # توليد باركود من 13 رقم (EAN-13 format)
        barcode = str(random.randint(1000000000000, 9999999999999))
        # التأكد من أن الباركود فريد
        existing = Product.query.filter_by(barcode=barcode).first()
        if not existing:
            return barcode


def auto_assign_barcodes():
    try:
        products_without_barcode = Product.query.filter(
            or_(
                Product.barcode.is_(None),
                Product.barcode == "",
                Product.barcode == "None"
            )
        ).filter_by(is_active=True).all()
        
        assigned_count = 0
        for product in products_without_barcode:
            try:
                product.barcode = generate_unique_barcode()
                db.session.add(product)
                assigned_count += 1
            except Exception as e:
                current_app.logger.error(f"Error assigning barcode to product {product.id}: {e}")
                continue
        
        db.session.commit()
        return assigned_count
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in auto_assign_barcodes: {e}")
        return 0


@barcode_scanner_bp.route("/", methods=["GET"], endpoint="index")
@login_required
@permission_required(SystemPermissions.USE_SCANNER)
def scanner_index():
    """صفحة ماسح الباركود الرئيسية"""
    return render_template("barcode_scanner/index.html")


@barcode_scanner_bp.route("/scan", methods=["POST"], endpoint="scan_barcode")
@login_required
@permission_required(SystemPermissions.USE_SCANNER)
def scan_barcode():
    """مسح الباركود والبحث عن المنتج"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        barcode_text = data.get("barcode", "").strip()
        
        if not barcode_text:
            return jsonify({"error": "باركود فارغ"}), 400
        
        # تطبيع الباركود
        normalized_barcode = normalize_barcode(barcode_text)
        
        # البحث عن المنتج
        product = Product.query.filter(
            or_(
                Product.barcode == normalized_barcode,
                Product.barcode == barcode_text,
                Product.sku == barcode_text,
                Product.part_number == barcode_text
            )
        ).first()
        
        if not product:
            return jsonify({
                "found": False,
                "message": "المنتج غير موجود",
                "barcode": barcode_text
            }), 404
        
        # الحصول على معلومات المخزون
        stock_levels = StockLevel.query.filter_by(product_id=product.id).all()
        stock_info = []
        total_stock = 0
        
        for stock in stock_levels:
            stock_info.append({
                "warehouse_id": stock.warehouse_id,
                "warehouse_name": stock.warehouse.name if stock.warehouse else "غير محدد",
                "quantity": stock.quantity,
                "reserved": stock.reserved_quantity,
                "available": stock.quantity - stock.reserved_quantity
            })
            total_stock += stock.quantity
        
        # معلومات المنتج
        product_info = {
            "id": product.id,
            "name": product.name,
            "sku": product.sku,
            "barcode": product.barcode,
            "part_number": product.part_number,
            "brand": product.brand,
            "category": product.category_name,
            "supplier": product.supplier.name if product.supplier else None,
            "purchase_price": float(product.purchase_price or 0),
            "selling_price": float(product.selling_price or 0),
            "image": product.image,
            "description": product.description,
            "is_active": product.is_active,
            "stock_info": stock_info,
            "total_stock": total_stock
        }
        
        return jsonify({
            "found": True,
            "product": product_info,
            "barcode": barcode_text
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/generate", methods=["POST"], endpoint="generate_barcode")
@login_required
def generate_barcode_for_product():
    """توليد باركود لمنتج"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        product_id = data.get("product_id")
        barcode_type = data.get("type", "CODE128")  # CODE128, QR, EAN13
        
        if not product_id:
            return jsonify({"error": "معرف المنتج مطلوب"}), 400
        
        product = _get_or_404(Product, product_id)
        
        # توليد الباركود
        if barcode_type == "QR":
            # QR Code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(f"PRODUCT:{product.id}:{product.sku}")
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            # تحويل إلى base64
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            img_data = base64.b64encode(buffer.getvalue()).decode()
            
            return jsonify({
                "success": True,
                "barcode_type": "QR",
                "barcode_data": f"PRODUCT:{product.id}:{product.sku}",
                "image": f"data:image/png;base64,{img_data}",
                "product": {
                    "id": product.id,
                    "name": product.name,
                    "sku": product.sku
                }
            })
        
        else:
            # باركود خطي
            barcode_data = product.barcode or product.sku or str(product.id)
            
            # استخدام مكتبة الباركود الموجودة
            try:
                barcode_image_data = generate_barcode_image(barcode_data)
                
                if barcode_image_data:
                    return jsonify({
                        "success": True,
                        "barcode_type": barcode_type,
                        "barcode_data": barcode_data,
                        "image": barcode_image_data,
                        "product": {
                            "id": product.id,
                            "name": product.name,
                            "sku": product.sku,
                            "barcode": product.barcode
                        }
                    })
                else:
                    # استخدام QR Code كبديل
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(barcode_data)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    
                    # تحويل إلى base64
                    buffer = io.BytesIO()
                    img.save(buffer, format='PNG')
                    buffer.seek(0)
                    img_data = base64.b64encode(buffer.getvalue()).decode()
                    
                    return jsonify({
                        "success": True,
                        "barcode_type": "QR",
                        "barcode_data": barcode_data,
                        "image": f"data:image/png;base64,{img_data}",
                        "product": {
                            "id": product.id,
                            "name": product.name,
                            "sku": product.sku,
                            "barcode": product.barcode
                        }
                    })
                
            except Exception as e:
                current_app.logger.exception('API error')
                return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/print/<int:product_id>", methods=["GET"], endpoint="print_barcode")
@login_required
def print_barcode(product_id):
    """طباعة باركود منتج"""
    try:
        product = _get_or_404(Product, product_id)
        barcode_type = request.args.get("type", "CODE128")
        quantity = int(request.args.get("quantity", 1))
        
        if quantity > 100:
            quantity = 100  # حد أقصى للطباعة
        
        # توليد الباركود
        barcode_data = product.barcode or product.sku or str(product.id)
        
        if barcode_type == "QR":
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=8,
                border=2,
            )
            qr.add_data(f"PRODUCT:{product.id}:{product.sku}")
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
        else:
            # استخدام QR Code كبديل للباركود العادي
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=8,
                border=2,
            )
            qr.add_data(barcode_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
        
        # إرسال الصورة للطباعة
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype='image/png',
            as_attachment=True,
            download_name=f"barcode_{product.sku}_{quantity}.png"
        )
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/bulk-generate", methods=["POST"], endpoint="bulk_generate")
@login_required
def bulk_generate_barcodes():
    """توليد باركودات متعددة"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        product_ids = data.get("product_ids", [])
        barcode_type = data.get("type", "CODE128")
        
        if not product_ids:
            return jsonify({"error": "لا توجد منتجات محددة"}), 400
        
        if len(product_ids) > 50:
            return jsonify({"error": "لا يمكن توليد أكثر من 50 باركود في المرة الواحدة"}), 400
        
        results = []
        
        for product_id in product_ids:
            try:
                product = db.session.get(Product, product_id)
                if not product:
                    continue
                
                barcode_data = product.barcode or product.sku or str(product.id)
                
                if barcode_type == "QR":
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=6,
                        border=2,
                    )
                    qr.add_data(f"PRODUCT:{product.id}:{product.sku}")
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                else:
                    # استخدام QR Code كبديل للباركود العادي
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=6,
                        border=2,
                    )
                    qr.add_data(barcode_data)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                
                # تحويل إلى base64
                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                buffer.seek(0)
                img_data = base64.b64encode(buffer.getvalue()).decode()
                
                results.append({
                    "product_id": product.id,
                    "product_name": product.name,
                    "sku": product.sku,
                    "barcode_data": barcode_data,
                    "image": f"data:image/png;base64,{img_data}"
                })
                
            except Exception as e:
                continue
        
        return jsonify({
            "success": True,
            "generated_count": len(results),
            "barcodes": results
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/inventory/update", methods=["POST"], endpoint="inventory_update")
@login_required
def inventory_update_by_barcode():
    """تحديث المخزون باستخدام الباركود مع دعم الحقول الديناميكية"""
    import logging
    
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        logging.info(f"📦 [Inventory Update] البيانات المستلمة: {dict(data)}")
        
        barcode = data.get("barcode", "").strip()
        warehouse_id = data.get("warehouse_id")
        quantity_change = int(data.get("quantity_change", 0))
        operation = data.get("operation", "adjust")  # adjust, add, subtract
        
        # الحقول الديناميكية
        partner_id = data.get("partner_id")
        supplier_id = data.get("supplier_id")
        
        if not barcode or not warehouse_id:
            logging.error(f"❌ [Inventory Update] بيانات ناقصة: barcode={barcode}, warehouse_id={warehouse_id}")
            return jsonify({"error": "الباركود ومعرف المستودع مطلوبان"}), 400
        
        # البحث عن المنتج
        product = Product.query.filter(
            or_(
                Product.barcode == barcode,
                Product.sku == barcode,
                Product.part_number == barcode
            )
        ).first()
        
        if not product:
            logging.error(f"❌ [Inventory Update] المنتج غير موجود: {barcode}")
            return jsonify({"error": "المنتج غير موجود"}), 404
        
        # البحث عن المستودع
        warehouse = _get_or_404(Warehouse, warehouse_id)
        warehouse_type = getattr(warehouse.warehouse_type, "value", warehouse.warehouse_type)
        logging.info(f"🏭 [Inventory Update] نوع المستودع: {warehouse_type}")
        
        # ========== Validation حسب نوع المستودع ==========
        if warehouse_type == 'PARTNER':
            if not partner_id:
                logging.error(f"❌ [Inventory Update] مستودع PARTNER يتطلب partner_id")
                return jsonify({"error": "⚠️ مستودع شريك: يجب تحديد الشريك!"}), 400
            supplier_id = None  # مستودعات PARTNER لا تستخدم supplier_id
            logging.info(f"✅ [Inventory Update] مستودع PARTNER مع partner_id={partner_id}")
        elif warehouse_type == 'EXCHANGE':
            if not supplier_id:
                logging.error(f"❌ [Inventory Update] مستودع EXCHANGE يتطلب supplier_id")
                return jsonify({"error": "⚠️ مستودع تبادل: يجب تحديد المورد/التاجر!"}), 400
            partner_id = None  # مستودعات EXCHANGE لا تستخدم partner_id
            logging.info(f"✅ [Inventory Update] مستودع EXCHANGE مع supplier_id={supplier_id}")
        else:
            # MAIN, ONLINE, INVENTORY - لا يتطلب شريك أو مورد
            partner_id = None
            supplier_id = None
            logging.info(f"ℹ️ [Inventory Update] مستودع {warehouse_type} - لا يتطلب شريك/مورد")
        
        # الحصول على مستوى المخزون الحالي
        stock_level = StockLevel.query.filter_by(
            product_id=product.id,
            warehouse_id=warehouse_id
        ).first()
        
        if not stock_level:
            # إنشاء مستوى مخزون جديد
            stock_level = StockLevel(
                product_id=product.id,
                warehouse_id=warehouse_id,
                quantity=0,
                reserved_quantity=0
            )
            db.session.add(stock_level)
            logging.info(f"✅ [Inventory Update] إنشاء مخزون جديد للمنتج {product.id}")
        
        current_qty = int(stock_level.quantity or 0)
        reserved_qty = int(getattr(stock_level, "reserved_quantity", 0) or 0)
        available_qty = current_qty - reserved_qty

        if operation in ("add", "subtract") and quantity_change <= 0:
            return jsonify({"error": "invalid_quantity", "message": "الكمية يجب أن تكون أكبر من صفر"}), 400

        if operation == "adjust" and quantity_change < 0:
            return jsonify({"error": "invalid_quantity", "message": "لا يمكن ضبط كمية سالبة"}), 400

        # التحقق من الكمية المتاحة قبل الطرح (مع مراعاة المحجوز)
        if operation == "subtract" and quantity_change > available_qty:
            logging.error(f"❌ [Inventory Update] كمية غير كافية: المطلوب={quantity_change}, المتاح={available_qty}, المحجوز={reserved_qty}")
            return jsonify({
                "error": "insufficient_stock",
                "message": f"الكمية المطلوبة ({quantity_change}) أكبر من المتاح ({available_qty})",
                "available": available_qty,
                "reserved": reserved_qty,
            }), 400

        if operation == "adjust" and quantity_change < reserved_qty:
            return jsonify({
                "error": "quantity_below_reserved",
                "message": f"لا يمكن ضبط الكمية إلى ({quantity_change}) لأنها أقل من المحجوز ({reserved_qty})",
                "reserved": reserved_qty,
            }), 400
        
        # تحديث الكمية
        if operation == "add":
            stock_level.quantity += quantity_change
            logging.info(f"➕ [Inventory Update] إضافة {quantity_change} للمخزون")
        elif operation == "subtract":
            stock_level.quantity -= quantity_change
            logging.info(f"➖ [Inventory Update] طرح {quantity_change} من المخزون")
        else:  # adjust
            stock_level.quantity = quantity_change
            logging.info(f"🔄 [Inventory Update] تعديل المخزون إلى {quantity_change}")
        
        db.session.add(stock_level)
        db.session.commit()
        
        logging.info(f"🎉 [Inventory Update] تم تحديث المخزون بنجاح: {stock_level.quantity}")
        
        return jsonify({
            "success": True,
            "message": "تم تحديث المخزون بنجاح",
            "product": {
                "id": product.id,
                "name": product.name,
                "sku": product.sku
            },
            "warehouse": {
                "id": warehouse.id,
                "name": warehouse.name,
                "type": warehouse_type
            },
            "new_quantity": stock_level.quantity,
            "operation": operation,
            "partner_id": partner_id,
            "supplier_id": supplier_id
        })
        
    except ValueError as ve:
        db.session.rollback()
        logging.error(f"❌ [Inventory Update] خطأ في القيم: {str(ve)}")
        return jsonify({"error": "خطأ في القيم المدخلة"}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"❌ [Inventory Update] خطأ غير متوقع: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/warehouses", methods=["GET"], endpoint="get_warehouses")
@login_required
def get_warehouses():
    """الحصول على جميع المستودعات"""
    try:
        warehouses = Warehouse.query.filter_by(is_active=True).all()
        return jsonify({
            "success": True,
            "warehouses": [
                {
                    "id": warehouse.id,
                    "name": warehouse.name,
                    "type": getattr(warehouse.warehouse_type, 'value', 'general') if hasattr(warehouse, 'warehouse_type') and warehouse.warehouse_type else "general",
                    "location": warehouse.location if hasattr(warehouse, 'location') else "",
                    "description": warehouse.description if hasattr(warehouse, 'description') else ""
                }
                for warehouse in warehouses
            ]
        })
    except Exception as e:
        
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/warehouse-fields", methods=["GET"], endpoint="get_warehouse_fields")
@login_required
def get_warehouse_fields():
    """الحصول على الحقول المطلوبة حسب نوع المستودع"""
    try:
        warehouse_id = request.args.get("warehouse_id", type=int)
        if not warehouse_id:
            return jsonify({"error": "معرف المستودع مطلوب"}), 400
        
        warehouse = db.get_or_404(Warehouse, warehouse_id)
        
        # تحديد الحقول المطلوبة حسب نوع المستودع
        # الحقول الأساسية ثابتة لجميع المستودعات، فقط نضيف حقول إضافية
        fields_config = {
            "MAIN": {
                "required_fields": ["name", "price", "quantity"],
                "recommended_fields": ["brand", "part_number", "commercial_name"],
                "optional_fields": ["origin_country", "unit", "warranty_period"],
                "default_values": {
                    "unit": "قطعة",
                    "warranty_period": 12
                },
                "show_partner_fields": False,
                "show_exchange_fields": False,
                "show_online_fields": False
            },
            "PARTNER": {
                "required_fields": ["name", "price", "quantity"],
                "recommended_fields": ["brand", "part_number", "commercial_name"],
                "optional_fields": ["origin_country", "unit", "warranty_period"],
                "default_values": {
                    "unit": "قطعة",
                    "warranty_period": 12
                },
                "show_partner_fields": True,
                "show_exchange_fields": False,
                "show_online_fields": False,
                "partner_note": "سيتم إضافة حقول مساهمات الشركاء عند الحفظ"
            },
            "INVENTORY": {
                "required_fields": ["name", "price", "quantity"],
                "recommended_fields": ["brand", "part_number", "commercial_name"],
                "optional_fields": ["origin_country", "unit", "warranty_period"],
                "default_values": {
                    "unit": "قطعة",
                    "warranty_period": 12
                },
                "show_partner_fields": False,
                "show_exchange_fields": False,
                "show_online_fields": False
            },
            "EXCHANGE": {
                "required_fields": ["name", "quantity"],
                "recommended_fields": ["brand"],
                "optional_fields": ["price", "part_number", "commercial_name", "origin_country", "unit", "warranty_period"],
                "default_values": {
                    "unit": "قطعة",
                    "warranty_period": 6,
                    "price": 0
                },
                "show_partner_fields": False,
                "show_exchange_fields": True,
                "show_online_fields": False,
                "exchange_note": "سيتم إضافة معلومات التاجر/المورد عند الحفظ"
            },
            "ONLINE": {
                "required_fields": ["name", "price", "quantity"],
                "recommended_fields": ["brand", "commercial_name"],
                "optional_fields": ["part_number", "origin_country", "unit", "warranty_period"],
                "default_values": {
                    "unit": "قطعة",
                    "warranty_period": 12
                },
                "show_partner_fields": False,
                "show_exchange_fields": False,
                "show_online_fields": True,
                "online_note": "سيتم إضافة الصورة والاسم الإلكتروني عند الحفظ"
            }
        }
        
        warehouse_type = warehouse.warehouse_type.value if warehouse.warehouse_type else "MAIN"
        config = fields_config.get(warehouse_type, fields_config["MAIN"])
        
        return jsonify({
            "success": True,
            "warehouse_type": warehouse_type,
            "warehouse_name": warehouse.name,
            "required_fields": config["required_fields"],
            "recommended_fields": config.get("recommended_fields", []),
            "optional_fields": config["optional_fields"],
            "default_values": config["default_values"],
            "show_partner_fields": config.get("show_partner_fields", False),
            "show_exchange_fields": config.get("show_exchange_fields", False),
            "show_online_fields": config.get("show_online_fields", False),
            "note": config.get("partner_note") or config.get("exchange_note") or config.get("online_note", "")
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/check-product", methods=["GET"], endpoint="check_product_exists")
@login_required
def check_product_exists():
    """فحص وجود المنتج بالباركود وإرجاع بياناته"""
    try:
        barcode = request.args.get("barcode", "").strip()
        
        if not barcode:
            return jsonify({"error": "باركود مطلوب"}), 400
        
        # البحث عن المنتج
        product = Product.query.filter_by(barcode=barcode).first()
        
        if not product:
            return jsonify({
                "exists": False,
                "message": "المنتج غير موجود"
            })
        
        # الحصول على المخزون الحالي
        stock = StockLevel.query.filter_by(
            product_id=product.id,
            warehouse_id=request.args.get("warehouse_id", 1, type=int)
        ).first()
        
        current_quantity = stock.quantity if stock else 0
        
        return jsonify({
            "exists": True,
            "product": {
                "id": product.id,
                "name": product.name,
                "barcode": product.barcode,
                "part_number": product.part_number,
                "brand": product.brand,
                "commercial_name": product.commercial_name,
                "origin_country": product.origin_country,
                "unit": product.unit,
                "warranty_period": product.warranty_period,
                "price": float(product.price) if product.price else 0,
                "purchase_price": float(product.purchase_price) if product.purchase_price else 0,
                "selling_price": float(product.selling_price) if product.selling_price else 0,
                "condition": product.condition,
                "current_quantity": current_quantity
            }
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/search", methods=["GET"], endpoint="search_products")
@login_required
def search_products():
    """البحث عن المنتجات للباركود"""
    try:
        query = request.args.get("q", "").strip()
        limit = min(int(request.args.get("limit", 20)), 100)
        
        if len(query) < 2:
            return jsonify({"products": []})
        
        # البحث في المنتجات
        products = Product.query.filter(
            or_(
                Product.name.ilike(f"%{query}%"),
                Product.sku.ilike(f"%{query}%"),
                Product.barcode.ilike(f"%{query}%"),
                Product.part_number.ilike(f"%{query}%"),
                Product.brand.ilike(f"%{query}%")
            )
        ).filter_by(is_active=True).limit(limit).all()
        
        results = []
        for product in products:
            # الحصول على إجمالي المخزون
            total_stock = db.session.query(
                db.func.sum(StockLevel.quantity)
            ).filter_by(product_id=product.id).scalar() or 0
            
            results.append({
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "barcode": product.barcode,
                "part_number": product.part_number,
                "brand": product.brand,
                "category": product.category_name,
                "selling_price": float(product.selling_price or 0),
                "total_stock": total_stock,
                "has_barcode": bool(product.barcode)
            })
        
        return jsonify({"products": results})
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/auto-assign", methods=["POST"], endpoint="auto_assign_barcodes")
@login_required
@permission_required(SystemPermissions.MANAGE_WAREHOUSES)
def auto_assign_barcodes_route():
    """إعطاء باركود فريد لكل منتج بدون باركود"""
    try:
        assigned_count = auto_assign_barcodes()
        
        return jsonify({
            "success": True,
            "message": f"تم إعطاء باركود فريد لـ {assigned_count} منتج",
            "assigned_count": assigned_count
        })
        
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/stats", methods=["GET"], endpoint="barcode_stats")
@login_required
def barcode_stats():
    """إحصائيات الباركود"""
    try:
        # إجمالي المنتجات
        total_products = Product.query.filter_by(is_active=True).count()
        
        # المنتجات التي لها باركود
        products_with_barcode = Product.query.filter(
            and_(
                Product.is_active == True,
                Product.barcode.isnot(None),
                Product.barcode != ""
            )
        ).count()
        
        # المنتجات بدون باركود
        products_without_barcode = total_products - products_with_barcode
        
        # نسبة المنتجات مع باركود
        barcode_percentage = (products_with_barcode / total_products * 100) if total_products > 0 else 0
        
        # أنواع الباركود المستخدمة
        barcode_types = db.session.query(
            db.func.length(Product.barcode).label('barcode_length'),
            db.func.count(Product.id).label('count')
        ).filter(
            and_(
                Product.is_active == True,
                Product.barcode.isnot(None),
                Product.barcode != ""
            )
        ).group_by(
            db.func.length(Product.barcode)
        ).all()
        
        stats = {
            "success": True,
            "total_products": total_products,
            "products_with_barcode": products_with_barcode,
            "products_without_barcode": products_without_barcode,
            "barcode_percentage": round(barcode_percentage, 1),
            "barcode_lengths": [
                {"length": length, "count": count}
                for length, count in barcode_types
            ]
        }
        
        if request.is_json or request.args.get("format") == "json":
            return jsonify(stats)
        
        return render_template("barcode_scanner/stats.html", stats=stats)
        
    except Exception as e:
        
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/bulk-import", methods=["POST"], endpoint="bulk_import_products")
@login_required
@permission_required(SystemPermissions.MANAGE_WAREHOUSES)
def bulk_import_products():
    """استيراد جماعي للمنتجات بالباركود مع دعم الحقول الديناميكية"""
    import logging
    
    try:
        data = request.get_json()
        products_data = data.get("products", [])
        warehouse_id = data.get("warehouse_id", 1)
        existing_product_action = data.get("existing_product_action", "add_quantity")
        
        # الحقول الديناميكية
        partner_id = data.get("partner_id")
        supplier_id = data.get("supplier_id")
        
        logging.info(f"📦 [Bulk Import] بدء الاستيراد: {len(products_data)} منتج، مستودع: {warehouse_id}")
        logging.info(f"🏭 [Bulk Import] حقول ديناميكية: partner_id={partner_id}, supplier_id={supplier_id}")
        
        if not products_data:
            return jsonify({"error": "لا توجد بيانات منتجات"}), 400
        
        # التحقق من المستودع ونوعه
        warehouse = db.session.get(Warehouse, warehouse_id)
        if not warehouse:
            return jsonify({"error": "المستودع غير موجود"}), 404
            
        warehouse_type = getattr(warehouse.warehouse_type, "value", warehouse.warehouse_type)
        logging.info(f"🏭 [Bulk Import] نوع المستودع: {warehouse_type}")
        
        # ========== Validation حسب نوع المستودع ==========
        if warehouse_type == 'PARTNER':
            if not partner_id:
                logging.error(f"❌ [Bulk Import] مستودع PARTNER يتطلب partner_id")
                return jsonify({"error": "⚠️ مستودع شريك: يجب تحديد الشريك!"}), 400
            supplier_id = None  # مستودعات PARTNER لا تستخدم supplier_id
            logging.info(f"✅ [Bulk Import] مستودع PARTNER مع partner_id={partner_id}")
        elif warehouse_type == 'EXCHANGE':
            if not supplier_id:
                logging.error(f"❌ [Bulk Import] مستودع EXCHANGE يتطلب supplier_id")
                return jsonify({"error": "⚠️ مستودع تبادل: يجب تحديد المورد/التاجر!"}), 400
            partner_id = None  # مستودعات EXCHANGE لا تستخدم partner_id
            logging.info(f"✅ [Bulk Import] مستودع EXCHANGE مع supplier_id={supplier_id}")
        else:
            # MAIN, ONLINE, INVENTORY - لا يتطلب شريك أو مورد
            partner_id = None
            supplier_id = None
            logging.info(f"ℹ️ [Bulk Import] مستودع {warehouse_type} - لا يتطلب شريك/مورد")
        
        imported_count = 0
        updated_count = 0
        errors = []
        
        for i, product_data in enumerate(products_data):
            try:
                barcode = product_data.get("barcode", "").strip()
                name = product_data.get("name", "").strip()
                part_number = product_data.get("part_number", "").strip()
                brand = product_data.get("brand", "").strip()
                commercial_name = product_data.get("commercial_name", "").strip()
                origin_country = product_data.get("origin_country", "").strip()
                unit = product_data.get("unit", "").strip()
                warranty_period = int(product_data.get("warranty_period", 12))
                price = float(product_data.get("price", 0))
                quantity = int(product_data.get("quantity", 0))
                
                if not barcode or not name:
                    errors.append(f"باركود أو اسم مفقود: {barcode}")
                    continue
                
                # البحث عن المنتج بالباركود
                existing_product = Product.query.filter_by(barcode=barcode, warehouse_id=warehouse_id).first()
                if not existing_product:
                    existing_product = Product.query.filter(
                        func.lower(Product.name) == name.lower(),
                        Product.warehouse_id == warehouse_id
                    ).first()
                    if existing_product and barcode:
                        if existing_product.barcode and existing_product.barcode != barcode:
                            errors.append(f"تعارض باركود للاسم {name}: {barcode}")
                            continue
                        if not existing_product.barcode:
                            other = (
                                db.session.query(Product.id)
                                .filter(
                                    Product.barcode == barcode,
                                    Product.warehouse_id == warehouse_id,
                                    Product.id != existing_product.id
                                )
                                .first()
                            )
                            if other:
                                errors.append(f"الباركود مستخدم بالفعل: {barcode}")
                                continue
                            existing_product.barcode = barcode
                
                if existing_product:
                    # تحديث المنتج الموجود (الحقول المحددة فقط)
                    update_fields = product_data.get("update_fields", {})
                    
                    if existing_product.part_number in (None, "") and part_number:
                        existing_product.part_number = part_number
                    if existing_product.brand in (None, "") and brand:
                        existing_product.brand = brand
                    if existing_product.commercial_name in (None, "") and commercial_name:
                        existing_product.commercial_name = commercial_name
                    if existing_product.origin_country in (None, "") and origin_country:
                        existing_product.origin_country = origin_country
                    if existing_product.unit in (None, "") and unit:
                        existing_product.unit = unit
                    if (existing_product.warranty_period in (None, 0)) and warranty_period > 0:
                        existing_product.warranty_period = warranty_period
                    if (existing_product.price in (None, 0)) and price > 0:
                        existing_product.price = price

                    if update_fields.get("name") and update_fields["name"] != existing_product.name:
                        existing_product.name = update_fields["name"]
                    if update_fields.get("part_number") is not None:
                        existing_product.part_number = update_fields["part_number"]
                    if update_fields.get("brand") is not None:
                        existing_product.brand = update_fields["brand"]
                    if update_fields.get("commercial_name") is not None:
                        existing_product.commercial_name = update_fields["commercial_name"]
                    if update_fields.get("origin_country") is not None:
                        existing_product.origin_country = update_fields["origin_country"]
                    if update_fields.get("unit") is not None:
                        existing_product.unit = update_fields["unit"]
                    if update_fields.get("warranty_period") is not None:
                        existing_product.warranty_period = update_fields["warranty_period"]
                    if update_fields.get("price") and update_fields["price"] > 0:
                        existing_product.price = update_fields["price"]
                    
                    existing_product.is_active = True
                    db.session.add(existing_product)
                    
                    # التعامل مع المخزون حسب نوع العملية المحدد
                    stock = StockLevel.query.filter_by(
                        product_id=existing_product.id,
                        warehouse_id=warehouse_id
                    ).first()
                    
                    if stock:
                        if existing_product_action == "add_quantity":
                            # إضافة الكمية الجديدة إلى الكمية الموجودة (تراكمي)
                            stock.quantity += quantity
                        elif existing_product_action == "replace_quantity":
                            # استبدال الكمية الموجودة بالكمية الجديدة
                            reserved_qty = int(getattr(stock, "reserved_quantity", 0) or 0)
                            if quantity < reserved_qty:
                                errors.append(f"لا يمكن استبدال الكمية إلى {quantity} لأن المحجوز {reserved_qty} للباركود {barcode}")
                                continue
                            stock.quantity = quantity
                        # إذا كان update_info_only فلا نغير الكمية
                        stock.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    else:
                        # إنشاء مخزون جديد
                        stock = StockLevel(
                            product_id=existing_product.id,
                            warehouse_id=warehouse_id,
                            quantity=quantity,
                            reserved_quantity=0
                        )
                    db.session.add(stock)
                    updated_count += 1
                    logging.info(f"✅ [Bulk Import] تحديث منتج: {name} ({barcode})")
                    
                else:
                    # إنشاء منتج جديد
                    new_product = Product(
                        name=name,
                        warehouse_id=warehouse_id,
                        barcode=barcode,
                        part_number=part_number if part_number else None,
                        brand=brand if brand else None,
                        commercial_name=commercial_name if commercial_name else None,
                        origin_country=origin_country if origin_country else None,
                        unit=unit if unit else 'قطعة',
                        warranty_period=warranty_period if warranty_period > 0 else None,
                        price=price,
                        purchase_price=price,  # نفس السعر كسعر شراء
                        selling_price=price,   # نفس السعر كسعر بيع
                        condition=ProductCondition.NEW.value,  # افتراضياً جديد
                        is_active=True
                    )
                    db.session.add(new_product)
                    db.session.flush()  # للحصول على ID
                    
                    # إضافة المخزون
                    stock = StockLevel(
                        product_id=new_product.id,
                        warehouse_id=warehouse_id,
                        quantity=quantity,
                        reserved_quantity=0
                    )
                    db.session.add(stock)
                    imported_count += 1
                    logging.info(f"✅ [Bulk Import] إنشاء منتج جديد: {name} ({barcode})")
                    
            except Exception as e:
                error_msg = f"خطأ في المنتج {barcode}"
                errors.append(error_msg)
                logging.error(f"❌ [Bulk Import] {error_msg}")
                continue
        
        db.session.commit()
        
        logging.info(f"🎉 [Bulk Import] اكتمل الاستيراد: {imported_count} جديد، {updated_count} محدث، {len(errors)} خطأ")
        
        return jsonify({
            "success": True,
            "imported_count": imported_count,
            "updated_count": updated_count,
            "total_processed": imported_count + updated_count,
            "errors": errors[:10],  # أول 10 أخطاء فقط
            "errors_count": len(errors),
            "warehouse_type": warehouse_type,
            "partner_id": partner_id,
            "supplier_id": supplier_id
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"❌ [Bulk Import] خطأ غير متوقع: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500


@barcode_scanner_bp.route("/bulk-scan", methods=["GET"], endpoint="bulk_scan_page")
@login_required
def bulk_scan_page():
    """صفحة المسح الجماعي"""
    warehouses = Warehouse.query.filter_by(is_active=True).all()
    return render_template("barcode_scanner/bulk_scan.html", warehouses=warehouses)


# ========== API Endpoints جديدة لدعم أنواع المستودعات ==========

@barcode_scanner_bp.route("/check-product", methods=["GET"], endpoint="check_product")
@login_required
def check_product():
    """فحص وجود المنتج والمخزون في مستودع معين"""
    import logging
    
    try:
        barcode = request.args.get("barcode", "").strip()
        warehouse_id = request.args.get("warehouse_id", type=int)
        
        if not barcode or not warehouse_id:
            return jsonify({"success": False, "error": "الباركود ومعرف المستودع مطلوبان"}), 400
        
        # البحث عن المنتج
        product = Product.query.filter(
            or_(
                Product.barcode == barcode,
                Product.sku == barcode,
                Product.part_number == barcode
            )
        ).first()
        
        if not product:
            return jsonify({
                "success": False,
                "exists": False,
                "error": "المنتج غير موجود"
            }), 404
        
        # البحث عن المخزون
        stock_level = StockLevel.query.filter_by(
            product_id=product.id,
            warehouse_id=warehouse_id
        ).first()
        
        current_quantity = stock_level.quantity if stock_level else 0
        
        return jsonify({
            "success": True,
            "exists": True,
            "product": {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "barcode": product.barcode,
                "part_number": product.part_number,
                "brand": product.brand,
                "price": float(product.price) if product.price else 0,
                "current_quantity": current_quantity
            }
        })
        
    except Exception as e:
        logging.error(f"[Check Product] خطأ: {str(e)}")
        current_app.logger.exception('API error')
        return jsonify({"success": False, "error": "تعذر تنفيذ العملية. حاول مرة أخرى."}), 500

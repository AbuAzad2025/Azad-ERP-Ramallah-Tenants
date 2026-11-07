# barcodes.py - Barcode Generation and Processing
# Location: /garage_manager/barcodes.py
# Description: Barcode generation, validation, and processing utilities

import re
import io
import base64
from typing import Optional, Dict, Any
try:
    import qrcode
    from PIL import Image
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

def compute_ean13_check_digit(code12: str) -> int:
    if not re.fullmatch(r"\d{12}", code12):
        raise ValueError("EAN-13 base must be exactly 12 digits")
    s = sum((3 if i % 2 else 1) * int(d) for i, d in enumerate(code12))
    return (10 - (s % 10)) % 10

def normalize_barcode(code: str) -> str | None:
    if not code:
        return None
    v = re.sub(r"\D+", "", str(code).strip())
    if not v:
        return None
    if len(v) == 12:
        return v + str(compute_ean13_check_digit(v))
    if len(v) == 13:
        return v
    return None

def is_valid_ean13(code: str) -> bool:
    v = re.sub(r"\D+", "", str(code).strip())
    if not re.fullmatch(r"\d{13}", v):
        return False
    return int(v[-1]) == compute_ean13_check_digit(v[:-1])

def validate_barcode(code: str) -> dict:
    raw = re.sub(r"\D+", "", str(code or "").strip())
    if not raw:
        return {"valid": False, "normalized": None, "suggested": None}
    if len(raw) == 12:
        normalized = raw + str(compute_ean13_check_digit(raw))
        return {"valid": True, "normalized": normalized, "suggested": None}
    if len(raw) == 13:
        ok = is_valid_ean13(raw)
        suggested = raw[:-1] + str(compute_ean13_check_digit(raw[:-1])) if not ok else None
        return {"valid": ok, "normalized": raw, "suggested": suggested}
    return {"valid": False, "normalized": None, "suggested": None}

def generate_qr_code(data: str, size: int = 200, border: int = 4) -> Optional[str]:
    """توليد QR Code كصورة base64"""
    if not QR_AVAILABLE:
        return None
    
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=border,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    except Exception:
        return None

def generate_barcode_image(code: str, width: int = 300, height: int = 100) -> Optional[str]:
    """توليد QR Code كصورة base64 (بديل الباركود — يتطلب python-barcode للباركود الحقيقي)"""
    if not QR_AVAILABLE:
        return None
    
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=3,
            border=1,
        )
        qr.add_data(code)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    except Exception:
        return None


def create_printable_label(product_name: str, barcode: str, price: Optional[float] = None, 
                          currency: str = "ILS") -> str:
    """إنشاء تسمية قابلة للطباعة"""
    qr_code = generate_qr_code(barcode)
    barcode_img = generate_barcode_image(barcode)
    
    price_text = f"السعر: {price} {currency}" if price else ""
    
    html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="utf-8">
        <title>تسمية المنتج</title>
        <style>
            @page {{
                size: 4in 2in;
                margin: 0.1in;
            }}
            body {{
                font-family: 'Cairo', Arial, sans-serif;
                margin: 0;
                padding: 5px;
                font-size: 12px;
                direction: rtl;
            }}
            .label {{
                width: 100%;
                height: 100%;
                border: 1px solid #000;
                padding: 5px;
                box-sizing: border-box;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }}
            .product-name {{
                font-weight: bold;
                text-align: center;
                margin-bottom: 5px;
                font-size: 14px;
            }}
            .barcode-section {{
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .barcode-img {{
                max-width: 150px;
                max-height: 50px;
            }}
            .qr-code {{
                max-width: 50px;
                max-height: 50px;
            }}
            .price {{
                text-align: center;
                font-weight: bold;
                margin-top: 5px;
            }}
        </style>
    </head>
    <body>
        <div class="label">
            <div class="product-name">{product_name}</div>
            <div class="barcode-section">
                <img src="{barcode_img}" alt="باركود" class="barcode-img">
                <img src="{qr_code}" alt="QR Code" class="qr-code">
            </div>
            <div class="price">{price_text}</div>
        </div>
    </body>
    </html>
    """
    
    return html

def print_label(product_name: str, barcode: str, price: float = None, 
                currency: str = "ILS") -> str:
    """طباعة تسمية المنتج"""
    label_html = create_printable_label(product_name, barcode, price, currency)
    
    print_script = """
    <script>
        window.onload = function() {
            window.print();
        }
    </script>
    """
    
    return label_html + print_script

"""
analytics_service.py
Customer matching engine + KPI calculations + aggregations.
Matching: exact email, exact phone, rapidfuzz name fallback.
Confidence scoring: high / medium / low.
"""
import re
import logging
from collections import defaultdict
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from database import InvoiceExtraction, ShopifyOrder, ProcessedRow, ProcessedFile, SyncLog
from services.sync_service import get_sync_status
from services.ocr_service import ocr_stats

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Normalisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def norm_email(email: Optional[str]) -> str:
    if not email:
        return ""
    return str(email).lower().strip()


def norm_phone(phone: Optional[str]) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    return digits[-10:] if len(digits) >= 10 else digits


# ─────────────────────────────────────────────────────────────────────────────
# Customer matching & segmentation
# ─────────────────────────────────────────────────────────────────────────────

def _build_fk_customers(db: Session) -> List[Dict]:
    """
    Build Flipkart customer profiles by merging:
      - ProcessedRow  → email, phone, product, size, colour (from warranty FORM — filled by customer)
      - InvoiceExtraction → product, city, state, order_id, invoice_date (from Gemini OCR)
    The warranty form's email/phone are authoritative since Flipkart invoices never expose them.
    """
    # Get all warranty rows (one per customer registration)
    warranty_rows = db.query(ProcessedRow).all()

    # Get all OCR extractions indexed by row_number
    ocr_rows = db.query(InvoiceExtraction).all()
    ocr_by_row: Dict[int, List] = defaultdict(list)
    for ocr in ocr_rows:
        ocr_by_row[ocr.row_number].append(ocr)

    customers = {}
    for wr in warranty_rows:
        # Use form email/phone as the primary identity key
        form_email = norm_email(wr.email)
        form_phone = norm_phone(wr.phone)
        key = form_email or form_phone or f"row_{wr.sheet_row_number}"

        # Pick the best OCR result for this row
        ocr_list = ocr_by_row.get(wr.sheet_row_number, [])
        best_ocr = ocr_list[0] if ocr_list else None

        # Merge: form data wins for contact info; OCR wins for invoice details
        city  = (best_ocr.billing_city  or best_ocr.shipping_city)  if best_ocr else None
        state = (best_ocr.billing_state or best_ocr.shipping_state) if best_ocr else None

        if key not in customers:
            customers[key] = {
                # Contact (from WARRANTY FORM — reliable)
                "email":         form_email or norm_email(best_ocr.email if best_ocr else None),
                "phone":         form_phone or norm_phone(best_ocr.phone if best_ocr else None),
                # Product info: prefer OCR (more detailed), fallback to form
                "customer_name": (best_ocr.customer_name if best_ocr else None) or wr.email,
                "product":       (best_ocr.product_title if best_ocr else None) or wr.warranty_product,
                "size":          (best_ocr.size          if best_ocr else None) or wr.warranty_size,
                "colour":        (best_ocr.colour        if best_ocr else None) or wr.warranty_colour,
                "brand":         wr.warranty_brand,
                # Location (OCR only — not on form)
                "city":          city,
                "state":         state,
                # Invoice details (OCR only)
                "invoice_date":  best_ocr.invoice_date if best_ocr else None,
                "order_id":      best_ocr.order_id     if best_ocr else None,
                "grand_total":   best_ocr.grand_total  if best_ocr else None,
                "platform":      best_ocr.platform     if best_ocr else "Flipkart",
                "file_ids":      [o.file_id for o in ocr_list],
            }
        else:
            # Additional OCR files for same customer — add file_ids
            customers[key]["file_ids"].extend([o.file_id for o in ocr_list])

    return list(customers.values())


def _build_d2c_customers(db: Session) -> List[Dict]:
    rows = db.query(ShopifyOrder).all()
    customers: Dict[str, Dict] = {}
    for row in rows:
        key_email = norm_email(row.email)
        key_phone = norm_phone(row.phone)
        key = key_email or key_phone or str(row.id)
        if key not in customers:
            customers[key] = {
                "email": key_email,
                "phone": key_phone,
                "customer_name": row.customer_name,
                "orders": [row.order_id],
                "total_spend": row.total or 0,
                "products": [row.product] if row.product else [],
                "city": row.city,
                "state": row.state,
                "first_order": row.created_at,
                "payment_method": row.payment_method,
            }
        else:
            customers[key]["orders"].append(row.order_id)
            customers[key]["total_spend"] = (customers[key]["total_spend"] or 0) + (row.total or 0)
            if row.product and row.product not in customers[key]["products"]:
                customers[key]["products"].append(row.product)

    return list(customers.values())


def _match_customers(fk_list: List[Dict], d2c_list: List[Dict]) -> Dict:
    """
    Match FK customers to D2C customers.
    Returns {converted, flipkart_only, d2c_only} lists with confidence scores.
    """
    # Build D2C lookup indexes
    d2c_by_email: Dict[str, Dict] = {c["email"]: c for c in d2c_list if c["email"]}
    d2c_by_phone: Dict[str, Dict] = {c["phone"]: c for c in d2c_list if c["phone"]}
    matched_d2c_keys = set()

    converted = []
    flipkart_only = []

    for fk in fk_list:
        match = None
        confidence = None

        # Exact email match (high)
        if fk["email"] and fk["email"] in d2c_by_email:
            match = d2c_by_email[fk["email"]]
            confidence = "high"

        # Exact phone match (high)
        elif fk["phone"] and fk["phone"] in d2c_by_phone:
            match = d2c_by_phone[fk["phone"]]
            confidence = "high"

        # rapidfuzz name match fallback (medium)
        elif fk.get("customer_name"):
            try:
                from rapidfuzz import fuzz
                for d2c in d2c_list:
                    if d2c.get("customer_name"):
                        score = fuzz.token_sort_ratio(
                            fk["customer_name"], d2c["customer_name"]
                        )
                        if score >= 88:
                            match = d2c
                            confidence = "medium"
                            break
            except ImportError:
                pass

        if match:
            d2c_key = match["email"] or match["phone"]
            matched_d2c_keys.add(d2c_key)
            converted.append({
                **fk,
                "d2c_orders": len(match["orders"]),
                "d2c_spend": match["total_spend"],
                "d2c_products": match["products"],
                "d2c_first_order": match["first_order"],
                "match_confidence": confidence,
            })
        else:
            flipkart_only.append(fk)

    # D2C only = those never matched
    d2c_only = [
        c for c in d2c_list
        if (c["email"] not in matched_d2c_keys and c["phone"] not in matched_d2c_keys)
    ]

    return {
        "converted": converted,
        "flipkart_only": flipkart_only,
        "d2c_only": d2c_only,
    }


# ─────────────────────────────────────────────────────────────────────────────
# KPI calculations
# ─────────────────────────────────────────────────────────────────────────────

def get_kpis(db: Session) -> Dict[str, Any]:
    fk_customers = _build_fk_customers(db)
    d2c_customers = _build_d2c_customers(db)
    segments = _match_customers(fk_customers, d2c_customers)

    total_revenue = db.query(func.sum(ShopifyOrder.total)).scalar() or 0
    order_count = db.query(func.count(ShopifyOrder.id)).scalar() or 0

    # Repeat customers: D2C customers with >1 order
    d2c_order_counts: Dict[str, int] = defaultdict(int)
    all_shopify = db.query(ShopifyOrder).all()
    for row in all_shopify:
        key = norm_email(row.email) or norm_phone(row.phone)
        if key:
            d2c_order_counts[key] += 1
    repeat_customers = sum(1 for v in d2c_order_counts.values() if v > 1)

    fk_count = len(fk_customers)
    converted_count = len(segments["converted"])
    conversion_rate = round((converted_count / fk_count * 100), 1) if fk_count else 0

    # Sync status
    sync_status = get_sync_status()

    # OCR status counts
    pending_ocr = db.query(ProcessedRow).filter(ProcessedRow.status == "pending").count()
    failed_ocr = db.query(ProcessedRow).filter(ProcessedRow.status == "failed").count()
    processed_today = (
        db.query(ProcessedRow)
        .filter(ProcessedRow.processed_at >= datetime.utcnow().replace(hour=0, minute=0, second=0))
        .count()
    )

    # Duplicates
    dup_count = db.query(InvoiceExtraction).filter(InvoiceExtraction.is_duplicate == True).count()

    last_sync = db.query(SyncLog).order_by(SyncLog.started_at.desc()).first()

    return {
        "flipkart_buyers": fk_count,
        "d2c_customers": len(d2c_customers),
        "converted_customers": converted_count,
        "only_flipkart": len(segments["flipkart_only"]),
        "only_d2c": len(segments["d2c_only"]),
        "conversion_rate": conversion_rate,
        "total_d2c_revenue": round(total_revenue, 2),
        "avg_order_value": round(total_revenue / order_count, 2) if order_count else 0,
        "repeat_customers": repeat_customers,
        # Sync & processing status
        "pending_ocr": pending_ocr,
        "failed_ocr": failed_ocr,
        "processed_today": processed_today,
        "duplicate_invoices": dup_count,
        "gemini_calls_today": ocr_stats["today_calls"],
        "last_sync_time": last_sync.completed_at.isoformat() if last_sync and last_sync.completed_at else None,
        "last_sync_duration": last_sync.duration_seconds if last_sync else None,
        "sync_running": sync_status.get("running", False),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Data for tables
# ─────────────────────────────────────────────────────────────────────────────

def get_converted_customers(db: Session) -> List[Dict]:
    fk = _build_fk_customers(db)
    d2c = _build_d2c_customers(db)
    return _match_customers(fk, d2c)["converted"]


def get_flipkart_only(db: Session) -> List[Dict]:
    fk = _build_fk_customers(db)
    d2c = _build_d2c_customers(db)
    return _match_customers(fk, d2c)["flipkart_only"]


def get_d2c_only(db: Session) -> List[Dict]:
    fk = _build_fk_customers(db)
    d2c = _build_d2c_customers(db)
    return _match_customers(fk, d2c)["d2c_only"]


def get_all_customers(db: Session) -> List[Dict]:
    fk = _build_fk_customers(db)
    d2c = _build_d2c_customers(db)
    segments = _match_customers(fk, d2c)

    all_customers = []
    for c in segments["converted"]:
        all_customers.append({**c, "source": "converted", "spend": c.get("d2c_spend", 0)})
    for c in segments["flipkart_only"]:
        all_customers.append({**c, "source": "flipkart", "spend": 0})
    for c in segments["d2c_only"]:
        all_customers.append({**c, "source": "d2c", "spend": c.get("total_spend", 0)})
    return all_customers


# ─────────────────────────────────────────────────────────────────────────────
# Chart data
# ─────────────────────────────────────────────────────────────────────────────

def get_product_analytics(db: Session) -> List[Dict]:
    rows = db.query(InvoiceExtraction.product_title, func.count().label("count")).group_by(
        InvoiceExtraction.product_title
    ).order_by(text("count DESC")).limit(10).all()
    return [{"product": r.product_title or "Unknown", "count": r.count} for r in rows]


def get_city_analytics(db: Session) -> List[Dict]:
    rows = (
        db.query(InvoiceExtraction.billing_city, func.count().label("count"))
        .filter(InvoiceExtraction.billing_city.isnot(None))
        .group_by(InvoiceExtraction.billing_city)
        .order_by(text("count DESC"))
        .limit(10)
        .all()
    )
    d2c_cities = (
        db.query(ShopifyOrder.city, func.count().label("count"))
        .filter(ShopifyOrder.city.isnot(None))
        .group_by(ShopifyOrder.city)
        .order_by(text("count DESC"))
        .limit(10)
        .all()
    )
    city_map: Dict[str, Dict] = {}
    for r in rows:
        city_map[r.billing_city] = {"city": r.billing_city, "flipkart": r.count, "d2c": 0}
    for r in d2c_cities:
        if r.city in city_map:
            city_map[r.city]["d2c"] = r.count
        else:
            city_map[r.city] = {"city": r.city, "flipkart": 0, "d2c": r.count}
    return sorted(city_map.values(), key=lambda x: x["flipkart"] + x["d2c"], reverse=True)[:10]


def get_revenue_by_month(db: Session) -> List[Dict]:
    orders = db.query(ShopifyOrder).all()
    monthly: Dict[str, float] = defaultdict(float)
    for o in orders:
        if o.created_at and o.total:
            try:
                # Parse ISO format dates (handles timezones via fromisoformat)
                date_str = str(o.created_at).strip()
                # Handle format like "2025-09-13 21:40:12 +0530"
                if ' +' in date_str or ' -' in date_str:
                    date_str = date_str.replace(' +', '+').replace(' -', '-')
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                month_key = dt.strftime("%Y-%m")
                monthly[month_key] += o.total
            except Exception as e:
                logger.debug(f"Failed to parse Shopify date '{o.created_at}': {e}")
                pass
    return [{"month": k, "revenue": round(v, 2)} for k, v in sorted(monthly.items())]


def get_registrations_by_month(db: Session) -> List[Dict]:
    rows = db.query(ProcessedRow).all()
    monthly: Dict[str, int] = defaultdict(int)
    for r in rows:
        if r.timestamp:
            try:
                # Parse ISO format dates (handles both with and without microseconds)
                date_str = str(r.timestamp).strip()
                # Handle format like "2025-07-23 20:28:13.573000"
                # Split by space to get just date + time (without timezone for warranty data)
                if ' ' in date_str:
                    date_str = date_str.split('+')[0].split('Z')[0].strip()
                
                dt = datetime.fromisoformat(date_str)
                monthly[dt.strftime("%Y-%m")] += 1
            except Exception as e:
                logger.debug(f"Failed to parse warranty timestamp '{r.timestamp}': {e}")
                pass
    return [{"month": k, "count": v} for k, v in sorted(monthly.items())]


def get_size_trends(db: Session) -> List[Dict]:
    rows = (
        db.query(InvoiceExtraction.size, func.count().label("count"))
        .filter(InvoiceExtraction.size.isnot(None))
        .group_by(InvoiceExtraction.size)
        .order_by(text("count DESC"))
        .all()
    )
    return [{"size": r.size, "count": r.count} for r in rows]


def get_colour_trends(db: Session) -> List[Dict]:
    rows = (
        db.query(InvoiceExtraction.colour, func.count().label("count"))
        .filter(InvoiceExtraction.colour.isnot(None))
        .group_by(InvoiceExtraction.colour)
        .order_by(text("count DESC"))
        .all()
    )
    return [{"colour": r.colour, "count": r.count} for r in rows]


def get_payment_methods(db: Session) -> List[Dict]:
    rows = (
        db.query(ShopifyOrder.payment_method, func.count().label("count"))
        .filter(ShopifyOrder.payment_method.isnot(None))
        .group_by(ShopifyOrder.payment_method)
        .order_by(text("count DESC"))
        .all()
    )
    return [{"method": r.payment_method, "count": r.count} for r in rows]


def get_customer_journey(db: Session, email: str) -> Dict:
    """
    Build a customer journey timeline for a converted customer.
    Journey includes:
    1. Flipkart purchases (from ProcessedRow.email → InvoiceExtraction.row_number)
    2. D2C orders (from ShopifyOrder.email)
    Sorted chronologically.
    """
    norm = norm_email(email)

    def _parse_date(value: Optional[str]):
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None

        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d %b %Y",
            "%d %B %Y",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(text[:len(fmt)], fmt)
            except ValueError:
                continue
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            # Convert to naive datetime (remove timezone info for consistent comparisons)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except Exception:
            return None

    def _invoice_score(inv: InvoiceExtraction) -> int:
        score = 0
        if inv.invoice_number:
            score += 30
        if inv.order_id:
            score += 25
        if inv.product_title:
            score += 15
        if inv.grand_total is not None:
            score += 20
        if inv.invoice_date:
            score += 10
        if inv.file_id:
            score += 5
        return score

    # ── Step 1: Get warranty rows (authoritative email source) ────────────
    warranty_rows = (
        db.query(ProcessedRow)
        .filter(ProcessedRow.email == norm)
        .all()
    )
    warranty_row_numbers = [r.sheet_row_number for r in warranty_rows]

    # ── Step 2: Get Flipkart invoices linked via row_number ──────────────
    fk_invoices = []
    if warranty_row_numbers:
        fk_invoices = (
            db.query(InvoiceExtraction)
            .filter(InvoiceExtraction.row_number.in_(warranty_row_numbers))
            .order_by(InvoiceExtraction.row_number.asc(), InvoiceExtraction.extracted_at.desc())
            .all()
        )

    # Keep only the best extraction per warranty row and skip blank noise rows.
    fk_best_by_row: Dict[int, InvoiceExtraction] = {}
    for inv in fk_invoices:
        if not any([
            inv.product_title,
            inv.invoice_number,
            inv.order_id,
            inv.grand_total is not None,
            inv.invoice_date,
        ]):
            continue

        current = fk_best_by_row.get(inv.row_number)
        if current is None or _invoice_score(inv) > _invoice_score(current):
            fk_best_by_row[inv.row_number] = inv

    # ── Step 3: Get D2C orders by email ──────────────────────────────────
    d2c_orders = (
        db.query(ShopifyOrder)
        .filter(ShopifyOrder.email == norm)
        .order_by(ShopifyOrder.created_at)
        .all()
    )

    # ── Build timeline ──────────────────────────────────────────────────────
    events = []
    
    # Track which warranty rows have Flipkart invoices to avoid duplicates
    warranty_rows_with_invoices = set(fk_best_by_row.keys())
    
    # Add warranty registration events ONLY if no associated Flipkart invoice
    if warranty_rows:
        for wr in warranty_rows:
            # Skip if this warranty row has a Flipkart invoice (will be shown as flipkart_purchase)
            if wr.sheet_row_number in warranty_rows_with_invoices:
                continue
            
            reg_date = _parse_date(wr.timestamp) if wr.timestamp else None
            events.append({
                "type": "warranty_registration",
                "date": wr.timestamp or "",
                "product": wr.warranty_product or "Warranty Registration",
                "amount": None,
                "platform": "Flipkart (Warranty)",
                "invoice_number": None,
            })
    
    # Add Flipkart purchases (from OCR of warranty invoice links)
    for inv in sorted(
        fk_best_by_row.values(),
        key=lambda item: (
            _parse_date(item.invoice_date) or datetime.max,
            item.row_number or 0,
        ),
    ):
        events.append({
            "type": "flipkart_purchase",
            "date": inv.invoice_date or "",
            "product": inv.product_title,
            "amount": inv.grand_total,
            "platform": "Flipkart",
            "invoice_number": inv.invoice_number,
        })
    
    # Add D2C orders
    for order in sorted(
        d2c_orders,
        key=lambda item: _parse_date(item.created_at) or datetime.max,
    ):
        events.append({
            "type": "d2c_order",
            "date": order.created_at or "",
            "product": order.product,
            "amount": order.total,
            "order_id": order.order_id,
            "platform": "D2C",
        })

    # Sort chronologically
    events.sort(
        key=lambda item: (
            _parse_date(item.get("date")) or datetime.max,
            0 if item.get("type") == "warranty_registration" else (1 if item.get("type") == "flipkart_purchase" else 2),
        )
    )
    
    return {
        "email": norm,
        "customer_name": warranty_rows[0].email if warranty_rows else email,
        "events": events,
        "flipkart_count": len(fk_best_by_row),
        "d2c_count": len(d2c_orders),
    }


def get_invoices_list(db: Session, page: int = 1, per_page: int = 50) -> Dict:
    offset = (page - 1) * per_page
    total = db.query(ProcessedFile).count()
    files = (
        db.query(ProcessedFile)
        .order_by(ProcessedFile.processed_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "files": [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "status": f.extraction_status,
                "processed_at": f.processed_at.isoformat() if f.processed_at else None,
                "row_number": f.row_number,
            }
            for f in files
        ],
    }

import re
import logging
from collections import defaultdict
from rapidfuzz import fuzz
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any

from sqlalchemy.orm import Session
from sqlalchemy import func, text
from database import InvoiceExtraction, ShopifyOrder, ProcessedRow, ProcessedFile, SyncLog
from config import ATTRIBUTION_DATE_BUFFER_DAYS
from services.sync_service import get_sync_status
from services.ocr_service import ocr_stats

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Normalisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def norm_email(email: Optional[str]) -> str:
    if not email:
        return ""
    # Trim spaces and lower
    # E.g. " Test@Gmail.com " -> "test@gmail.com"
    return str(email).lower().strip()

def validate_phone(phone: Optional[str]) -> str:
    """Strict Indian mobile validation. Exactly 10 digits, starts with 6/7/8/9."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) >= 10:
        last10 = digits[-10:]
        if last10[0] in "6789":
            return last10
    return ""

def norm_phone(phone: Optional[str]) -> str:
    return validate_phone(phone)

def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt in (
        "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
        "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y",
        "%Y/%m/%d", "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text[:len(fmt)], fmt)
        except ValueError:
            continue
    try:
        if ' ' in text and not 'T' in text and not '+' in text and not 'Z' in text:
            if '.' in text:
                return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
            else:
                return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Canonical Customer Resolution
# ─────────────────────────────────────────────────────────────────────────────

class IdentityGraph:
    def __init__(self):
        self.parent = {}
        self.profiles = {}

    def find(self, key: str) -> str:
        if key not in self.parent:
            self.parent[key] = key
            self.profiles[key] = self._empty_profile()
        if self.parent[key] != key:
            self.parent[key] = self.find(self.parent[key])
        return self.parent[key]

    def union(self, key1: str, key2: str):
        root1 = self.find(key1)
        root2 = self.find(key2)
        if root1 != root2:
            self.parent[root2] = root1
            self._merge_profiles(root1, root2)

    def _empty_profile(self) -> Dict:
        return {
            "canonical_email": "",
            "canonical_phone": "",
            "customer_name": {"value": "", "source": "", "confidence": 0.0},
            "city": {"value": "", "source": "", "confidence": 0.0},
            "state": {"value": "", "source": "", "confidence": 0.0},
            
            # Shopify Data
            "shopify_orders": set(),
            "shopify_total_spend": 0.0,
            "shopify_products": set(),
            "shopify_first_order": None,
            
            # Warranty & OCR Data
            "warranty_products": set(),
            "warranty_date": None,
            "warranty_brands": set(),
            
            "detected_source": "Unknown",
            "source_confidence": 0.0,
            "attribution_method": "fallback",
            "ocr_failed": True,
            "file_ids": set(),
        }

    def _merge_profiles(self, root1: str, root2: str):
        p1 = self.profiles[root1]
        p2 = self.profiles[root2]
        
        # Merge basic fields (highest confidence wins)
        for field in ["customer_name", "city", "state"]:
            if p2[field]["confidence"] > p1[field]["confidence"]:
                p1[field] = p2[field]
                
        # Merge Sets
        p1["shopify_orders"].update(p2["shopify_orders"])
        p1["shopify_products"].update(p2["shopify_products"])
        p1["warranty_products"].update(p2["warranty_products"])
        p1["warranty_brands"].update(p2["warranty_brands"])
        p1["file_ids"].update(p2["file_ids"])
        
        # Sum spend
        p1["shopify_total_spend"] += p2["shopify_total_spend"]
        
        # Min Date
        if p2["shopify_first_order"]:
            if not p1["shopify_first_order"] or _parse_date(p2["shopify_first_order"]) < _parse_date(p1["shopify_first_order"]):
                p1["shopify_first_order"] = p2["shopify_first_order"]
                
        if p2["warranty_date"]:
            if not p1["warranty_date"] or _parse_date(p2["warranty_date"]) < _parse_date(p1["warranty_date"]):
                p1["warranty_date"] = p2["warranty_date"]
                
        # Source
        if p2["source_confidence"] > p1["source_confidence"]:
            p1["detected_source"] = p2["detected_source"]
            p1["source_confidence"] = p2["source_confidence"]
            p1["attribution_method"] = p2["attribution_method"]
            p1["ocr_failed"] = p2["ocr_failed"]
            
        if p1["canonical_email"] == "" and p2["canonical_email"] != "":
            p1["canonical_email"] = p2["canonical_email"]
        if p1["canonical_phone"] == "" and p2["canonical_phone"] != "":
            p1["canonical_phone"] = p2["canonical_phone"]

def _update_field(profile: Dict, field: str, value: str, source: str, conf: float):
    if not value: return
    if conf > profile[field]["confidence"]:
        profile[field] = {"value": value, "source": source, "confidence": conf}

def _build_canonical_customers(db: Session) -> List[Dict]:
    """
    Build canonical customer identity layer using a Trust Hierarchy:
    1. Shopify (conf: 1.0)
    2. Warranty Form (conf: 0.8)
    3. OCR (conf: 0.5)
    """
    graph = IdentityGraph()
    
    # 1. Process Shopify Data (Highest Trust)
    shopify_rows = db.query(ShopifyOrder).all()
    for row in shopify_rows:
        e = norm_email(row.email)
        p = norm_phone(row.phone)
        
        if not e and not p:
            continue
            
        if e and p:
            graph.union(e, p)
        
        root = graph.find(e or p)
        prof = graph.profiles[root]
        
        if e: prof["canonical_email"] = e
        if p: prof["canonical_phone"] = p
        
        _update_field(prof, "customer_name", row.customer_name, "Shopify", 1.0)
        _update_field(prof, "city", row.city, "Shopify", 1.0)
        _update_field(prof, "state", row.state, "Shopify", 1.0)
        
        if row.order_id: prof["shopify_orders"].add(row.order_id)
        if row.product: prof["shopify_products"].add(row.product)
        prof["shopify_total_spend"] += (row.total or 0.0)
        
        if row.created_at:
            if not prof["shopify_first_order"] or _parse_date(row.created_at) < _parse_date(prof["shopify_first_order"]):
                prof["shopify_first_order"] = row.created_at
                
    # 2. Process Warranty Form Data (Medium Trust)
    warranty_rows = db.query(ProcessedRow).all()
    
    # Pre-fetch OCR to link it with Warranty
    ocr_rows = db.query(InvoiceExtraction).all()
    ocr_by_row: Dict[int, List] = defaultdict(list)
    for ocr in ocr_rows:
        ocr_by_row[ocr.row_number].append(ocr)
        
    for wr in warranty_rows:
        w_e = norm_email(wr.email)
        w_p = norm_phone(wr.phone)
        
        ocr_list = ocr_by_row.get(wr.sheet_row_number, [])
        best_ocr = ocr_list[0] if ocr_list else None
        
        o_e = norm_email(best_ocr.email) if best_ocr else ""
        o_p = norm_phone(best_ocr.phone) if best_ocr else ""
        
        keys = [k for k in [w_e, w_p, o_e, o_p] if k]
        
        if not keys:
            keys = [f"row_{wr.sheet_row_number}"]
            
        # Union all valid keys for this warranty row
        first_key = keys[0]
        for k in keys[1:]:
            graph.union(first_key, k)
            
        root = graph.find(first_key)
        prof = graph.profiles[root]
        
        if w_e: prof["canonical_email"] = w_e
        elif o_e and not prof["canonical_email"]: prof["canonical_email"] = o_e
        
        if w_p: prof["canonical_phone"] = w_p
        elif o_p and not prof["canonical_phone"]: prof["canonical_phone"] = o_p
        
        # Warranty Trust (0.8)
        _update_field(prof, "customer_name", wr.email, "Warranty", 0.6) # email as fallback name
        _update_field(prof, "customer_name", w_e, "Warranty", 0.6)
        if wr.warranty_brand: prof["warranty_brands"].add(wr.warranty_brand)
        if wr.warranty_product: prof["warranty_products"].add(wr.warranty_product)
        if wr.timestamp:
            if not prof["warranty_date"] or _parse_date(wr.timestamp) < _parse_date(prof["warranty_date"]):
                prof["warranty_date"] = wr.timestamp
                
        # OCR Trust (0.5)
        if best_ocr:
            _update_field(prof, "customer_name", best_ocr.customer_name, "OCR", 0.5)
            _update_field(prof, "city", best_ocr.billing_city or best_ocr.shipping_city, "OCR", 0.5)
            _update_field(prof, "state", best_ocr.billing_state or best_ocr.shipping_state, "OCR", 0.5)
            
            prof["file_ids"].update([o.file_id for o in ocr_list])
            
            if best_ocr.source_confidence > prof["source_confidence"]:
                prof["detected_source"] = best_ocr.detected_source or "Unknown"
                prof["source_confidence"] = best_ocr.source_confidence
                prof["attribution_method"] = best_ocr.attribution_method or "fallback"
                prof["ocr_failed"] = (best_ocr.attribution_method == "ocr_failed")
                

    # 3. Fuzzy Name & Date Buffer Pass (Pass 2)
    # Compare all unmatched warranty customers with unmatched Shopify customers
    roots = list(set(graph.parent.values()))
    
    # We only want to fuzzy match if they don't already have both
    for i in range(len(roots)):
        for j in range(i + 1, len(roots)):
            r1, r2 = graph.find(roots[i]), graph.find(roots[j])
            if r1 == r2: continue
            
            p1, p2 = graph.profiles[r1], graph.profiles[r2]
            
            # One must be Shopify-only, the other Warranty-only
            p1_has_s = len(p1['shopify_orders']) > 0
            p1_has_w = p1['warranty_date'] is not None or len(p1['warranty_products']) > 0
            p2_has_s = len(p2['shopify_orders']) > 0
            p2_has_w = p2['warranty_date'] is not None or len(p2['warranty_products']) > 0
            
            if p1_has_s and p1_has_w: continue
            if p2_has_s and p2_has_w: continue
            if (p1_has_s and p2_has_s) or (p1_has_w and p2_has_w): continue # don't merge same source types
            
            # Check names
            n1 = p1['customer_name']['value']
            n2 = p2['customer_name']['value']
            if not n1 or not n2: continue
            
            similarity = fuzz.token_sort_ratio(n1.lower(), n2.lower())
            if similarity >= 85:
                # Check dates
                d1 = p1['shopify_first_order'] or p1['warranty_date']
                d2 = p2['shopify_first_order'] or p2['warranty_date']
                
                if d1 and d2:
                    diff = abs((_parse_date(d1) - _parse_date(d2)).days)
                    if diff <= ATTRIBUTION_DATE_BUFFER_DAYS:
                        graph.union(r1, r2)
                        merged_root = graph.find(r1)
                        graph.profiles[merged_root]['match_reason'] = f"Fuzzy Name ({similarity:.0f}%) + Date Match"

    # Flatten unique profiles
    unique_profiles = {}
    for key, _ in graph.parent.items():
        root = graph.find(key)
        if root not in unique_profiles:
            unique_profiles[root] = graph.profiles[root]
            
    return list(unique_profiles.values())

def _is_marketplace(source: str) -> bool:
    return source in ("Flipkart", "Amazon", "Myntra", "Meesho", "Nykaa")

def _classify_all_customers(db: Session) -> Dict[str, List[Dict]]:
    canonical = _build_canonical_customers(db)
    
    segments = {
        "marketplace": [],
        "converted": [],
        "direct_d2c": [],
        "probable_d2c": [],
        "unknown": [],
        "ocr_failed": [],
    }
    
    for prof in canonical:
        has_shopify = len(prof["shopify_orders"]) > 0
        has_warranty = len(prof["warranty_products"]) > 0 or prof["warranty_date"] is not None
        source = prof["detected_source"]
        
        record = {
            "email": prof["canonical_email"],
            "phone": prof["canonical_phone"],
            "customer_name": prof["customer_name"]["value"],
            "city": prof["city"]["value"],
            "orders": list(prof["shopify_orders"]),
            "d2c_orders": len(prof["shopify_orders"]),
            "total_spend": prof["shopify_total_spend"],
            "d2c_spend": prof["shopify_total_spend"],
            "products": list(prof["shopify_products"].union(prof["warranty_products"])),
            "first_order": prof["shopify_first_order"] or prof["warranty_date"],
            
            "detected_source": source,
            "source_confidence": prof["source_confidence"],
            "source_inference_method": prof["attribution_method"],
        }
        
        # Determine match reason and confidence bucket
        match_reason = prof.get("match_reason")
        match_confidence_bucket = "Unresolved"
        
        if has_shopify and has_warranty:
            if not match_reason:
                match_reason = "Identity Linked (Email/Phone)"
                match_confidence_bucket = "High Confidence"
            else:
                match_confidence_bucket = "Medium Confidence" # Fuzzy name match
        elif has_shopify and not has_warranty:
            match_reason = "Shopify Only"
            match_confidence_bucket = "High Confidence"
        elif has_warranty and not has_shopify:
            match_reason = "Warranty Only"
            match_confidence_bucket = "Medium Confidence"
            
        record["match_reason"] = match_reason
        record["match_confidence_bucket"] = match_confidence_bucket
        
        # Classification Logic
        if has_shopify and has_warranty:
            if _is_marketplace(source):
                record["conversion_type"] = "Marketplace to D2C"
                segments["converted"].append(record)
            elif source in ("D2C", "Shopify"):
                record["conversion_type"] = "Direct D2C"
                segments["direct_d2c"].append(record)
            else:
                record["conversion_type"] = "Probable D2C"
                segments["probable_d2c"].append(record)
                if prof["ocr_failed"]:
                    segments["ocr_failed"].append(record)
        elif has_shopify and not has_warranty:
            record["conversion_type"] = "Direct D2C"
            segments["direct_d2c"].append(record)
        elif has_warranty and not has_shopify:
            if _is_marketplace(source):
                record["conversion_type"] = "Marketplace Only"
                segments["marketplace"].append(record)
            elif source in ("D2C", "Shopify"):
                record["conversion_type"] = "Direct D2C"
                segments["direct_d2c"].append(record)
            else:
                record["conversion_type"] = "Unknown"
                segments["unknown"].append(record)
                # Note: we don't need a separate list for ocr_failed here if we just want to count them in KPIs

        else:
            # Neither? Shouldn't happen
            pass
            
    return segments


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_kpis(db: Session) -> Dict[str, Any]:
    segments = _classify_all_customers(db)
    canonical = _build_canonical_customers(db)
    warranty_customers = [p for p in canonical if p["warranty_date"] is not None or len(p["warranty_products"]) > 0]
    d2c_customers = [p for p in canonical if len(p["shopify_orders"]) > 0]

    total_revenue = db.query(func.sum(ShopifyOrder.total)).scalar() or 0
    order_count = db.query(func.count(ShopifyOrder.id)).scalar() or 0

    d2c_order_counts: Dict[str, int] = defaultdict(int)
    all_shopify = db.query(ShopifyOrder).all()
    for row in all_shopify:
        key = norm_email(row.email) or norm_phone(row.phone)
        if key:
            d2c_order_counts[key] += 1
    repeat_customers = sum(1 for v in d2c_order_counts.values() if v > 1)

    marketplace_count = len(segments["marketplace"])
    converted_count = len(segments["converted"])
    total_marketplace_pool = marketplace_count + converted_count
    conversion_rate = round((converted_count / total_marketplace_pool * 100), 1) if total_marketplace_pool else 0

    # â”€â”€ Attribution & OCR metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    total_warranty_customers = len(warranty_customers)
    ocr_failed_count = len(segments["ocr_failed"])
    ocr_failed_percentage = round((ocr_failed_count / total_warranty_customers * 100), 1) if total_warranty_customers else 0
    
    # Average source confidence
    confidence_scores = [(c.get("source_confidence") or 0.0) for c in warranty_customers]
    avg_source_confidence = round(sum(confidence_scores) / len(confidence_scores), 2) if confidence_scores else 0.0
    
    # Date-inferred attribution
    date_inferred_count = len(segments["probable_d2c"])
    date_inferred_percentage = round((date_inferred_count / total_warranty_customers * 100), 1) if total_warranty_customers else 0
    
    # Unknown attribution
    unknown_count = len(segments["unknown"])
    unknown_percentage = round((unknown_count / total_warranty_customers * 100), 1) if total_warranty_customers else 0
    heuristic_count = date_inferred_count
    heuristic_percentage = round((heuristic_count / total_warranty_customers * 100), 1) if total_warranty_customers else 0

    sync_status = get_sync_status()
    pending_ocr = db.query(ProcessedRow).filter(ProcessedRow.status == "pending").count()
    failed_ocr = db.query(ProcessedRow).filter(ProcessedRow.status == "failed").count()
    processed_today = (
        db.query(ProcessedRow)
        .filter(ProcessedRow.processed_at >= datetime.utcnow().replace(hour=0, minute=0, second=0))
        .count()
    )
    dup_count = db.query(InvoiceExtraction).filter(InvoiceExtraction.is_duplicate == True).count()
    last_sync = db.query(SyncLog).order_by(SyncLog.started_at.desc()).first()

    return {
        # â”€â”€ Customer Segments â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        "marketplace_buyers": total_marketplace_pool,
        "flipkart_buyers": total_marketplace_pool, # Alias for backward compat
        "d2c_customers": len(d2c_customers),
        "direct_d2c_customers": len(segments["direct_d2c"]),
        "converted_customers": converted_count,
        "only_marketplace": marketplace_count,
        "only_flipkart": marketplace_count, # Alias
        "probable_d2c_count": date_inferred_count,
        "heuristic_attribution_count": heuristic_count,
        "unknown_attribution_count": unknown_count,
        "ocr_failed_count": ocr_failed_count,
        
        # â”€â”€ Conversion Metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        "marketplace_to_d2c_rate": conversion_rate,
        "conversion_rate": conversion_rate, # Alias
        
        # â”€â”€ Revenue Metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        "total_d2c_revenue": round(total_revenue, 2),
        "avg_order_value": round(total_revenue / order_count, 2) if order_count else 0,
        "repeat_customers": repeat_customers,
        
        # â”€â”€ Attribution Quality Metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        "ocr_failed_percentage": ocr_failed_percentage,
        "avg_source_confidence": avg_source_confidence,
        "date_inferred_attribution_count": date_inferred_count,
        "date_inferred_attribution_percentage": date_inferred_percentage,
        "heuristic_attribution_percentage": heuristic_percentage,
        "unknown_attribution_percentage": unknown_percentage,
        
        # â”€â”€ Processing Status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        "pending_ocr": pending_ocr,
        "failed_ocr": failed_ocr,
        "processed_today": processed_today,
        "duplicate_invoices": dup_count,
        "gemini_calls_today": ocr_stats["today_calls"],
        "last_sync_time": last_sync.completed_at.isoformat() if last_sync and last_sync.completed_at else None,
        "last_sync_duration": last_sync.duration_seconds if last_sync else None,
        "sync_running": sync_status.get("running", False),
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Data for tables
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_converted_customers(db: Session) -> List[Dict]:
    return _classify_all_customers(db)["converted"]

def get_marketplace_only(db: Session) -> List[Dict]:
    return _classify_all_customers(db)["marketplace"]

def get_flipkart_only(db: Session) -> List[Dict]:
    return get_marketplace_only(db)

def get_direct_d2c(db: Session) -> List[Dict]:
    return _classify_all_customers(db)["direct_d2c"]

def get_d2c_only(db: Session) -> List[Dict]:
    # Combine direct and probable for backward compat
    segs = _classify_all_customers(db)
    canonical = _build_canonical_customers(db)
    w = [p for p in canonical if p["warranty_date"] is not None or len(p["warranty_products"]) > 0]
    d2c_list = segs["direct_d2c"] + segs["probable_d2c"]
    
    for c in d2c_list:
        if "orders" not in c and "d2c_orders" in c:
            c["orders"] = [None] * int(c.get("d2c_orders", 0))
            c["total_spend"] = c.get("d2c_spend", 0)
            c["products"] = c.get("d2c_products", [])
            c["first_order"] = c.get("d2c_first_order")
            
    return d2c_list

def get_probable_d2c(db: Session) -> List[Dict]:
    return _classify_all_customers(db)["probable_d2c"]

def get_unknown_attribution(db: Session) -> List[Dict]:
    return _classify_all_customers(db)["unknown"]

def get_all_customers(db: Session) -> List[Dict]:
    segments = _classify_all_customers(db)

    all_customers = []
    for c in segments["converted"]:
        all_customers.append({**c, "source": "converted", "spend": c.get("d2c_spend", 0)})
    for c in segments["marketplace"]:
        all_customers.append({**c, "source": "marketplace", "spend": 0})
    for c in segments["direct_d2c"]:
        all_customers.append({**c, "source": "d2c", "spend": c.get("total_spend", c.get("d2c_spend", 0))})
    for c in segments["probable_d2c"]:
        all_customers.append({**c, "source": "probable_d2c", "spend": c.get("d2c_spend", 0)})
    for c in segments["unknown"]:
        all_customers.append({**c, "source": "unknown", "spend": 0})
    return all_customers


def get_attribution_insights(db: Session) -> Dict[str, Any]:
    """
    Comprehensive attribution analytics covering:
    - Source breakdown (Flipkart, Amazon, D2C, etc.)
    - OCR attribution confidence distribution
    - Marketplace â†’ D2C conversion metrics
    - Date-inferred attribution count
    - Unknown source percentage
    """
    segs = _classify_all_customers(db)
    canonical = _build_canonical_customers(db)
    w = [p for p in canonical if p["warranty_date"] is not None or len(p["warranty_products"]) > 0]

    # â”€â”€ Source breakdown â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    source_counts = defaultdict(int)
    source_conversion_metrics: Dict[str, Dict] = defaultdict(
        lambda: {"total": 0, "converted": 0, "direct": 0, "unknown": 0}
    )
    
    # â”€â”€ Confidence distribution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    confidence_bins = {"0.0-0.3": 0, "0.3-0.6": 0, "0.6-0.9": 0, "0.9-1.0": 0}
    detection_methods = defaultdict(int)
    
    # â”€â”€ Conversion metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    total_conversion_days = 0
    converted_count = 0
    marketplace_conversions_by_source: Dict[str, int] = defaultdict(int)
    
    # â”€â”€ OCR failure tracking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ocr_failed_count = 0
    ocr_failed_matched = 0
    ocr_failed_count = 0
    
    # Process warranty customers
    for c in w:
        source = c.get("detected_source", "Unknown")
        source_counts[source] += 1
        
        # Confidence distribution
        conf = c.get("source_confidence", 0.0)
        if conf < 0.3: confidence_bins["0.0-0.3"] += 1
        elif conf < 0.6: confidence_bins["0.3-0.6"] += 1
        elif conf < 0.9: confidence_bins["0.6-0.9"] += 1
        else: confidence_bins["0.9-1.0"] += 1
        
        # Detection method tracking
        method = c.get("attribution_method", "unknown")
        detection_methods[method] += 1
        
        # OCR failure tracking
        if c.get("ocr_failed", False):
            ocr_failed_count += 1

    # â”€â”€ Segment breakdown by source â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for c in segs["marketplace"]:
        source = c.get("detected_source", "Unknown")
        source_conversion_metrics[source]["total"] += 1

    for c in segs["converted"]:
        source = c.get("detected_source", "Unknown")
        source_conversion_metrics[source]["total"] += 1
        source_conversion_metrics[source]["converted"] += 1
        marketplace_conversions_by_source[source] += 1

    for c in segs["direct_d2c"]:
        source = c.get("detected_source", "Unknown")
        if source != "Unknown":
            source_conversion_metrics[source]["direct"] += 1

    for c in segs["unknown"]:
        if c in segs["ocr_failed"]:
            ocr_failed_count += 1

    # â”€â”€ Calculate conversion rates by source â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    source_conversion_rates: Dict[str, Dict] = {}
    for source, metrics in source_conversion_metrics.items():
        total = metrics["total"]
        converted = metrics["converted"]
        rate = round((converted / total * 100), 1) if total > 0 else 0
        source_conversion_rates[source] = {
            "source": source,
            "total_marketplace": total,
            "converted": converted,
            "unconverted": total - converted,
            "conversion_rate": rate,
        }

    # â”€â”€ Marketplace â†’ D2C conversion days â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for c in segs["converted"]:
        w_date = _parse_date(c.get("warranty_date") or c.get("invoice_date"))
        d_date = _parse_date(c.get("d2c_first_order"))
        if w_date and d_date:
            total_conversion_days += max(0, (d_date - w_date).days)
            converted_count += 1

    avg_days = total_conversion_days / converted_count if converted_count else 0

    # â”€â”€ Date-inferred attribution (probable_d2c) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    date_inferred_count = len(segs["probable_d2c"])

    # â”€â”€ Summary stats â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    total_warranty = len(w)
    unknown_count = len(segs["unknown"]) + len(segs["ocr_failed"])
    unknown_percentage = round((unknown_count / total_warranty * 100), 1) if total_warranty > 0 else 0
    
    # Calculate total marketplace to D2C conversion pool
    total_marketplace_pool = len(segs["marketplace"]) + len(segs["converted"])
    marketplace_conversion_rate = round(
        (len(segs["converted"]) / total_marketplace_pool * 100), 1
    ) if total_marketplace_pool > 0 else 0

    return {
        # Source-wise breakdown
        "source_breakdown": [
            {"source": k, "count": v} 
            for k, v in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)
        ],
        
        # Source-wise conversion metrics
        "source_conversion_metrics": sorted(
            source_conversion_rates.values(),
            key=lambda x: x["conversion_rate"],
            reverse=True
        ),
        
        # OCR confidence distribution
        "confidence_distribution": [
            {"range": k, "count": v} 
            for k, v in [
                ("0.0-0.3", confidence_bins["0.0-0.3"]),
                ("0.3-0.6", confidence_bins["0.3-0.6"]),
                ("0.6-0.9", confidence_bins["0.6-0.9"]),
                ("0.9-1.0", confidence_bins["0.9-1.0"]),
            ]
        ],
        
        # Attribution methods used
        "detection_methods": [
            {"method": k, "count": v}
            for k, v in sorted(detection_methods.items(), key=lambda x: x[1], reverse=True)
        ],
        
        # Conversion metrics
        "avg_days_to_conversion": round(avg_days, 1),
        "marketplace_to_d2c_rate": marketplace_conversion_rate,
        "total_marketplace_customers": total_marketplace_pool,
        "total_conversions": len(segs["converted"]),
        "avg_days_to_d2c": round(avg_days, 1) if converted_count > 0 else 0,
        
        # Date-inferred (fallback) matching
        "date_inferred_attribution_count": date_inferred_count,
        "date_inferred_percentage": round(
            (date_inferred_count / total_warranty * 100), 1
        ) if total_warranty > 0 else 0,
        
        # OCR failure metrics
        "ocr_failed_count": ocr_failed_count,
        "ocr_failed_percentage": round(
            (ocr_failed_count / total_warranty * 100), 1
        ) if total_warranty > 0 else 0,
        "ocr_failed_with_fallback_match": 0,
        "ocr_failed_count": ocr_failed_count,
        
        # Unknown attribution
        "unknown_attribution_count": unknown_count,
        "unknown_attribution_percentage": unknown_percentage,
        
        # Summary
        "total_warranty_customers": total_warranty,
        "direct_d2c_customers": len(segs["direct_d2c"]),
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Chart data
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        city_map[r.billing_city] = {"city": r.billing_city, "marketplace": r.count, "d2c": 0}
    for r in d2c_cities:
        if r.city in city_map:
            city_map[r.city]["d2c"] = r.count
        else:
            city_map[r.city] = {"city": r.city, "marketplace": 0, "d2c": r.count}
    return sorted(city_map.values(), key=lambda x: x["marketplace"] + x["d2c"], reverse=True)[:10]


def get_revenue_by_month(db: Session) -> List[Dict]:
    orders = db.query(ShopifyOrder).all()
    monthly: Dict[str, float] = defaultdict(float)
    for o in orders:
        if o.created_at and o.total:
            dt = _parse_date(o.created_at)
            if dt:
                monthly[dt.strftime("%Y-%m")] += o.total
    return [{"month": k, "revenue": round(v, 2)} for k, v in sorted(monthly.items())]


def get_registrations_by_month(db: Session) -> List[Dict]:
    rows = db.query(ProcessedRow).all()
    monthly: Dict[str, int] = defaultdict(int)
    for r in rows:
        if r.timestamp:
            dt = _parse_date(r.timestamp)
            if dt:
                monthly[dt.strftime("%Y-%m")] += 1
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
    Build a customer journey timeline.
    """
    norm = norm_email(email)

    def _invoice_score(inv: InvoiceExtraction) -> int:
        score = 0
        if inv.invoice_number: score += 30
        if inv.order_id: score += 25
        if inv.product_title: score += 15
        if inv.grand_total is not None: score += 20
        if inv.invoice_date: score += 10
        if inv.file_id: score += 5
        return score

    warranty_rows = db.query(ProcessedRow).filter(ProcessedRow.email == norm).all()
    warranty_row_numbers = [r.sheet_row_number for r in warranty_rows]

    ocr_invoices = []
    if warranty_row_numbers:
        ocr_invoices = (
            db.query(InvoiceExtraction)
            .filter(InvoiceExtraction.row_number.in_(warranty_row_numbers))
            .order_by(InvoiceExtraction.row_number.asc(), InvoiceExtraction.extracted_at.desc())
            .all()
        )

    best_by_row: Dict[int, InvoiceExtraction] = {}
    for inv in ocr_invoices:
        if not any([inv.product_title, inv.invoice_number, inv.order_id, inv.grand_total is not None, inv.invoice_date]):
            continue
        current = best_by_row.get(inv.row_number)
        if current is None or _invoice_score(inv) > _invoice_score(current):
            best_by_row[inv.row_number] = inv

    d2c_orders = db.query(ShopifyOrder).filter(ShopifyOrder.email == norm).order_by(ShopifyOrder.created_at).all()

    events = []
    warranty_rows_with_invoices = set(best_by_row.keys())
    
    if warranty_rows:
        for wr in warranty_rows:
            if wr.sheet_row_number in warranty_rows_with_invoices:
                continue
            events.append({
                "type": "warranty_registration",
                "date": wr.timestamp or "",
                "product": wr.warranty_product or "Warranty Registration",
                "amount": None,
                "platform": "Warranty Registration",
                "invoice_number": None,
            })
    
    for inv in sorted(best_by_row.values(), key=lambda i: (_parse_date(i.invoice_date) or datetime.max, i.row_number or 0)):
        ptype = "marketplace_purchase" if _is_marketplace(inv.detected_source) else "purchase"
        events.append({
            "type": ptype,
            "date": inv.invoice_date or "",
            "product": inv.product_title,
            "amount": inv.grand_total,
            "platform": inv.detected_source or "Unknown",
            "invoice_number": inv.invoice_number,
            "source_confidence": inv.source_confidence,
        })
    
    for order in sorted(d2c_orders, key=lambda item: _parse_date(item.created_at) or datetime.max):
        events.append({
            "type": "d2c_order",
            "date": order.created_at or "",
            "product": order.product,
            "amount": order.total,
            "order_id": order.order_id,
            "platform": "Shopify / D2C",
        })

    events.sort(key=lambda item: (_parse_date(item.get("date")) or datetime.max, 0 if item.get("type") == "warranty_registration" else 1))
    
    return {
        "email": norm,
        "customer_name": warranty_rows[0].email if warranty_rows else email,
        "events": events,
        "marketplace_count": len(best_by_row),
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

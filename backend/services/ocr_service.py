"""
ocr_service.py
Gemini Vision OCR pipeline — Gemini-only, production-grade.
- Uses the configured free-tier Gemini vision model
- Exponential backoff on 429 quota errors
- retry_pending status instead of immediate failure
- In-memory PDF→image conversion (PyMuPDF, never touches disk)
- Structured JSON extraction with source/platform attribution
- Expanded marketplace patterns (Flipkart, Amazon, Myntra, Ajio, Meesho, Nykaa, D2C)
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, date
from typing import Optional, Dict, Any, Tuple

import google.generativeai as genai
from config import (
    GEMINI_API_KEY, GEMINI_MODEL_NAME, MAX_OCR_CONCURRENCY, OCR_RETRY_LIMIT,
    OCR_DELAY_SECONDS, OCR_TIMEOUT_SECONDS, MAX_PDF_PAGES,
    GEMINI_QUOTA_COOLDOWN_SECONDS,
)
from database import ProcessedRow, InvoiceExtraction
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)

# Global concurrency limiter (1 at a time to be gentle with free tier)
_semaphore = asyncio.Semaphore(MAX_OCR_CONCURRENCY)

# Runtime stats (reset on restart)
ocr_stats: Dict[str, Any] = {
    "total_calls": 0,
    "success": 0,
    "failed": 0,
    "retry_pending": 0,
    "today_calls": 0,
    "today_date": str(date.today()),
    # Quota tracking
    "quota_exhausted": False,
    "quota_exhausted_at": None,   # epoch float
    "consecutive_failures": 0,
}

# ── Marketplace keyword lists for source detection ─────────────────────────
_MARKETPLACE_PATTERNS: Dict[str, list] = {
    "Flipkart": [
        "flipkart", "www.flipkart.com", "flipkart.com", "ekart",
        "flipkart internet", "jeeves", "flipkart logistics", "fbl",
        "flipkart business", "flipkart india", "retailnet",
        "omnitechretail", "vision star", "corseca", "hydel",
        "seller fulfilled by flipkart",
    ],
    "Amazon": [
        "amazon", "www.amazon.in", "amazon.in", "amazon seller",
        "amazon.com", "amazon fulfillment", "amzn", "amazon pay",
        "amazon.co.in", "amazon logistics", "appario", "cloudtail",
        "cocoblu", "dawntech", "amazon easy ship", "fulfillment by amazon",
    ],
    "Myntra": [
        "myntra", "www.myntra.com", "myntra.com", "myntra designs",
        "myntra fashion", "myntra.in", "flashtech", "shreyash",
    ],
    "Ajio": [
        "ajio", "www.ajio.com", "ajio.com", "ajio business",
        "reliance ajio", "jio fashion",
    ],
    "Meesho": [
        "meesho", "www.meesho.com", "meesho.com", "meesho supply",
        "meesho marketplace",
    ],
    "Nykaa": [
        "nykaa", "www.nykaa.com", "nykaa.com", "nykaa fashion",
        "nykaa beauty", "fsh by nykaa",
    ],
}

_D2C_PATTERNS = [
    "shopify", "myshopify", "shopify.com", "woocommerce", "razorpay",
    "direct", "brand website", "own website", "company website",
    "wix", "squarespace", "magento", "bigcommerce", "prestashop",
    "self", "direct sale", "direct purchase", "brand direct",
    "our website", "direct order", "website order", "online store",
    "brand store", "official website", "official store",
]

# Order ID / Invoice number prefix patterns per marketplace
_INVOICE_NUMBER_PATTERNS: Dict[str, list] = {
    "Flipkart": [r"^FK-?\d", r"^OD-?\d", r"OD\d{15}"],
    "Amazon":   [r"^\d{3}-\d{7}-\d{7}", r"^[A-Z]{2}\d-\w+"],
}

OCR_PROMPT = """You are an expert invoice data extraction AI.
Carefully analyze this invoice image and extract the following fields.
Return ONLY a valid JSON object — no markdown, no explanation, no extra text.

{
  "customer_name": "Full name on invoice or shipping label",
  "email": "Customer email address (lowercase, trimmed, or null)",
  "phone": "Customer mobile number (exactly 10 digits, Indian mobile only). Reject GSTINs, order IDs, tracking numbers.",
  "order_id": "Order ID or transaction ID (e.g. OD435..., 402-..., etc.)",
  "invoice_number": "Invoice or bill number",
  "invoice_date": "Date in YYYY-MM-DD format",
  "product_title": "Full product name from invoice",
  "size": "Product size (e.g. Cabin, Check-in, 20inch, 55cm)",
  "colour": "Product colour",
  "grand_total": "Total amount paid, digits only (e.g. 2499.00)",
  "seller_name": "Seller or company/brand name printed on invoice",
    "seller_gstin": "Seller GSTIN if visible, otherwise null",
    "marketplace_keywords": ["Any marketplace, checkout, courier, brand, or domain keywords visible on the invoice"],
  "billing_city": "Billing address city",
  "billing_state": "Billing address state",
  "shipping_city": "Shipping / delivery city",
  "shipping_state": "Shipping / delivery state",
    "platform": "Flipkart | Amazon | Myntra | Ajio | Meesho | Nykaa | Shopify | Direct Website | D2C | Unknown"
}

PLATFORM DETECTION RULES (apply in order):
1. Flipkart → logo, domain flipkart.com, ekart, FBL, jeeves, order ID starts OD
2. Amazon → logo, domain amazon.in, order ID format 402-XXXXXXX-XXXXXXX, AMZN
3. Myntra → logo, domain myntra.com, Myntra Designs
4. Ajio → logo, domain ajio.com, Reliance Ajio
5. Meesho → logo, domain meesho.com
6. Nykaa → logo, domain nykaa.com
7. Shopify/D2C → Shopify checkout, Razorpay, brand's own domain, WooCommerce, Magento
8. Unknown → cannot determine from invoice

EXTRACTION RULES:
- phone: 10-digit Indian mobile starting with 6/7/8/9 only. null if not found.
- grand_total: numeric string only. null if not found.
- invoice_date: YYYY-MM-DD. null if not found.
- Use null for any field not found — never guess.
- Return ONLY the JSON object, no markdown or explanation."""


def _convert_pdf_bytes_to_image(pdf_bytes: bytes) -> bytes:
    """
    Convert first page of PDF to PNG bytes in memory. Never writes to disk.
    Uses PyMuPDF (fitz) — no poppler required.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(doc)
        if page_count > MAX_PDF_PAGES:
            logger.info(f"PDF has {page_count} pages, processing first page only")
        page = doc[0]
        # 200 DPI for better OCR quality
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        doc.close()
        return img_bytes
    except ImportError:
        raise RuntimeError("PyMuPDF not installed. Run: pip install PyMuPDF")
    except Exception as e:
        raise RuntimeError(f"PDF conversion failed: {e}")


def _refresh_today_stats():
    today = str(date.today())
    if ocr_stats["today_date"] != today:
        ocr_stats["today_calls"] = 0
        ocr_stats["today_date"] = today


def is_quota_cooling_down() -> bool:
    """Return True if we're in a quota cooldown window."""
    if not ocr_stats["quota_exhausted"]:
        return False
    exhausted_at = ocr_stats["quota_exhausted_at"]
    if exhausted_at is None:
        return False
    elapsed = time.time() - exhausted_at
    if elapsed >= GEMINI_QUOTA_COOLDOWN_SECONDS:
        # Cooldown expired — reset
        ocr_stats["quota_exhausted"] = False
        ocr_stats["quota_exhausted_at"] = None
        ocr_stats["consecutive_failures"] = 0
        logger.info(f"Gemini quota cooldown expired after {elapsed:.0f}s. Resuming OCR.")
        return False
    remaining = GEMINI_QUOTA_COOLDOWN_SECONDS - elapsed
    logger.debug(f"Gemini quota cooling down — {remaining:.0f}s remaining")
    return True


def _parse_retry_delay(error_str: str) -> int:
    """Parse retry_delay seconds from Gemini 429 error message."""
    match = re.search(r'retry_delay\s*\{[^}]*seconds:\s*(\d+)', error_str)
    if match:
        return int(match.group(1))
    match = re.search(r'retry[-_ ]after[:\s]*(\d+)', error_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r'retry in (\d+(?:\.\d+)?)s', error_str, re.IGNORECASE)
    if match:
        return int(float(match.group(1))) + 1
    return 60  # Default cooldown


def _score_invoice_validity(extracted: Dict) -> Dict[str, Any]:
    """Score invoice validity. Returns {status, score, reasons}."""
    score = 0
    reasons = []

    def _to_float(v):
        try:
            if v is None: return 0.0
            return float(re.sub(r"[^\d.]", "", str(v)))
        except Exception:
            return 0.0

    if extracted.get("order_id") or extracted.get("invoice_number"):
        score += 30
    else:
        reasons.append("missing_order_id")
        score -= 20

    total = _to_float(extracted.get("grand_total"))
    if total > 0:
        score += 25
    else:
        reasons.append("missing_grand_total")
        score -= 30

    if extracted.get("email") or extracted.get("phone"):
        score += 20
    else:
        reasons.append("missing_contact_info")
        score -= 25

    if extracted.get("customer_name"):
        score += 10
    else:
        reasons.append("missing_customer_name")
        score -= 5

    platform = extracted.get("platform", "Unknown")
    if platform and platform.lower() not in ("unknown", ""):
        score += 15
    else:
        reasons.append("unknown_platform")
        score -= 10

    if total and (total < 10 or total > 1_000_000):
        reasons.append(f"amount_out_of_range({total})")
        score -= 10

    score = max(0, min(100, score))
    if score >= 60:
        status = "valid"
    elif score >= 30:
        status = "suspicious"
    else:
        status = "invalid"

    return {"status": status, "score": score, "reasons": reasons}


def _detect_source_from_extraction(extracted: Dict) -> Dict[str, Any]:
    """
    Infer acquisition source from extracted invoice fields.
    Priority: platform field → seller name → order ID patterns → fallback
    """
    platform_raw = (extracted.get("platform") or "").strip()
    seller_raw   = (extracted.get("seller_name") or "").strip().lower()
    gstin_raw    = (extracted.get("seller_gstin") or "").strip().lower()
    order_id_raw = (extracted.get("order_id") or "").strip()
    inv_num_raw  = (extracted.get("invoice_number") or "").strip()
    keywords_raw = extracted.get("marketplace_keywords") or []

    if isinstance(keywords_raw, list):
        keyword_blob = " ".join(str(v) for v in keywords_raw if v)
    else:
        keyword_blob = str(keywords_raw)
    keyword_blob = keyword_blob.lower().strip()

    # 1. Platform field (direct from OCR)
    if platform_raw and platform_raw.lower() not in ("unknown", ""):
        platform_lower = platform_raw.lower()
        for source, keywords in _MARKETPLACE_PATTERNS.items():
            if any(kw.lower() in platform_lower for kw in keywords):
                return {"detected_source": source, "source_confidence": 0.95,
                        "detection_method": "ocr_platform_field"}
        if any(kw in platform_lower for kw in _D2C_PATTERNS) or "direct website" in platform_lower:
            return {"detected_source": "D2C", "source_confidence": 0.90,
                    "detection_method": "ocr_platform_field"}
        # Platform set but unrecognised → store as-is
        return {"detected_source": platform_raw, "source_confidence": 0.70,
                "detection_method": "ocr_platform_field"}

    # 2. Seller name keyword scan
    if seller_raw:
        for source, keywords in _MARKETPLACE_PATTERNS.items():
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in seller_raw:
                    return {"detected_source": source, "source_confidence": 0.85,
                            "detection_method": "ocr_seller_name"}
        for kw in _D2C_PATTERNS:
            if kw.lower() in seller_raw:
                return {"detected_source": "D2C", "source_confidence": 0.78,
                        "detection_method": "ocr_seller_name"}

    if keyword_blob:
        for source, keywords in _MARKETPLACE_PATTERNS.items():
            if any(kw.lower() in keyword_blob for kw in keywords):
                return {"detected_source": source, "source_confidence": 0.88,
                        "detection_method": "ocr_keyword_scan"}
        if any(kw in keyword_blob for kw in _D2C_PATTERNS):
            return {"detected_source": "D2C", "source_confidence": 0.82,
                    "detection_method": "ocr_keyword_scan"}

    if gstin_raw and gstin_raw not in ("", "null"):
        return {"detected_source": "Unknown", "source_confidence": 0.55,
                "detection_method": "ocr_gstin"}

    # 3. Order ID / Invoice number regex patterns
    for id_str in (order_id_raw, inv_num_raw):
        if not id_str:
            continue
        for source, patterns in _INVOICE_NUMBER_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, id_str, re.IGNORECASE):
                    return {"detected_source": source, "source_confidence": 0.65,
                            "detection_method": "ocr_invoice_pattern"}

    return {"detected_source": "Unknown", "source_confidence": 0.0,
            "detection_method": "fallback"}


def _is_marketplace_source(detected_source: str) -> bool:
    return detected_source in {"Flipkart", "Amazon", "Myntra", "Ajio", "Meesho", "Nykaa"}


async def extract_invoice_data(
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    file_id: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Extract structured invoice data using Gemini Vision.
    Processes entirely in memory — no disk I/O.

    Returns:
        (extracted_dict, status) where status is one of:
          "success"       — Gemini extracted data successfully
          "retry_pending" — Quota/rate-limit hit; should requeue for later
          "failed"        — Genuine failure (bad image, timeout, etc.)
    """
    # Quick check: if quota is in cooldown window, skip immediately
    if is_quota_cooling_down():
        logger.info(f"Quota cooldown active — skipping Gemini for {filename}, marking retry_pending")
        ocr_stats["retry_pending"] += 1
        return None, "retry_pending"

    async with _semaphore:
        last_error: Optional[str] = None

        for attempt in range(OCR_RETRY_LIMIT):
            try:
                # Delay between calls to respect free-tier rate limits
                if attempt == 0 and OCR_DELAY_SECONDS > 0:
                    await asyncio.sleep(OCR_DELAY_SECONDS)
                elif attempt > 0:
                    backoff = min(2 ** attempt, 32)
                    logger.info(f"Retry {attempt} for {filename} — waiting {backoff}s")
                    await asyncio.sleep(backoff)

                # PDF → PNG conversion in memory
                if mime_type == "application/pdf":
                    try:
                        image_bytes = _convert_pdf_bytes_to_image(file_bytes)
                        image_mime = "image/png"
                        logger.info(f"PDF converted to PNG for {filename}")
                    except RuntimeError as pdf_err:
                        logger.error(f"PDF conversion failed for {filename}: {pdf_err}")
                        return None, "failed"
                elif mime_type in ("image/jpeg", "image/jpg", "image/png",
                                   "image/webp", "image/gif", "image/bmp"):
                    image_bytes = file_bytes
                    image_mime = mime_type
                else:
                    logger.warning(f"Unsupported MIME type: {mime_type} for {filename}")
                    return None, "failed"

                # Use the configured free-tier Gemini vision model.
                model = genai.GenerativeModel(GEMINI_MODEL_NAME)

                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            model.generate_content,
                            [{"mime_type": image_mime, "data": image_bytes}, OCR_PROMPT]
                        ),
                        timeout=OCR_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    last_error = f"Gemini timeout after {OCR_TIMEOUT_SECONDS}s"
                    logger.warning(f"OCR timeout for {filename} (attempt {attempt + 1})")
                    if attempt >= OCR_RETRY_LIMIT - 1:
                        break
                    continue

                # Parse JSON from response
                raw_text = (getattr(response, "text", "") or "").strip()
                if not raw_text:
                    raise ValueError("Empty Gemini response")
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                raw_text = re.sub(r"\s*```$", "", raw_text).strip()

                extracted: Dict = json.loads(raw_text)

                # ── Post-processing ──────────────────────────────────────
                if extracted.get("email"):
                    extracted["email"] = str(extracted["email"]).lower().strip()

                if extracted.get("phone"):
                    digits = re.sub(r"\D", "", str(extracted["phone"]))
                    if len(digits) >= 10:
                        last10 = digits[-10:]
                        extracted["phone"] = last10 if last10[0] in "6789" else None
                    else:
                        extracted["phone"] = None

                if extracted.get("grand_total") is not None:
                    total_str = re.sub(r"[^\d.]", "", str(extracted["grand_total"]))
                    try:
                        extracted["grand_total"] = float(total_str) if total_str else None
                    except ValueError:
                        extracted["grand_total"] = None

                if extracted.get("seller_gstin"):
                    gstin = re.sub(r"[^A-Z0-9]", "", str(extracted["seller_gstin"]).upper())
                    extracted["seller_gstin"] = gstin or None

                if extracted.get("marketplace_keywords"):
                    keywords_value = extracted["marketplace_keywords"]
                    if isinstance(keywords_value, str):
                        extracted["marketplace_keywords"] = [k.strip() for k in re.split(r"[,;\n]", keywords_value) if k.strip()]
                    elif not isinstance(keywords_value, list):
                        extracted["marketplace_keywords"] = [str(keywords_value)]

                # Source detection
                source_info = _detect_source_from_extraction(extracted)
                extracted["detected_source"]   = source_info["detected_source"]
                extracted["source_confidence"] = source_info["source_confidence"]
                extracted["detection_method"]  = source_info["detection_method"]

                # Validity score
                extracted["validity_score"] = _score_invoice_validity(extracted)

                # Cleanup
                del image_bytes

                # Update stats
                _refresh_today_stats()
                ocr_stats["total_calls"] += 1
                ocr_stats["success"] += 1
                ocr_stats["today_calls"] += 1
                ocr_stats["consecutive_failures"] = 0
                ocr_stats["quota_exhausted"] = False

                logger.info(
                    f"Gemini OCR success: {filename} | attempt {attempt + 1} | "
                    f"validity: {extracted['validity_score']['status']} | "
                    f"source: {extracted['detected_source']} @ {extracted['source_confidence']:.2f}"
                )
                return extracted, "success"

            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                logger.warning(f"OCR JSON error for {filename} (attempt {attempt + 1}): {e}")
                # Don't retry JSON errors — Gemini gave garbage response
                break

            except Exception as e:
                err_str = str(e)
                last_error = err_str

                # 429 Quota / rate limit — do NOT retry, mark for later
                if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                    retry_delay = _parse_retry_delay(err_str)
                    logger.warning(
                        f"Gemini quota/rate limit for {filename}. "
                        f"retry_delay={retry_delay}s. Marking retry_pending."
                    )
                    _refresh_today_stats()
                    ocr_stats["total_calls"] += 1
                    ocr_stats["retry_pending"] += 1
                    ocr_stats["consecutive_failures"] += 1
                    ocr_stats["last_retry_delay_seconds"] = retry_delay
                    ocr_stats["last_error"] = err_str

                    # If 3+ consecutive failures, enter cooldown
                    if ocr_stats["consecutive_failures"] >= 3:
                        cooldown = max(retry_delay, GEMINI_QUOTA_COOLDOWN_SECONDS)
                        ocr_stats["quota_exhausted"] = True
                        ocr_stats["quota_exhausted_at"] = time.time()
                        logger.warning(
                            f"Gemini quota exhausted — entering {cooldown}s cooldown. "
                            f"All new OCR requests will be queued as retry_pending."
                        )

                    return None, "retry_pending"

                # Other errors — retry with backoff
                logger.error(f"OCR error for {filename} (attempt {attempt + 1}): {e}")
                if attempt >= OCR_RETRY_LIMIT - 1:
                    break

        # All attempts exhausted
        _refresh_today_stats()
        ocr_stats["total_calls"] += 1
        ocr_stats["failed"] += 1
        ocr_stats["last_error"] = last_error or "unknown_failure"
        return None, "failed"

async def process_invoice_orchestrated(
    db: Session,
    file_bytes: bytes,
    mime_type: str,
    actual_name: str,
    file_id: str,
    row_number: int,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Unified entry point for invoice processing.
    1. Check OCR Memory (same email with high confidence)
    2. Try Gemini OCR
    3. On failure (non-quota), use Heuristic fallback
    4. On quota hit, return retry_pending
    """
    start_time = time.time()

    # 1. OCR Memory
    warranty_row = db.query(ProcessedRow).filter(ProcessedRow.sheet_row_number == row_number).first()
    if warranty_row and warranty_row.email:
        existing = db.query(InvoiceExtraction).filter(
            InvoiceExtraction.email == warranty_row.email,
            InvoiceExtraction.source_confidence > 0.8
        ).first()
        if existing:
            logger.info(f"OCR Memory Hit: {warranty_row.email} -> {existing.detected_source}")
            payload = _heuristic_fallback_logic(row_number, db)
            if payload:
                payload.update({
                    "detected_source": existing.detected_source,
                    "source_confidence": 0.95,
                    "detection_method": "historical_memory",
                    "ocr_provider": "memory_cache",
                    "ocr_latency_ms": round((time.time() - start_time) * 1000, 2),
                })
                return payload, "success"

    # 2. Gemini OCR
    extracted, status = await extract_invoice_data(file_bytes, mime_type, actual_name, file_id)
    
    if status == "retry_pending":
        return None, "retry_pending"
    
    if extracted:
        extracted["ocr_provider"] = "gemini"
        extracted["ocr_latency_ms"] = round((time.time() - start_time) * 1000, 2)
        return extracted, "success"

    # 3. Heuristic Fallback
    logger.warning(f"Gemini failed for {actual_name}, using heuristic fallback.")
    payload = _heuristic_fallback_logic(row_number, db)
    if payload:
        payload["ocr_provider"] = "heuristic"
        payload["ocr_latency_ms"] = round((time.time() - start_time) * 1000, 2)
        return payload, "heuristic_success"

    return None, "failed"


def _heuristic_fallback_logic(row_number: int, db: Session) -> Optional[Dict[str, Any]]:
    """Lightweight heuristic extraction from Sheet data."""
    wr = db.query(ProcessedRow).filter(ProcessedRow.sheet_row_number == row_number).first()
    if not wr: return None
    
    return {
        "customer_name": wr.email or "Unknown",
        "email": wr.email,
        "phone": wr.phone,
        "order_id": None,
        "invoice_number": None,
        "invoice_date": wr.timestamp,
        "product_title": wr.warranty_product,
        "size": wr.warranty_size,
        "colour": wr.warranty_colour,
        "grand_total": None,
        "seller_name": wr.warranty_brand,
        "platform": "Warranty_Registration",
        "detected_source": "Unknown",
        "source_confidence": 0.0,
        "detection_method": "heuristic_fallback",
        "validity_score": {"status": "excel_only", "score": 50, "reasons": ["gemini_failed_using_excel"]}
    }

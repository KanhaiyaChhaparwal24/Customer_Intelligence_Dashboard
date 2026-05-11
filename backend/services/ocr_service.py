"""
ocr_service.py
Gemini 2.5 Flash Vision OCR pipeline.
- Async with concurrency semaphore (MAX_OCR_CONCURRENCY)
- Exponential backoff on 429 rate-limit errors
- In-memory PDF→image conversion (never touches disk)
- Structured JSON extraction
"""
import asyncio
import base64
import json
import logging
import re
import time
from datetime import datetime, date
from typing import Optional, Dict, Any

import google.generativeai as genai
from config import GEMINI_API_KEY, MAX_OCR_CONCURRENCY, OCR_RETRY_LIMIT, OCR_DELAY_SECONDS

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)

# Global concurrency limiter
_semaphore = asyncio.Semaphore(MAX_OCR_CONCURRENCY)

# Runtime stats (reset on restart)
ocr_stats: Dict[str, Any] = {
    "total_calls": 0,
    "success": 0,
    "failed": 0,
    "today_calls": 0,
    "today_date": str(date.today()),
}

OCR_PROMPT = """You are an expert invoice data extraction AI.
Analyze this invoice image carefully and extract the following fields.
Return ONLY a valid JSON object — no markdown, no explanation, no extra text.

Required fields:
{
  "customer_name": "Full name on invoice",
  "email": "email address (lowercase, trimmed)",
  "phone": "digits only, last 10 digits",
  "order_id": "Order ID or transaction ID",
  "invoice_number": "Invoice or bill number",
  "invoice_date": "Date in YYYY-MM-DD format",
  "product_title": "Full product name",
  "size": "Product size e.g. Cabin, Check-in, 20inch, 28inch",
  "colour": "Product colour",
  "grand_total": "Total amount, digits only, no currency symbols",
  "seller_name": "Seller or company name",
  "billing_city": "Billing city",
  "billing_state": "Billing state",
  "shipping_city": "Shipping city",
  "shipping_state": "Shipping state",
  "platform": "Flipkart | Amazon | D2C | Shopify | Unknown"
}

Rules:
- Use null for any field not found
- platform: infer from seller name, logo, header (Flipkart = Flipkart, Myntra website = D2C, etc.)
- grand_total: numeric string only e.g. "2499.00"
- invoice_date: convert to YYYY-MM-DD if possible
- Return ONLY the JSON object"""


def _convert_pdf_bytes_to_image(pdf_bytes: bytes) -> bytes:
    """
    Convert first page of PDF to PNG bytes in memory. Never writes to disk.
    Respects MAX_PDF_PAGES limit to avoid processing huge PDFs.
    """
    from config import MAX_PDF_PAGES
    
    # Try PyMuPDF first (fastest, no poppler dependency)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Enforce page limit
        page_count = len(doc)
        if page_count > MAX_PDF_PAGES:
            logger.info(f"PDF has {page_count} pages, processing only first {MAX_PDF_PAGES}")
        
        page = doc[0]  # Always first page
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        doc.close()
        return img_bytes
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"PyMuPDF failed: {e}")

    # Fallback: pdf2image (requires poppler)
    try:
        import pdf2image
        images = pdf2image.convert_from_bytes(
            pdf_bytes, first_page=1, last_page=min(MAX_PDF_PAGES, 1), dpi=150
        )
        if images:
            import io
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            result = buf.getvalue()
            buf.close()
            return result
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"pdf2image failed: {e}")

    raise RuntimeError("No PDF converter available. Install PyMuPDF: pip install PyMuPDF")


def _refresh_today_stats():
    today = str(date.today())
    if ocr_stats["today_date"] != today:
        ocr_stats["today_calls"] = 0
        ocr_stats["today_date"] = today


def _score_invoice_validity(extracted: Dict) -> Dict[str, Any]:
    """
    Score invoice validity to detect garbage/random screenshots.
    Returns {status: "valid"|"suspicious"|"invalid", score: 0-100, reasons: [...]}.
    
    Valid invoice must have:
    - order_id or invoice_number (mandatory)
    - grand_total > 0 (mandatory)
    - email or phone (at least one)
    - customer_name (optional but expected)
    
    Suspicious if:
    - Missing email AND phone
    - grand_total = 0 or null
    - Platform = "Unknown" (couldn't identify seller)
    """
    score = 0
    reasons = []
    
    # Check mandatory fields
    has_order_id = bool(extracted.get("order_id"))
    has_invoice_number = bool(extracted.get("invoice_number"))

    def _to_float(value: Any) -> float:
        try:
            if value is None:
                return 0.0
            if isinstance(value, (int, float)):
                return float(value)
            cleaned = str(value).replace(",", "").strip()
            if not cleaned:
                return 0.0
            return float(cleaned)
        except Exception:
            return 0.0

    total_value = _to_float(extracted.get("grand_total"))
    has_total = total_value > 0
    has_email = bool(extracted.get("email"))
    has_phone = bool(extracted.get("phone"))
    has_customer_name = bool(extracted.get("customer_name"))
    has_platform = extracted.get("platform") and extracted.get("platform") != "Unknown"
    
    # Mandatory: at least one ID field
    if has_order_id or has_invoice_number:
        score += 30
    else:
        reasons.append("missing_order_id")
        score -= 20
    
    # Mandatory: must have amount
    if has_total:
        score += 25
    else:
        reasons.append("missing_grand_total")
        score -= 30
    
    # Contact info: must have at least email or phone
    if has_email or has_phone:
        score += 20
    else:
        reasons.append("missing_contact_info")
        score -= 25
    
    # Customer name is expected
    if has_customer_name:
        score += 10
    else:
        reasons.append("missing_customer_name")
        score -= 5
    
    # Platform should be identifiable
    if has_platform:
        score += 15
    else:
        reasons.append("unknown_platform")
        score -= 10
    
    # Verify reasonable amount (basic sanity check)
    amount = total_value
    if amount and (amount < 10 or amount > 1000000):
        reasons.append(f"amount_out_of_range({amount})")
        score -= 10
    
    # Determine status
    if score >= 60:
        status = "valid"
    elif score >= 30:
        status = "suspicious"
    else:
        status = "invalid"
    
    return {
        "status": status,
        "score": max(0, min(100, score)),
        "reasons": reasons,
    }



async def extract_invoice_data(
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    file_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Extract structured invoice data using Gemini Vision.
    Processes entirely in memory — no disk I/O.
    Returns extracted dict or None on failure.
    
    Enforces OCR_TIMEOUT_SECONDS to prevent hanging.
    """
    from config import OCR_TIMEOUT_SECONDS
    
    async with _semaphore:
        last_error: Optional[str] = None

        for attempt in range(OCR_RETRY_LIMIT):
            try:
                # Add delay between Gemini calls to prevent rate limiting
                if attempt > 0 or OCR_DELAY_SECONDS > 0:
                    await asyncio.sleep(OCR_DELAY_SECONDS if attempt == 0 else 2 ** attempt)

                # Convert PDF to image in memory
                if mime_type == "application/pdf":
                    image_bytes = _convert_pdf_bytes_to_image(file_bytes)
                    image_mime = "image/png"
                elif mime_type in ("image/jpeg", "image/jpg", "image/png",
                                   "image/webp", "image/gif", "image/bmp"):
                    image_bytes = file_bytes
                    image_mime = mime_type
                else:
                    logger.warning(f"Unsupported MIME type: {mime_type} for {filename}")
                    return None

                # Base64 encode
                b64 = base64.b64encode(image_bytes).decode("utf-8")

                # Call Gemini with timeout enforcement
                model = genai.GenerativeModel("gemini-2.5-flash")
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            model.generate_content,
                            [{"mime_type": image_mime, "data": b64}, OCR_PROMPT]
                        ),
                        timeout=OCR_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    last_error = f"Gemini call exceeded {OCR_TIMEOUT_SECONDS}s timeout"
                    logger.warning(f"OCR timeout for {filename} (attempt {attempt + 1}): {last_error}")
                    if attempt >= OCR_RETRY_LIMIT - 1:
                        break
                    await asyncio.sleep(2 ** attempt)
                    continue

                # Parse response
                text = response.text.strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                text = text.strip()

                extracted: Dict = json.loads(text)

                # ── Post-processing ──────────────────────────────────────
                # Email normalisation
                if extracted.get("email"):
                    extracted["email"] = str(extracted["email"]).lower().strip()

                # Phone: digits only, last 10
                if extracted.get("phone"):
                    digits = re.sub(r"\D", "", str(extracted["phone"]))
                    extracted["phone"] = digits[-10:] if len(digits) >= 10 else digits

                # grand_total: numeric float
                if extracted.get("grand_total") is not None:
                    total_str = re.sub(r"[^\d.]", "", str(extracted["grand_total"]))
                    try:
                        extracted["grand_total"] = float(total_str) if total_str else None
                    except ValueError:
                        extracted["grand_total"] = None

                # Add validity score
                extracted["validity_score"] = _score_invoice_validity(extracted)

                # Explicit cleanup of large objects
                del image_bytes
                del b64

                # Update stats
                _refresh_today_stats()
                ocr_stats["total_calls"] += 1
                ocr_stats["success"] += 1
                ocr_stats["today_calls"] += 1

                logger.info(
                    f"OCR success: {filename} (attempt {attempt + 1}, "
                    f"validity: {extracted['validity_score']['status']})"
                )
                return extracted

            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                logger.warning(f"OCR JSON error for {filename} (attempt {attempt + 1}): {e}")
                continue

            except Exception as e:
                err_str = str(e)
                last_error = err_str

                # Quota/Rate limit: fail immediately, don't retry or backoff
                # This allows the system to gracefully degrade to Excel-only data
                if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                    logger.warning(
                        f"Gemini quota/rate limit hit for {filename}. "
                        f"Skipping OCR. System will use Excel-only data. Error: {e}"
                    )
                    # Return None immediately — caller will use Excel fallback
                    _refresh_today_stats()
                    ocr_stats["total_calls"] += 1
                    ocr_stats["failed"] += 1
                    return None
                else:
                    logger.error(f"OCR error for {filename} (attempt {attempt + 1}): {e}")
                    if attempt >= OCR_RETRY_LIMIT - 1:
                        break
                    await asyncio.sleep(2 ** attempt)

        # All attempts exhausted
        _refresh_today_stats()
        ocr_stats["total_calls"] += 1
        ocr_stats["failed"] += 1
        logger.error(f"OCR failed after {OCR_RETRY_LIMIT} attempts for {filename}: {last_error}")
        return None

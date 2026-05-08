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
    """Convert first page of PDF to PNG bytes in memory. Never writes to disk."""
    # Try PyMuPDF first (fastest, no poppler dependency)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
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
        images = pdf2image.convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=150)
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
    """
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

                # Call Gemini
                model = genai.GenerativeModel("gemini-2.5-flash")
                response = await asyncio.to_thread(
                    model.generate_content,
                    [{"mime_type": image_mime, "data": b64}, OCR_PROMPT]
                )

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

                # Explicit cleanup of large objects
                del image_bytes
                del b64

                # Update stats
                _refresh_today_stats()
                ocr_stats["total_calls"] += 1
                ocr_stats["success"] += 1
                ocr_stats["today_calls"] += 1

                logger.info(f"OCR success: {filename} (attempt {attempt + 1})")
                return extracted

            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                logger.warning(f"OCR JSON error for {filename} (attempt {attempt + 1}): {e}")
                continue

            except Exception as e:
                err_str = str(e)
                last_error = err_str

                # Rate limit: exponential backoff
                if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                    wait = min(60, (2 ** attempt) * 5)
                    logger.warning(f"Rate limit hit for {filename}. Backing off {wait}s")
                    await asyncio.sleep(wait)
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

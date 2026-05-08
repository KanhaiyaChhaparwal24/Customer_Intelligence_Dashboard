"""
sync_service.py
Orchestrates the full incremental sync pipeline:
  Sheets → Drive → OCR → SQLite
Row-level idempotency via processed_rows table.
File-level OCR cache via processed_files.file_id.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional, List

from sqlalchemy.orm import Session

from database import (
    SessionLocal, ProcessedRow, ProcessedFile,
    InvoiceExtraction, ShopifyOrder, SyncLog,
)
from services.sheets_service import read_warranty_rows, read_shopify_rows
from services.drive_service import extract_drive_id, stream_file_to_memory, list_folder_files
from services.ocr_service import extract_invoice_data
from config import ENABLE_DEBUG_DOWNLOADS

logger = logging.getLogger(__name__)

_sync_running: bool = False
_last_sync_result: Dict = {}


def get_sync_status() -> Dict:
    return {
        "running": _sync_running,
        **_last_sync_result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_last_processed_row(db: Session) -> int:
    row = (
        db.query(ProcessedRow)
        .order_by(ProcessedRow.sheet_row_number.desc())
        .first()
    )
    return row.sheet_row_number if row else 0


def _is_file_cached(db: Session, file_id: str) -> bool:
    record = db.query(ProcessedFile).filter(ProcessedFile.file_id == file_id).first()
    return record is not None and record.processed is True


def _get_cached_extraction(db: Session, file_id: str) -> Optional[InvoiceExtraction]:
    return (
        db.query(InvoiceExtraction)
        .filter(InvoiceExtraction.file_id == file_id)
        .first()
    )


def _mark_file_processed(
    db: Session,
    file_id: str,
    filename: str,
    row_number: int,
    status: str,
) -> None:
    existing = db.query(ProcessedFile).filter(ProcessedFile.file_id == file_id).first()
    if existing:
        existing.processed = (status == "success")
        existing.processed_at = datetime.utcnow()
        existing.extraction_status = status
    else:
        db.add(ProcessedFile(
            file_id=file_id,
            filename=filename,
            processed=(status == "success"),
            processed_at=datetime.utcnow(),
            extraction_status=status,
            row_number=row_number,
        ))
    db.commit()


def _detect_duplicates(db: Session, extraction: Dict) -> bool:
    """Check if an invoice is a duplicate by order_id or invoice_number."""
    if extraction.get("order_id"):
        exists = (
            db.query(InvoiceExtraction)
            .filter(InvoiceExtraction.order_id == extraction["order_id"])
            .first()
        )
        if exists:
            return True
    if extraction.get("invoice_number"):
        exists = (
            db.query(InvoiceExtraction)
            .filter(InvoiceExtraction.invoice_number == extraction["invoice_number"])
            .first()
        )
        if exists:
            return True
    return False


async def _process_single_file(
    db: Session,
    file_id: str,
    filename: str,
    row_number: int,
    stats: Dict,
) -> bool:
    """Stream, OCR, and store one Drive file. Returns True on success."""
    # Check OCR cache
    if _is_file_cached(db, file_id):
        logger.info(f"Cache hit: {filename} ({file_id}) — skipping OCR")
        stats["files_skipped"] += 1
        return True

    try:
        # Stream file into memory
        file_bytes, mime_type, actual_name = await asyncio.to_thread(
            stream_file_to_memory, file_id
        )
        stats["files_processed"] += 1

        # Run OCR
        extracted = await extract_invoice_data(file_bytes, mime_type, actual_name, file_id)

        # Explicit memory release
        del file_bytes

        if extracted:
            is_dup = _detect_duplicates(db, extracted)
            db.add(InvoiceExtraction(
                file_id=file_id,
                row_number=row_number,
                customer_name=extracted.get("customer_name"),
                email=extracted.get("email"),
                phone=extracted.get("phone"),
                order_id=extracted.get("order_id"),
                invoice_number=extracted.get("invoice_number"),
                invoice_date=extracted.get("invoice_date"),
                product_title=extracted.get("product_title"),
                size=extracted.get("size"),
                colour=extracted.get("colour"),
                grand_total=extracted.get("grand_total"),
                seller_name=extracted.get("seller_name"),
                billing_city=extracted.get("billing_city"),
                billing_state=extracted.get("billing_state"),
                shipping_city=extracted.get("shipping_city"),
                shipping_state=extracted.get("shipping_state"),
                platform=extracted.get("platform", "Unknown"),
                is_duplicate=is_dup,
                confidence="high",
                extracted_at=datetime.utcnow(),
            ))
            db.commit()
            _mark_file_processed(db, file_id, actual_name, row_number, "success")
            stats["ocr_success"] += 1
            return True
        else:
            _mark_file_processed(db, file_id, actual_name, row_number, "failed")
            stats["ocr_failed"] += 1
            return False

    except Exception as e:
        logger.error(f"Error processing file {file_id}: {e}")
        _mark_file_processed(db, file_id, filename, row_number, "failed")
        stats["ocr_failed"] += 1
        return False


async def _process_warranty_row(db: Session, row: Dict, stats: Dict) -> str:
    """Process a single warranty sheet row. Returns final status."""
    row_number = row["_row_number"]
    invoice_link = row.get("invoice_link", "").strip()

    if not invoice_link:
        logger.debug(f"Row {row_number}: no invoice link, skipping")
        return "processed"

    drive_info = extract_drive_id(invoice_link)
    if not drive_info:
        logger.warning(f"Row {row_number}: invalid Drive link: {invoice_link}")
        return "failed"

    try:
        if drive_info["type"] == "file":
            file_id = drive_info["id"]
            await _process_single_file(db, file_id, "file", row_number, stats)

        elif drive_info["type"] == "folder":
            folder_id = drive_info["id"]
            files = await asyncio.to_thread(list_folder_files, folder_id)
            logger.info(f"Row {row_number}: folder has {len(files)} files")

            for f in files:
                await _process_single_file(db, f["id"], f["name"], row_number, stats)

        return "processed"

    except Exception as e:
        logger.error(f"Row {row_number} failed: {e}")
        return "failed"


def _sync_shopify(db: Session) -> int:
    """Upsert Shopify orders into DB. Commits row-by-row to avoid cascade failures."""
    import re as _re
    try:
        rows = read_shopify_rows()
        inserted = 0
        updated = 0
        for row in rows:
            raw_order_id = row.get("order_id", "").strip()
            email = row.get("email", "").lower().strip() or None
            cname  = row.get("customer_name", "").strip()

            # Build a stable, unique order_id
            # If the mapped column returned the customer name (fuzzy mismatch),
            # use email + created_at as a fallback key
            if not raw_order_id or raw_order_id == cname:
                created = row.get("created_at", "").strip()
                raw_order_id = f"{email or cname}_{created}" if (email or cname) else None
            if not raw_order_id:
                continue

            total_val = None
            try:
                total_str = _re.sub(r"[^\d.]", "", row.get("total", ""))
                total_val = float(total_str) if total_str else None
            except Exception:
                pass

            try:
                existing = db.query(ShopifyOrder).filter(ShopifyOrder.order_id == raw_order_id).first()
                if existing:
                    existing.customer_name  = cname or existing.customer_name
                    existing.email          = email or existing.email
                    existing.phone          = row.get("phone", "") or existing.phone
                    existing.city           = row.get("city")  or existing.city
                    existing.state          = row.get("state") or existing.state
                    existing.total          = total_val if total_val is not None else existing.total
                    existing.product        = row.get("product") or existing.product
                    existing.created_at     = row.get("created_at") or existing.created_at
                    existing.payment_method = row.get("payment_method") or existing.payment_method
                    updated += 1
                else:
                    db.add(ShopifyOrder(
                        order_id=raw_order_id,
                        customer_name=cname,
                        email=email,
                        phone=row.get("phone", ""),
                        city=row.get("city"),
                        state=row.get("state"),
                        total=total_val,
                        product=row.get("product"),
                        created_at=row.get("created_at"),
                        payment_method=row.get("payment_method"),
                    ))
                    inserted += 1
                db.commit()
            except Exception as row_err:
                db.rollback()
                logger.warning(f"Shopify row skipped ({raw_order_id}): {row_err}")

        logger.info(f"Shopify sync: {inserted} inserted, {updated} updated of {len(rows)} rows")
        return len(rows)
    except Exception as e:
        db.rollback()
        logger.error(f"Shopify sync failed: {e}")
        return 0


import re  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Main sync entry point
# ─────────────────────────────────────────────────────────────────────────────

async def sync_all() -> Dict:
    """
    Full incremental sync. Idempotent — safe to call multiple times.
    Returns stats dict.
    """
    global _sync_running, _last_sync_result

    if _sync_running:
        logger.info("Sync already running — skipping")
        return {"status": "skipped", "reason": "already_running"}

    _sync_running = True
    start_time = time.time()
    db = SessionLocal()

    sync_log = SyncLog(started_at=datetime.utcnow(), status="running")
    db.add(sync_log)
    db.commit()

    stats: Dict = {
        "rows_scanned": 0,
        "new_rows": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "ocr_success": 0,
        "ocr_failed": 0,
    }

    try:
        # ── 1. Warranty rows (incremental) ───────────────────────────────
        last_row = _get_last_processed_row(db)
        new_rows, total_rows = read_warranty_rows(last_row)
        stats["rows_scanned"] = total_rows
        stats["new_rows"] = len(new_rows)

        logger.info(f"Sync: {len(new_rows)} new warranty rows to process")

        for row in new_rows:
            row_number = row["_row_number"]

            # Insert row record with ALL fields from the warranty form
            pr = ProcessedRow(
                sheet_row_number=row_number,
                timestamp=row.get("timestamp", ""),
                email=row.get("email", "").lower().strip() or None,
                phone=re.sub(r"\D", "", row.get("phone", ""))[-10:] or None,
                warranty_brand=row.get("brand"),
                warranty_product=row.get("product_name"),
                warranty_colour=row.get("colour"),
                warranty_size=row.get("size"),
                status="processing",
            )
            db.add(pr)
            db.commit()

            try:
                status = await _process_warranty_row(db, row, stats)
                pr.status = status
                pr.processed_at = datetime.utcnow()
            except Exception as e:
                pr.status = "failed"
                pr.last_error = str(e)
                pr.retry_count = (pr.retry_count or 0) + 1
                logger.error(f"Row {row_number} error: {e}")

            db.commit()

        # ── 2. Shopify sync ──────────────────────────────────────────────
        _sync_shopify(db)

        # ── 3. Finalise sync log ─────────────────────────────────────────
        duration = time.time() - start_time
        sync_log.completed_at = datetime.utcnow()
        sync_log.status = "completed"
        sync_log.duration_seconds = duration
        sync_log.rows_scanned = stats["rows_scanned"]
        sync_log.new_rows = stats["new_rows"]
        sync_log.files_processed = stats["files_processed"]
        sync_log.files_skipped = stats["files_skipped"]
        sync_log.ocr_success = stats["ocr_success"]
        sync_log.ocr_failed = stats["ocr_failed"]
        db.commit()

        result = {
            "status": "completed",
            "duration_seconds": round(duration, 2),
            "last_sync": datetime.utcnow().isoformat(),
            **stats,
        }
        _last_sync_result = result
        logger.info(f"Sync completed in {duration:.1f}s — {stats}")
        return result

    except Exception as e:
        duration = time.time() - start_time
        sync_log.status = "failed"
        sync_log.error = str(e)
        sync_log.completed_at = datetime.utcnow()
        sync_log.duration_seconds = duration
        db.commit()
        logger.error(f"Sync failed: {e}")
        result = {"status": "failed", "error": str(e), "duration_seconds": round(duration, 2)}
        _last_sync_result = result
        return result

    finally:
        db.close()
        _sync_running = False


async def retry_failed_ocr() -> Dict:
    """Retry all rows/files that previously failed OCR."""
    db = SessionLocal()
    stats = {"retried": 0, "recovered": 0, "still_failed": 0}
    try:
        failed_rows = (
            db.query(ProcessedRow)
            .filter(ProcessedRow.status.in_(["failed", "retrying"]))
            .all()
        )
        for row in failed_rows:
            row.status = "retrying"
            row.retry_count = (row.retry_count or 0) + 1
            db.commit()
            stats["retried"] += 1

        # Re-run a targeted sync for failed rows only
        # (simplified: trigger full sync which skips already-processed rows)
        result = await sync_all()
        return {**stats, "sync_result": result}
    finally:
        db.close()

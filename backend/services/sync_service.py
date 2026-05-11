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
from datetime import timedelta
from typing import Dict, Optional, List, Tuple

from sqlalchemy.orm import Session

from database import (
    SessionLocal, ProcessedRow, ProcessedFile,
    InvoiceExtraction, ShopifyOrder, SyncLog,
)
from services.sheets_service import read_warranty_rows, read_shopify_rows
from services.drive_service import extract_drive_id, stream_file_to_memory, list_folder_files
from services.ocr_service import process_invoice_orchestrated
from config import SYNC_MAX_RETRIES, OCR_RETRY_QUEUE_INTERVAL_SECONDS, OCR_QUEUE_BATCH_SIZE, OCR_RETRY_BATCH_SIZE

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
    success_statuses = ("success", "processed", "cached", "heuristic_success")
    existing = db.query(ProcessedFile).filter(ProcessedFile.file_id == file_id).first()
    if existing:
        existing.processed = (status in success_statuses)
        existing.processed_at = datetime.utcnow()
        existing.extraction_status = status
    else:
        db.add(ProcessedFile(
            file_id=file_id,
            filename=filename,
            processed=(status in success_statuses),
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
) -> Tuple[bool, str]:
    """Stream, OCR, and store one Drive file. Returns (success, status_string)."""
    try:
        # Check OCR cache
        if _is_file_cached(db, file_id):
            logger.info(f"Cache hit: {filename} ({file_id}) — skipping OCR")
            stats["files_skipped"] += 1
            return True, "cached"

        # Stream file into memory
        file_bytes, mime_type, actual_name = await asyncio.to_thread(
            stream_file_to_memory, file_id
        )
        stats["files_processed"] += 1

        result_bool, result_str = await _process_bytes_file(db, file_id, actual_name, file_bytes, mime_type, row_number, stats)
        # release memory
        try:
            del file_bytes
        except Exception:
            pass
        return result_bool, result_str

    except ValueError as ve:
        # File size limit or URL parsing error
        logger.error(f"Row {row_number}: File validation error: {ve}")
        _mark_file_processed(db, file_id, filename, row_number, "failed")
        stats["ocr_failed"] += 1
        return False, "invalid"
    except Exception as e:
        logger.error(f"Error processing file {file_id} (row {row_number}): {e}")
        _mark_file_processed(db, file_id, filename, row_number, "failed")
        stats["ocr_failed"] += 1
        return False, "failed"


async def _process_warranty_row(db: Session, row: Dict, stats: Dict) -> str:
    """
    Process a single warranty sheet row. Returns final status.
    Row-level errors are isolated and logged, but don't crash sync.
    """
    row_number = row["_row_number"]
    invoice_link = row.get("invoice_link", "").strip()

    try:
        if not invoice_link:
            logger.debug(f"Row {row_number}: no invoice link, skipping")
            return "processed"

        # 1) Drive-style link -> process via Drive
        drive_info = extract_drive_id(invoice_link)
        if drive_info:
            if drive_info["type"] == "file":
                file_id = drive_info["id"]
                ok, status_str = await _process_single_file(db, file_id, "file", row_number, stats)
                return status_str
            elif drive_info["type"] == "folder":
                folder_id = drive_info["id"]
                folder_ok = True
                final_status = "processed"
                try:
                    files = await asyncio.to_thread(list_folder_files, folder_id)
                    logger.info(f"Row {row_number}: folder has {len(files)} files")

                    for f in files:
                        file_ok, file_status = await _process_single_file(db, f["id"], f["name"], row_number, stats)
                        folder_ok = folder_ok and file_ok
                        final_status = file_status  # Last file status dictates folder status for simplicity
                except Exception as folder_err:
                    logger.error(f"Row {row_number}: Error listing folder {folder_id}: {folder_err}")
                    return "failed"

                return final_status if folder_ok else "failed"

        logger.warning(f"Row {row_number}: invalid Drive link: {invoice_link}")
        return "invalid"

    except Exception as e:
        logger.error(f"Row {row_number} processing error: {e}", exc_info=True)
        return "failed"


async def _process_bytes_file(
    db: Session,
    file_id: str,
    actual_name: str,
    file_bytes: bytes,
    mime_type: str,
    row_number: int,
    stats: Dict,
) -> Tuple[bool, str]:
    """
    Process already-read bytes: run OCR and store results. 
    On OCR failure or quota hit, create Excel-only fallback extraction.
    Shared between Drive/local flows.
    """
    try:
        # Check OCR cache
        if _is_file_cached(db, file_id):
            logger.info(f"Cache hit: {actual_name} ({file_id}) — skipping OCR")
            stats["files_skipped"] += 1
            return True, "cached"

        # Delegate to Gemini OCR Orchestrated Entry Point
        extracted, status_result = await process_invoice_orchestrated(
            db=db,
            file_bytes=file_bytes,
            mime_type=mime_type,
            actual_name=actual_name,
            file_id=file_id,
            row_number=row_number,
        )

        # Quota hit — mark for retry later, do NOT store any extraction yet
        if status_result == "retry_pending":
            logger.info(f"Row {row_number}: Gemini quota hit for {actual_name} — queued as retry_pending")
            _mark_file_processed(db, file_id, actual_name, row_number, "retry_pending")
            stats["ocr_failed"] += 1
            return False, "retry_pending"

        if not extracted:
            logger.error(f"Row {row_number}: OCR failed completely for {actual_name}")
            _mark_file_processed(db, file_id, actual_name, row_number, "failed")
            stats["ocr_failed"] += 1
            return False, "failed"

        validity = extracted.get("validity_score", {})
        validity_status = validity.get("status", "unknown")

        # Only reject genuinely invalid invoices (not heuristic/excel_only data)
        if validity_status == "invalid" and status_result != "heuristic_success":
            logger.warning(
                f"Row {row_number}: Invalid invoice ({actual_name}). "
                f"Reasons: {validity.get('reasons')}. Skipping."
            )
            _mark_file_processed(db, file_id, actual_name, row_number, "invalid")
            stats["ocr_failed"] += 1
            return False, "invalid"

        is_dup = _detect_duplicates(db, extracted)
        try:
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
                confidence=validity_status,
                extracted_at=datetime.utcnow(),
                detected_source=extracted.get("detected_source", "Unknown"),
                source_confidence=extracted.get("source_confidence", 0.0),
                attribution_method=extracted.get("detection_method", "fallback"),
                ocr_provider=extracted.get("ocr_provider", "unknown"),
                ocr_fallback_used=extracted.get("ocr_fallback_used", False),
                ocr_latency_ms=extracted.get("ocr_latency_ms", 0.0),
                ocr_attempts=extracted.get("ocr_attempts", 1),
            ))
            db.commit()
            _mark_file_processed(db, file_id, actual_name, row_number, status_result)

            if status_result == "heuristic_success":
                logger.info(f"Row {row_number}: Stored heuristic-only extraction for {actual_name}")
            else:
                logger.info(f"Row {row_number}: Stored Gemini extraction for {actual_name}")

            stats["ocr_success"] += 1
            return True, status_result
        except Exception as db_err:
            db.rollback()
            logger.error(f"Failed to store extraction for {file_id}: {db_err}")
            _mark_file_processed(db, file_id, actual_name, row_number, "failed")
            stats["ocr_failed"] += 1
            return False, "failed"

    except Exception as e:
        logger.error(f"Byte-processing error for {file_id}: {e}")
        _mark_file_processed(db, file_id, actual_name, row_number, "failed")
        stats["ocr_failed"] += 1
        return False, "failed"


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
    Full incremental sync with fault tolerance.
    - Idempotent — safe to call multiple times
    - Row-level errors isolated — one bad row doesn't crash entire sync
    - Returns stats dict with success/failure counts
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
        "rows_succeeded": 0,
        "rows_failed": 0,
    }

    try:
        # ── 1. Warranty rows (incremental, with upsert idempotency) ──────────────────────
        # Reads new rows from Warranty sheet (Tab 0)
        # For each row:
        #   1. Upsert to ProcessedRow (update if exists, insert if not)
        #   2. If invoice_link present: process via OCR (Drive file, folder, or local file)
        #   3. On OCR failure or quota: use Excel-only fallback (create extraction from form data)
        #   4. Commit with per-row fault isolation
        try:
            last_row = _get_last_processed_row(db)
            new_rows, total_rows = read_warranty_rows(last_row)
            stats["rows_scanned"] = total_rows
            stats["new_rows"] = len(new_rows)

            logger.info(f"Sync: {len(new_rows)} new warranty rows to process")

            for row in new_rows:
                row_number = row["_row_number"]

                # Upsert row record: check if already exists, update if so, insert otherwise
                pr = db.query(ProcessedRow).filter(ProcessedRow.sheet_row_number == row_number).first()
                if pr:
                    # Update existing row
                    pr.timestamp = row.get("timestamp", "")
                    pr.email = row.get("email", "").lower().strip() or None
                    pr.phone = re.sub(r"\D", "", row.get("phone", ""))[-10:] or None
                    pr.warranty_brand = row.get("brand")
                    pr.warranty_product = row.get("product_name")
                    pr.warranty_colour = row.get("colour")
                    pr.warranty_size = row.get("size")
                    # v3.0: Set status to queued for background worker
                    pr.status = "queued"
                    logger.debug(f"Row {row_number}: Updated existing record and queued for OCR")
                else:
                    # Insert new row
                    pr = ProcessedRow(
                        sheet_row_number=row_number,
                        timestamp=row.get("timestamp", ""),
                        email=row.get("email", "").lower().strip() or None,
                        phone=re.sub(r"\D", "", row.get("phone", ""))[-10:] or None,
                        warranty_brand=row.get("brand"),
                        warranty_product=row.get("product_name"),
                        warranty_colour=row.get("colour"),
                        warranty_size=row.get("size"),
                        status="queued",
                        invoice_link=row.get("invoice_link", "").strip()  # Need to store this for background worker!
                    )
                    db.add(pr)
                    logger.debug(f"Row {row_number}: Inserted new record and queued for OCR")

                try:
                    db.commit()
                    stats["rows_succeeded"] += 1
                except Exception as row_insert_err:
                    db.rollback()
                    logger.error(f"Row {row_number}: Failed to upsert: {row_insert_err}")
                    stats["rows_failed"] += 1
                    continue

                try:
                    db.commit()
                except Exception as commit_err:
                    db.rollback()
                    logger.error(f"Row {row_number}: Failed to commit status: {commit_err}")

        except Exception as warranty_batch_err:
            logger.error(f"Warranty batch processing failed: {warranty_batch_err}", exc_info=True)

        # ── 2. Shopify sync ──────────────────────────────────────────────
        try:
            _sync_shopify(db)
        except Exception as shopify_err:
            logger.error(f"Shopify sync failed: {shopify_err}", exc_info=True)

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
        sync_log.error = str(e)[:500]
        sync_log.completed_at = datetime.utcnow()
        sync_log.duration_seconds = duration
        db.commit()
        logger.error(f"Sync critical error: {e}", exc_info=True)
        result = {
            "status": "failed",
            "error": str(e),
            "duration_seconds": round(duration, 2),
        }
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
            .filter(ProcessedRow.status.in_(["failed", "retrying", "retry_pending"]))
            .all()
        )
        for row in failed_rows:
            row.status = "queued"
            row.retry_count = (row.retry_count or 0) + 1
            row.next_retry_at = None
            db.commit()
            stats["retried"] += 1

        # Re-run a targeted sync for failed rows only
        # (simplified: trigger full sync which skips already-processed rows)
        result = await sync_all()
        return {**stats, "sync_result": result}
    finally:
        db.close()


async def process_ocr_queue():
    """
    Background worker: pulls 'queued' and 'retry_pending' rows from DB.
    Processes only small batches per interval to respect Gemini free-tier limits.
    - 'queued'        → new rows, process immediately
    - 'retry_pending' → quota-hit rows, process only when cooldown has cleared
    """
    from services.ocr_service import is_quota_cooling_down, ocr_stats

    db = SessionLocal()
    try:
        run_started_at = datetime.utcnow()
        logger.info("OCR queue worker started")

        # Pick up 'queued' rows first
        queued_rows = (
            db.query(ProcessedRow)
            .filter(ProcessedRow.status == "queued")
            .order_by(ProcessedRow.sheet_row_number)
            .limit(OCR_QUEUE_BATCH_SIZE)
            .all()
        )

        # Also pick up 'retry_pending' rows, but ONLY if quota cooldown has cleared
        retry_rows = []
        if not is_quota_cooling_down():
            now = datetime.utcnow()
            retry_rows = (
                db.query(ProcessedRow)
                .filter(ProcessedRow.status == "retry_pending")
                .filter((ProcessedRow.next_retry_at.is_(None)) | (ProcessedRow.next_retry_at <= now))
                .order_by(ProcessedRow.sheet_row_number)
                .limit(OCR_RETRY_BATCH_SIZE)
                .all()
            )
            if retry_rows:
                logger.info(
                    f"Quota cooldown cleared — picking up {len(retry_rows)} retry_pending rows."
                )

        all_rows = queued_rows + retry_rows
        if not all_rows:
            ocr_stats["queue_last_run_at"] = run_started_at.isoformat()
            ocr_stats["queue_last_run_status"] = "idle"
            return

        logger.info(
            f"OCR Queue worker: {len(queued_rows)} queued + "
            f"{len(retry_rows)} retry_pending = {len(all_rows)} rows to process."
        )

        stats = {
            "files_processed": 0,
            "files_skipped":   0,
            "ocr_success":     0,
            "ocr_failed":      0,
        }

        for pr in all_rows:
            pr.status = "processing"
            pr.last_error = None
            db.commit()

            row_dict = {
                "_row_number": pr.sheet_row_number,
                "invoice_link": pr.invoice_link or "",
            }

            try:
                status = await _process_warranty_row(db, row_dict, stats)

                # Map orchestrator status to ProcessedRow status
                if status == "retry_pending":
                    retry_delay = int(ocr_stats.get("last_retry_delay_seconds") or OCR_RETRY_QUEUE_INTERVAL_SECONDS)
                    pr.status = "retry_pending"
                    pr.next_retry_at = datetime.utcnow() + timedelta(seconds=retry_delay)
                    pr.last_error = ocr_stats.get("last_error")
                elif status in ("success", "heuristic_success", "cached", "processed"):
                    pr.status = "processed"
                    pr.next_retry_at = None
                elif status == "failed" or status == "invalid":
                    pr.retry_count = (pr.retry_count or 0) + 1
                    if pr.retry_count < SYNC_MAX_RETRIES:
                        pr.status = "queued"  # allow one more try
                        pr.next_retry_at = None
                    else:
                        pr.status = "failed"
                        pr.next_retry_at = None
                else:
                    pr.status = status or "processed"

                pr.processed_at = datetime.utcnow()

            except Exception as row_err:
                pr.last_error = str(row_err)[:500]
                pr.retry_count = (pr.retry_count or 0) + 1
                pr.status = "retry_pending" if pr.retry_count < SYNC_MAX_RETRIES else "failed"
                if pr.status == "retry_pending":
                    pr.next_retry_at = datetime.utcnow() + timedelta(seconds=OCR_RETRY_QUEUE_INTERVAL_SECONDS)
                logger.error(
                    f"Row {pr.sheet_row_number} queue exception: {row_err}", exc_info=True
                )

            db.commit()
        ocr_stats["queue_last_run_at"] = run_started_at.isoformat()
        ocr_stats["queue_last_run_status"] = "completed"
        ocr_stats["queue_last_run_count"] = len(all_rows)

    finally:
        db.close()

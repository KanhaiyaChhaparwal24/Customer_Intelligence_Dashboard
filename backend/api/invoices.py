import asyncio
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from database import get_db, ProcessedFile, ProcessedRow
from services.sync_service import sync_all, retry_failed_ocr, get_sync_status
from services.drive_service import stream_file_to_memory
from services.ocr_service import extract_invoice_data
from scheduler import get_sync_state

router = APIRouter(tags=["sync & invoices"])


# ── Sync controls ─────────────────────────────────────────────────────────────

@router.get("/sync/status")
def sync_status():
    """
    Get current sync status including:
    - is_running: bool
    - elapsed_seconds: float (if running)
    - status: "running" | "completed" | "failed" | "idle"
    - last_result: dict (if completed)
    """
    scheduler_state = get_sync_state()
    service_state = get_sync_status()
    
    # Merge both states
    return {
        **scheduler_state,
        "service_stats": service_state,
    }


@router.post("/sync/trigger")
async def trigger_sync(background_tasks: BackgroundTasks):
    """Trigger a full incremental sync in the background."""
    background_tasks.add_task(sync_all)
    return {"message": "Sync triggered", "status": "started"}


@router.post("/sync/retry-failed")
async def retry_failed(background_tasks: BackgroundTasks):
    """Retry all failed OCR rows in the background."""
    background_tasks.add_task(retry_failed_ocr)
    return {"message": "Retry triggered"}


# ── Invoice controls ──────────────────────────────────────────────────────────

@router.post("/invoices/{file_id}/retry")
async def retry_invoice(file_id: str, db: Session = Depends(get_db)):
    """Retry OCR for a specific Drive file ID."""
    record = db.query(ProcessedFile).filter(ProcessedFile.file_id == file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="File not found in cache")

    # Reset the file cache so sync will reprocess it
    record.processed = False
    record.extraction_status = "retrying"
    db.commit()

    # Trigger targeted reprocess
    try:
        file_bytes, mime_type, filename = await asyncio.to_thread(
            stream_file_to_memory, file_id
        )
        extracted = await extract_invoice_data(file_bytes, mime_type, filename, file_id)
        del file_bytes
        if extracted:
            record.processed = True
            record.extraction_status = "success"
            db.commit()
            return {"status": "success", "data": extracted}
        else:
            record.extraction_status = "failed"
            db.commit()
            return {"status": "failed", "message": "OCR returned no data"}
    except Exception as e:
        record.extraction_status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/invoices/row/{row_number}/reprocess")
def reprocess_row(row_number: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Reset a specific row so it will be reprocessed in the next sync."""
    row = db.query(ProcessedRow).filter(ProcessedRow.sheet_row_number == row_number).first()
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")
    row.status = "pending"
    row.retry_count = (row.retry_count or 0) + 1
    db.commit()
    background_tasks.add_task(sync_all)
    return {"message": f"Row {row_number} queued for reprocessing"}


# ── Export CSV ────────────────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse
import csv
import io
from services.analytics_service import (
    get_converted_customers, get_flipkart_only, get_d2c_only, get_all_customers
)


@router.get("/export/csv")
def export_csv(
    type: str = "all",
    db: Session = Depends(get_db),
):
    """Export customer data as CSV. type: all | converted | flipkart | d2c"""
    if type == "converted":
        data = get_converted_customers(db)
    elif type == "flipkart":
        data = get_flipkart_only(db)
    elif type == "d2c":
        data = get_d2c_only(db)
    else:
        data = get_all_customers(db)

    if not data:
        raise HTTPException(status_code=404, detail="No data to export")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(data[0].keys()), extrasaction="ignore")
    writer.writeheader()
    for row in data:
        # Flatten lists
        flat = {k: (", ".join(v) if isinstance(v, list) else v) for k, v in row.items()}
        writer.writerow(flat)

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=customers_{type}.csv"},
    )

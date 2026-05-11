from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from services import analytics_service as analytics
from services.ocr_service import ocr_stats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/kpis")
def kpis(db: Session = Depends(get_db)):
    return analytics.get_kpis(db)


@router.get("/conversions")
def conversions(db: Session = Depends(get_db)):
    return {"data": analytics.get_converted_customers(db)}


@router.get("/customers")
def customers(
    source: str = Query(None, description="all|converted|marketplace|flipkart|direct_d2c|probable_d2c|d2c|unknown"),
    search: str = Query(None),
    city: str = Query(None),
    state: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    if source == "converted":
        data = analytics.get_converted_customers(db)
    elif source == "marketplace" or source == "flipkart":
        data = analytics.get_marketplace_only(db)
    elif source == "direct_d2c":
        data = analytics.get_direct_d2c(db)
    elif source == "probable_d2c":
        data = analytics.get_probable_d2c(db)
    elif source == "d2c":
        data = analytics.get_d2c_only(db)
    elif source == "unknown":
        data = analytics.get_unknown_attribution(db)
    else:
        data = analytics.get_all_customers(db)

    # Apply search filter
    if search:
        s = search.lower()
        data = [
            c for c in data
            if s in (c.get("email") or "").lower()
            or s in (c.get("phone") or "")
            or s in (c.get("customer_name") or "").lower()
        ]

    if city:
        data = [c for c in data if (c.get("city") or "").lower() == city.lower()]
    if state:
        data = [c for c in data if (c.get("state") or "").lower() == state.lower()]

    total = len(data)
    start = (page - 1) * per_page
    paginated = data[start: start + per_page]
    return {"total": total, "page": page, "per_page": per_page, "data": paginated}


@router.get("/products")
def products(db: Session = Depends(get_db)):
    return {"data": analytics.get_product_analytics(db)}


@router.get("/cities")
def cities(db: Session = Depends(get_db)):
    return {"data": analytics.get_city_analytics(db)}


@router.get("/revenue")
def revenue(db: Session = Depends(get_db)):
    return {
        "monthly": analytics.get_revenue_by_month(db),
        "registrations": analytics.get_registrations_by_month(db),
    }


@router.get("/sizes")
def sizes(db: Session = Depends(get_db)):
    return {"data": analytics.get_size_trends(db)}


@router.get("/colours")
def colours(db: Session = Depends(get_db)):
    return {"data": analytics.get_colour_trends(db)}


@router.get("/payments")
def payments(db: Session = Depends(get_db)):
    return {"data": analytics.get_payment_methods(db)}


@router.get("/journey/{email}")
def journey(email: str, db: Session = Depends(get_db)):
    return analytics.get_customer_journey(db, email)


@router.get("/invoices")
def invoices(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return analytics.get_invoices_list(db, page, per_page)


@router.get("/attribution-insights")
def attribution_insights(db: Session = Depends(get_db)):
    return analytics.get_attribution_insights(db)


@router.get("/ocr-metrics")
def ocr_metrics(db: Session = Depends(get_db)):
    from database import ProcessedRow, InvoiceExtraction, ProcessedFile
    from sqlalchemy import func

    provider_rows = db.query(
        InvoiceExtraction.ocr_provider,
        func.count(InvoiceExtraction.id)
    ).group_by(InvoiceExtraction.ocr_provider).all()
    provider_stats = {provider or "unknown": count for provider, count in provider_rows}

    source_rows = db.query(
        InvoiceExtraction.detected_source,
        func.count(InvoiceExtraction.id)
    ).group_by(InvoiceExtraction.detected_source).all()
    source_stats = {source or "Unknown": count for source, count in source_rows}

    queue_rows = db.query(
        ProcessedRow.status,
        func.count(ProcessedRow.id)
    ).group_by(ProcessedRow.status).all()
    queue_stats = {status or "unknown": count for status, count in queue_rows}

    avg_latency = db.query(func.avg(InvoiceExtraction.ocr_latency_ms)).scalar() or 0.0

    gemini_success = provider_stats.get("gemini", 0)
    heuristic_attribution = provider_stats.get("heuristic", 0)
    memory_cache_hits = provider_stats.get("memory_cache", 0)
    retry_pending = queue_stats.get("retry_pending", 0)
    queue_pending = queue_stats.get("queued", 0)
    queue_processing = queue_stats.get("processing", 0)
    queue_failed = queue_stats.get("failed", 0)
    ocr_skipped = db.query(ProcessedFile).filter(ProcessedFile.extraction_status == "cached").count()
    gemini_failed = db.query(ProcessedFile).filter(ProcessedFile.extraction_status == "failed").count()
    unknown_attribution = source_stats.get("Unknown", 0)

    total_gemini_outcomes = gemini_success + gemini_failed
    success_rate = round((gemini_success / total_gemini_outcomes) * 100, 1) if total_gemini_outcomes else 0.0

    return {
        "gemini_success": gemini_success,
        "gemini_failed": gemini_failed,
        "retry_pending": retry_pending,
        "ocr_skipped": ocr_skipped,
        "heuristic_attribution": heuristic_attribution,
        "unknown_attribution": unknown_attribution,
        "queue_pending": queue_pending,
        "queue_processing": queue_processing,
        "queue_failed": queue_failed,
        "memory_cache_hits": memory_cache_hits,
        "avg_latency_ms": round(avg_latency, 2),
        "gemini_success_rate": success_rate,
        "gemini_calls_today": ocr_stats.get("today_calls", 0),
        "queue_retry_pending": retry_pending,
        "queue_size": queue_pending + queue_processing + retry_pending,
        "queue_last_run_at": ocr_stats.get("queue_last_run_at"),
        "queue_last_run_status": ocr_stats.get("queue_last_run_status"),
    }

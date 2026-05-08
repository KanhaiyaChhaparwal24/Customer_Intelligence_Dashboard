from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from services import analytics_service as analytics

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/kpis")
def kpis(db: Session = Depends(get_db)):
    return analytics.get_kpis(db)


@router.get("/conversions")
def conversions(db: Session = Depends(get_db)):
    return {"data": analytics.get_converted_customers(db)}


@router.get("/customers")
def customers(
    source: str = Query(None, description="all|converted|flipkart|d2c"),
    search: str = Query(None),
    city: str = Query(None),
    state: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    if source == "converted":
        data = analytics.get_converted_customers(db)
    elif source == "flipkart":
        data = analytics.get_flipkart_only(db)
    elif source == "d2c":
        data = analytics.get_d2c_only(db)
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

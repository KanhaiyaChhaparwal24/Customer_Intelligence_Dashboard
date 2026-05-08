import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Integer, Float,
    Boolean, DateTime, Text, Index, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DATABASE_URL

# Resolve absolute path for SQLite
_db_path = DATABASE_URL.replace("sqlite:///", "")
_db_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), _db_path))
os.makedirs(os.path.dirname(_db_abs), exist_ok=True)
_resolved_url = f"sqlite:///{_db_abs}"

engine = create_engine(
    _resolved_url,
    connect_args={"check_same_thread": False},
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: processed_rows
# Tracks which warranty sheet rows have been handled (idempotency key = row #)
# ─────────────────────────────────────────────────────────────────────────────
class ProcessedRow(Base):
    __tablename__ = "processed_rows"

    id               = Column(Integer, primary_key=True, index=True)
    sheet_row_number = Column(Integer, unique=True, nullable=False)
    timestamp        = Column(String)
    # Fields filled by the CUSTOMER in the warranty registration form
    email            = Column(String)   # directly from sheet column "Email"
    phone            = Column(String)   # directly from sheet column "Phone"
    warranty_brand   = Column(String)
    warranty_product = Column(String)
    warranty_colour  = Column(String)
    warranty_size    = Column(String)
    # Processing state
    status           = Column(String, default="pending")  # pending/processing/processed/failed/retrying
    processed_at     = Column(DateTime)
    retry_count      = Column(Integer, default=0)
    last_error       = Column(Text)

    __table_args__ = (
        Index("ix_processed_rows_email",  "email"),
        Index("ix_processed_rows_phone",  "phone"),
        Index("ix_processed_rows_status", "status"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: processed_files
# Drive file_id → permanent OCR cache key
# ─────────────────────────────────────────────────────────────────────────────
class ProcessedFile(Base):
    __tablename__ = "processed_files"

    id               = Column(Integer, primary_key=True, index=True)
    file_id          = Column(String, unique=True, nullable=False)
    filename         = Column(String)
    processed        = Column(Boolean, default=False)
    processed_at     = Column(DateTime)
    extraction_status = Column(String)   # success / failed
    row_number       = Column(Integer)

    __table_args__ = (
        Index("ix_processed_files_file_id", "file_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: invoice_extractions
# Structured JSON extracted by Gemini OCR from each invoice file
# ─────────────────────────────────────────────────────────────────────────────
class InvoiceExtraction(Base):
    __tablename__ = "invoice_extractions"

    id             = Column(Integer, primary_key=True, index=True)
    file_id        = Column(String)
    row_number     = Column(Integer)
    customer_name  = Column(String)
    email          = Column(String)
    phone          = Column(String)
    order_id       = Column(String)
    invoice_number = Column(String)
    invoice_date   = Column(String)
    product_title  = Column(String)
    size           = Column(String)
    colour         = Column(String)
    grand_total    = Column(Float)
    seller_name    = Column(String)
    billing_city   = Column(String)
    billing_state  = Column(String)
    shipping_city  = Column(String)
    shipping_state = Column(String)
    platform       = Column(String)
    is_duplicate   = Column(Boolean, default=False)
    confidence     = Column(String, default="high")   # high / medium / low
    extracted_at   = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_inv_email",          "email"),
        Index("ix_inv_phone",          "phone"),
        Index("ix_inv_order_id",       "order_id"),
        Index("ix_inv_invoice_number", "invoice_number"),
        Index("ix_inv_file_id",        "file_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: shopify_orders
# D2C Shopify orders from Sheet Tab 2
# ─────────────────────────────────────────────────────────────────────────────
class ShopifyOrder(Base):
    __tablename__ = "shopify_orders"

    id             = Column(Integer, primary_key=True, index=True)
    order_id       = Column(String, unique=True)
    customer_name  = Column(String)
    email          = Column(String)
    phone          = Column(String)
    city           = Column(String)
    state          = Column(String)
    total          = Column(Float)
    product        = Column(String)
    created_at     = Column(String)
    payment_method = Column(String)

    __table_args__ = (
        Index("ix_shopify_email",    "email"),
        Index("ix_shopify_phone",    "phone"),
        Index("ix_shopify_order_id", "order_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TABLE: sync_logs
# Audit log of every scheduler run
# ─────────────────────────────────────────────────────────────────────────────
class SyncLog(Base):
    __tablename__ = "sync_logs"

    id               = Column(Integer, primary_key=True, index=True)
    started_at       = Column(DateTime, default=datetime.utcnow)
    completed_at     = Column(DateTime)
    rows_scanned     = Column(Integer, default=0)
    new_rows         = Column(Integer, default=0)
    files_processed  = Column(Integer, default=0)
    files_skipped    = Column(Integer, default=0)
    ocr_success      = Column(Integer, default=0)
    ocr_failed       = Column(Integer, default=0)
    duration_seconds = Column(Float)
    status           = Column(String)   # running / completed / failed
    error            = Column(Text)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

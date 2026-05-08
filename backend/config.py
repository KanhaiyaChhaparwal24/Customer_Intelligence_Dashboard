import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Gemini ─────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Google ──────────────────────────────────────────────────────────────────
GOOGLE_SHEET_NAME: str = os.getenv(
    "GOOGLE_SHEET_NAME", "Customer Data Sources Sample Structure"
)
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
GOOGLE_CREDENTIALS_FILE: str = os.path.join(_base, "credentials.json")
GOOGLE_TOKEN_FILE: str = os.path.join(_base, "token.json")

# ── Database ────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///../database/intelligence.db")

# ── Scheduler ───────────────────────────────────────────────────────────────
SYNC_INTERVAL_MINUTES: int = int(os.getenv("SYNC_INTERVAL_MINUTES", "30"))
SYNC_TIMEOUT_SECONDS: int = int(os.getenv("SYNC_TIMEOUT_SECONDS", "3600"))  # 1 hour max per sync
SYNC_MAX_RETRIES: int = int(os.getenv("SYNC_MAX_RETRIES", "3"))

# ── OCR ─────────────────────────────────────────────────────────────────────
MAX_OCR_CONCURRENCY: int = int(os.getenv("MAX_OCR_CONCURRENCY", "3"))
OCR_RETRY_LIMIT: int = int(os.getenv("OCR_RETRY_LIMIT", "3"))
OCR_DELAY_SECONDS: float = float(os.getenv("OCR_DELAY_SECONDS", "1.0"))
OCR_TIMEOUT_SECONDS: int = int(os.getenv("OCR_TIMEOUT_SECONDS", "30"))  # Max time per Gemini call
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))  # Max file size in MB
MAX_PDF_PAGES: int = int(os.getenv("MAX_PDF_PAGES", "5"))  # Process first N pages only
ENABLE_DEBUG_DOWNLOADS: bool = os.getenv("ENABLE_DEBUG_DOWNLOADS", "false").lower() == "true"

# ── API ──────────────────────────────────────────────────────────────────────
BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

# ── Fuzzy Column Mapping ─────────────────────────────────────────────────────
# Maps logical field names → list of possible header names in Google Sheets
COLUMN_MAPPING: dict = {
    # ── Warranty / Flipkart registration tab ───────────────────────────────
    # Exact headers: Timestamp  Email  Phone  Brand  Product Name  Colour  Size  Invoice Upload
    "invoice_link": ["Invoice Upload", "Invoice Link", "Drive Link", "Drive URL", "Invoice", "Upload"],
    "email":        ["Email", "Email Address", "Customer Email", "E-mail", "Mail"],
    "phone":        ["Phone", "Phone Number", "Mobile", "Mobile Number", "Contact", "WhatsApp"],
    "brand":        ["Brand", "Brand Name", "Product Brand"],
    "product_name": ["Product Name", "Product", "Item", "Item Name"],
    "colour":       ["Colour", "Color", "Product Color", "Product Colour", "Shade"],
    "size":         ["Size", "Product Size", "Bag Size"],
    "timestamp":    ["Timestamp", "Date", "Registration Date", "Submission Time"],

    # ── Shopify export tab ─────────────────────────────────────────────────
    # Exact headers from Shopify CSV export format
    "order_id":       ["Id", "Order ID", "Order #", "Order Number", "Name"],
    "customer_name":  ["Billing Name", "Name", "Customer Name", "Full Name"],
    "email":          ["Email"],          # same key — sheets_service handles per-tab
    "phone":          ["Billing Phone", "Shipping Phone", "Phone"],
    "city":           ["Billing City", "Shipping City", "City"],
    "state":          ["Billing Province Name", "Billing Province", "Shipping Province Name",
                       "Shipping Province", "State"],
    "total":          ["Total", "Subtotal", "Grand Total", "Order Total", "Amount"],
    "product":        ["Lineitem name", "Product", "Line Item", "Items", "Products"],
    "created_at":     ["Paid at", "Created at", "Order Date", "Date"],
    "payment_method": ["Payment Method", "Payment Gateway"],
}

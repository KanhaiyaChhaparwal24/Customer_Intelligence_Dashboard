"""
main.py — FastAPI application entry point
"""
import logging
import sys
import os

# Ensure backend directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from config import CORS_ORIGINS, BACKEND_PORT
from database import create_tables, engine
from scheduler import start_scheduler, stop_scheduler
from api.dashboard import router as dashboard_router
from api.invoices import router as invoices_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

def run_startup_validation():
    """Validate backend environment on boot."""
    print("\n" + "="*50)
    print(" CUSTOMER INTELLIGENCE DASHBOARD — STARTUP ")
    print("="*50)
    
    # 1. Gemini Check
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        print("[!] ERROR: GEMINI_API_KEY not found in .env")
    else:
        print(f"[*] Gemini API: Configured (Key: {GEMINI_API_KEY[:4]}...{GEMINI_API_KEY[-4:]})")
    
    # 2. Pipeline Mode
    print("[*] OCR Mode: Gemini-Only (High Precision)")
    print("[*] Fallback: Heuristic Data Linking (Enabled)")
    
    # 3. Dependencies check
    import fitz
    print(f"[*] PDF Support: Active (PyMuPDF {fitz.__version__})")
    
    # 4. DB check
    from database import engine
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[*] Database: Connected (SQLite)")
    except Exception as e:
        print(f"[!] Database ERROR: {e}")

    print("="*50 + "\n")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    run_startup_validation()
    logger.info("Creating database tables...")
    create_tables()
    logger.info("Starting APScheduler...")
    start_scheduler()
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Stopping scheduler...")
    stop_scheduler()


app = FastAPI(
    title="Customer Intelligence Dashboard API",
    description="Luggage brand ecommerce analytics — Flipkart + D2C unified intelligence",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(dashboard_router)
app.include_router(invoices_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "Customer Intelligence Dashboard API", "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=BACKEND_PORT, reload=True)

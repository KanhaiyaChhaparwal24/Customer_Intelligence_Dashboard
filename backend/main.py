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

from config import CORS_ORIGINS, BACKEND_PORT
from database import create_tables
from scheduler import start_scheduler, stop_scheduler
from api.dashboard import router as dashboard_router
from api.invoices import router as invoices_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
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

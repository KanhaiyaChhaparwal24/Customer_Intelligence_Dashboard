import asyncio
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

from database import create_tables, SessionLocal, ProcessedRow, ProcessedFile, InvoiceExtraction, ShopifyOrder, SyncLog
from services.sync_service import sync_all


def reset_data() -> None:
    db = SessionLocal()
    try:
        for model in (ProcessedRow, ProcessedFile, InvoiceExtraction, ShopifyOrder, SyncLog):
            deleted = db.query(model).delete(synchronize_session=False)
            logging.info("Deleted %s rows from %s", deleted, model.__tablename__)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_tables()
    reset_data()
    result = asyncio.run(sync_all())
    print(json.dumps(result, indent=2))

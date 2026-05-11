import os
import json
from database import get_db, SessionLocal
from services.analytics_service import get_kpis

def run_verification():
    print("Starting Multi-Source Attribution Verification...\n")
    db = SessionLocal()
    try:
        kpis = get_kpis(db)
        print("=== Attribution KPIs ===")
        print(f"Total Marketplace Buyers:   {kpis.get('marketplace_buyers', 0)}")
        print(f"Direct D2C Customers:       {kpis.get('direct_d2c_customers', 0)}")
        print(f"Converted to D2C:           {kpis.get('converted_customers', 0)}")
        print(f"Probable D2C (Date-match):  {kpis.get('probable_d2c_count', 0)}")
        print(f"Unknown Source:             {kpis.get('unknown_attribution_count', 0)}")
        print(f"OCR Failed:                 {kpis.get('ocr_failed_count', 0)}")
        print(f"Marketplace -> D2C Rate:    {kpis.get('marketplace_to_d2c_rate', 0)}%")
        print("\nVerification completed successfully.")
    except Exception as e:
        print(f"Error during verification: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_verification()

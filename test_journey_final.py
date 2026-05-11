import sys
sys.path.insert(0, 'backend')
from database import SessionLocal
from services.analytics_service import get_customer_journey

db = SessionLocal()

# Test customer with warranty + flipkart purchase
journey = get_customer_journey(db, 'vishnujith.p.s@gmail.com')
print(f"Customer: {journey['email']}")
print(f"Events: {len(journey['events'])}")
for e in journey['events']:
    print(f"  - {e['type']}: {e['product']} ({e['date']})")

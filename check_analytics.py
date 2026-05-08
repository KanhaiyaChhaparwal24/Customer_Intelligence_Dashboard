import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backend')
from database import SessionLocal
from services.analytics_service import get_kpis, get_converted_customers, get_flipkart_only

db = SessionLocal()

print('=== KPIs ===')
kpis = get_kpis(db)
for k, v in kpis.items():
    print('  %s: %s' % (k, v))

print()
print('=== CONVERTED CUSTOMERS ===')
converted = get_converted_customers(db)
print('Count:', len(converted))
for c in converted:
    print('  email=%s | phone=%s | product=%s | size=%s | colour=%s | confidence=%s | d2c_spend=%s | city=%s' % (
        c.get('email'), c.get('phone'), c.get('product'), c.get('size'),
        c.get('colour'), c.get('match_confidence'), c.get('d2c_spend'), c.get('city')
    ))

print()
print('=== FLIPKART ONLY (not yet converted) ===')
fk_only = get_flipkart_only(db)
print('Count:', len(fk_only))
for c in fk_only:
    print('  email=%s | phone=%s | product=%s | size=%s | colour=%s | city=%s' % (
        c.get('email'), c.get('phone'), c.get('product'), c.get('size'), c.get('colour'), c.get('city')
    ))

db.close()

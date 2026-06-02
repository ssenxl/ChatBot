"""Script ตรวจสอบ item ที่ไม่มี Master.Group ใน BookingMaster"""
from powerbi_connector import fetch_table
from collections import defaultdict

print("กำลังดึงข้อมูล BookingMaster...")
result = fetch_table('BookingMaster')
rows = result.get('data', [])
print(f"ได้ {len(rows)} rows\n")

no_group = []
for r in rows:
    group = str(r.get('Master.Group', '') or '').strip()
    if not group:
        item = r.get('ITEM_CODE', '')
        mc = r.get('MC_CODE', r.get('Master.MC', ''))
        yw = r.get('YW', '')
        no_group.append({'item': item, 'mc': mc, 'yw': yw, 'row': r})

if not no_group:
    print("ไม่มี item ที่ขาด Group")
else:
    print(f"พบ {len(no_group)} rows ที่ไม่มี Master.Group\n")
    # สรุปตาม item
    by_item = defaultdict(list)
    for x in no_group:
        by_item[x['item']].append(x)

    print(f"Item ที่ไม่มี Group ({len(by_item)} item):")
    for item, entries in sorted(by_item.items()):
        mc_vals = sorted(set(str(e['mc']) for e in entries))
        yws = sorted(set(str(e['yw']) for e in entries))
        print(f"  {item:30s}  MC={mc_vals}  weeks={yws[:3]}{'...' if len(yws)>3 else ''}")

    # ดู keys ทั้งหมดที่มีใน row ตัวอย่าง
    print("\n--- ตัวอย่าง keys ใน row ที่ไม่มี group ---")
    sample = no_group[0]['row']
    for k, v in sample.items():
        print(f"  {k}: {v}")

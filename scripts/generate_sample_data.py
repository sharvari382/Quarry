"""Generate the sample datasets in sample_data/ (deterministic, seed 42).

sales.csv      ~6k order lines, Jan 2024 to Dec 2025, 5 regions, seasonality, growth,
               plus planted anomalies: a bulk order spike, a refund-like negative,
               a pricing error, and a month where one region collapses.
customers.csv  customers with segment and signup date (joins on customer_id).
products.csv   product catalogue with category and unit cost (joins on product_id).
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
OUT = Path(__file__).resolve().parents[1] / "sample_data"
OUT.mkdir(exist_ok=True)

REGIONS = {"North": 1.25, "South": 0.9, "East": 1.05, "West": 1.15, "Central": 0.7}
PRODUCTS = [
    ("P-100", "Ledger Pro Subscription", "Software", 49.0, 12.0),
    ("P-101", "Ledger Lite Subscription", "Software", 19.0, 4.0),
    ("P-200", "Thermal Receipt Printer", "Hardware", 189.0, 120.0),
    ("P-201", "Barcode Scanner", "Hardware", 95.0, 58.0),
    ("P-202", "Card Terminal", "Hardware", 249.0, 170.0),
    ("P-300", "Onboarding Package", "Services", 399.0, 210.0),
    ("P-301", "Priority Support (annual)", "Services", 299.0, 90.0),
    ("P-400", "Receipt Paper (box of 50)", "Consumables", 24.0, 11.0),
    ("P-401", "Cash Drawer", "Hardware", 129.0, 85.0),
    ("P-402", "Label Rolls (pack)", "Consumables", 15.0, 6.0),
]
# Relative popularity; Label Rolls and Cash Drawer are the underperformers.
WEIGHTS = [16, 14, 9, 8, 7, 5, 6, 12, 2, 1.5]
SEGMENTS = ["SMB", "Mid-Market", "Enterprise"]
FIRST = ["Asha", "Ben", "Chen", "Diya", "Elena", "Farid", "Grace", "Hiro", "Isla", "Jonas", "Kavya", "Liam",
         "Maya", "Noah", "Omar", "Priya", "Quinn", "Ravi", "Sara", "Tom"]
LAST = ["Retail", "Foods", "Pharmacy", "Hardware", "Books", "Cafe", "Outfitters", "Market", "Studio", "Supply"]


def customers() -> list[dict]:
    rows, used = [], set()
    for i in range(1, 161):
        while True:
            name = f"{random.choice(FIRST)}'s {random.choice(LAST)}"
            if name not in used:
                used.add(name)
                break
        seg = random.choices(SEGMENTS, weights=[70, 22, 8])[0]
        rows.append({
            "customer_id": f"C{i:04d}",
            "customer_name": name,
            "segment": seg,
            "region": random.choices(list(REGIONS), weights=[24, 18, 22, 22, 14])[0],
            "signup_date": (date(2023, 1, 1) + timedelta(days=random.randint(0, 900))).isoformat(),
        })
    return rows


def sales(custs: list[dict]) -> list[dict]:
    rows = []
    order_id = 10_000
    start = date(2024, 1, 1)
    seg_mult = {"SMB": 1, "Mid-Market": 3, "Enterprise": 8}
    for day in range(731):
        d = start + timedelta(days=day)
        growth = 1 + day / 731 * 0.35
        season = {11: 1.35, 12: 1.5, 1: 0.8, 2: 0.85, 7: 0.9}.get(d.month, 1.0)
        weekday = 0.55 if d.weekday() >= 5 else 1.0
        n = max(1, int(random.gauss(8, 2) * growth * season * weekday))
        for _ in range(n):
            c = random.choice(custs)
            if d < date.fromisoformat(c["signup_date"]) - timedelta(days=400):
                continue
            region = c["region"]
            if random.random() > REGIONS[region] / 1.25:
                continue  # regional demand differences (North strongest, Central weakest)
            if region == "Central" and d.year == 2025 and d.month == 6 and random.random() < 0.85:
                continue  # planted: Central region collapses in June 2025
            p = random.choices(PRODUCTS, weights=WEIGHTS)[0]
            qty = max(1, int(random.expovariate(1 / (1.5 * seg_mult[c["segment"]]))) + 1)
            price = p[3] * random.uniform(0.92, 1.0) * (1 if c["segment"] == "SMB" else 0.95)
            order_id += 1
            rows.append({
                "order_id": f"SO-{order_id}", "order_date": d.isoformat(), "customer_id": c["customer_id"],
                "product_id": p[0], "region": region, "sales_channel": random.choices(
                    ["Online", "Partner", "Direct"], weights=[55, 25, 20])[0],
                "quantity": qty, "unit_price": round(price, 2),
                "discount_pct": random.choice([0, 0, 0, 5, 10, 15]),
            })
            rows[-1]["revenue"] = round(qty * rows[-1]["unit_price"] * (1 - rows[-1]["discount_pct"] / 100), 2)

    # Planted anomalies
    big = next(r for r in rows if r["order_date"] >= "2025-03-14" and r["product_id"] == "P-202")
    big.update(quantity=400, revenue=round(400 * big["unit_price"], 2))  # bulk order spike
    neg = next(r for r in rows if r["order_date"] >= "2024-09-02")
    neg.update(quantity=-3, revenue=round(-3 * neg["unit_price"], 2))  # return booked as a sale
    typo = next(r for r in rows if r["order_date"] >= "2025-08-21" and r["product_id"] == "P-400")
    typo.update(unit_price=2400.0, revenue=round(typo["quantity"] * 2400.0, 2))  # price typo (24 -> 2400)
    return rows


def write(name: str, rows: list[dict]) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {name}: {len(rows)} rows")


if __name__ == "__main__":
    custs = customers()
    write("customers.csv", custs)
    write("sales.csv", sales(custs))
    write("products.csv", [{"product_id": p[0], "product_name": p[1], "category": p[2], "list_price": p[3],
                            "unit_cost": p[4]} for p in PRODUCTS])

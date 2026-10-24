"""Tiny fake Olist CSVs with the real headers. TEST DATA ONLY, not Olist data.

Lets the loader and example queries be tested without the Kaggle download.
"""
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

FMT = "%Y-%m-%d %H:%M:%S"
STATES = ["SP", "RJ", "MG", "BA"]
CATS = [("beleza_saude", "health_beauty"), ("informatica_acessorios", "computers_accessories"),
        ("esporte_lazer", "sports_leisure")]


def _write(path: Path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_csvs(d: Path, n_orders: int = 300, seed: int = 1) -> None:
    rng = random.Random(seed)
    d.mkdir(parents=True, exist_ok=True)
    _write(d / "product_category_name_translation.csv", ["product_category_name", "product_category_name_english"], CATS)
    sellers = [(f"s{i}", 1000 + i, "city", rng.choice(STATES)) for i in range(5)]
    _write(d / "olist_sellers_dataset.csv", ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"], sellers)
    products = [(f"p{i}", rng.choice(CATS)[0], 30, 300, 2, 500, 20, 10, 15) for i in range(12)]
    _write(d / "olist_products_dataset.csv",
           ["product_id", "product_category_name", "product_name_lenght", "product_description_lenght",
            "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"],
           products)
    customers, orders, items, pays, reviews = [], [], [], [], []
    for i in range(n_orders):
        cid, oid = f"c{i}", f"o{i}"
        customers.append((cid, f"u{i % 250}", 2000 + i % 40, "city", rng.choice(STATES)))
        bought = datetime(2017, 1, 1) + timedelta(days=rng.randint(0, 600), hours=rng.randint(0, 23))
        status = rng.choices(["delivered", "canceled", "shipped", "unavailable"], [90, 5, 3, 2])[0]
        est = bought + timedelta(days=rng.randint(8, 25))
        delivered = ""
        if status == "delivered":
            delivered = (est + timedelta(days=rng.randint(-8, 10))).strftime(FMT)
        orders.append((oid, cid, status, bought.strftime(FMT), bought.strftime(FMT), "", delivered, est.strftime(FMT)))
        total = 0.0
        for k in range(1, rng.randint(1, 3) + 1):
            price, freight = round(rng.uniform(10, 200), 2), round(rng.uniform(5, 30), 2)
            total += price + freight
            items.append((oid, k, rng.choice(products)[0], rng.choice(sellers)[0],
                          (bought + timedelta(days=3)).strftime(FMT), price, freight))
        pays.append((oid, 1, rng.choice(["credit_card", "boleto", "voucher", "debit_card"]), 1, round(total, 2)))
        if status == "delivered":
            late = delivered > est.strftime(FMT)
            score = rng.choice([1, 1, 2, 3]) if late else rng.choice([3, 4, 5, 5])
            reviews.append((f"r{i}", oid, score, "", "", bought.strftime(FMT), bought.strftime(FMT)))
    _write(d / "olist_customers_dataset.csv",
           ["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"], customers)
    _write(d / "olist_orders_dataset.csv",
           ["order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at",
            "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"], orders)
    _write(d / "olist_order_items_dataset.csv",
           ["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"], items)
    _write(d / "olist_order_payments_dataset.csv",
           ["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"], pays)
    _write(d / "olist_order_reviews_dataset.csv",
           ["review_id", "order_id", "review_score", "review_comment_title", "review_comment_message",
            "review_creation_date", "review_answer_timestamp"], reviews)
    _write(d / "olist_geolocation_dataset.csv",
           ["geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng", "geolocation_city", "geolocation_state"],
           [(2000 + i, -23.5, -46.6, "city", "SP") for i in range(40)])

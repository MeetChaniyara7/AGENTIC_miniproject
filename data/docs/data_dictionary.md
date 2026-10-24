# Data Dictionary

This document describes the tables of the Olist e-commerce database (`olist.db`). It covers orders placed between 2016 and 2018 on a Brazilian marketplace. Machine-readable column notes are in `schema_notes.json`.

## Conventions

- All monetary values are in Brazilian reais (BRL).
- Timestamps are text in the form `YYYY-MM-DD HH:MM:SS`. Use SQLite functions such as `strftime`, `date` and `julianday` on them.
- Empty values are stored as NULL.
- Two column names keep the original misspelling `lenght` (`product_name_lenght`, `product_description_lenght`). Do not "correct" them in queries.

## Tables and relationships

| Table | Grain (one row is...) | Joins to |
|---|---|---|
| `customers` | one customer record per order (`customer_id`) | `orders.customer_id` |
| `orders` | one order | `customers`, `order_items`, `order_payments`, `order_reviews` via `order_id` |
| `order_items` | one product line within an order | `orders`, `products`, `sellers` |
| `order_payments` | one payment instalment or method used on an order | `orders` |
| `order_reviews` | one customer review | `orders` |
| `products` | one product | `order_items.product_id` |
| `sellers` | one seller | `order_items.seller_id` |
| `geolocation` | one latitude/longitude sample for a zip prefix | `customers` and `sellers` by zip prefix |
| `product_category_translation` | one category name | `products.product_category_name` |

## Important subtleties

1. **`customer_id` versus `customer_unique_id`.** The `customer_id` changes with every order, so it is a key between `orders` and `customers`. The real person is `customer_unique_id`. To count distinct buyers, count distinct `customer_unique_id`, never `customer_id`.
2. **An order can have several items.** `order_items` has one row per item, with `order_item_id` numbering them 1, 2, 3 and so on. Joining `orders` to `order_items` multiplies order rows. Use `COUNT(DISTINCT order_id)` to count orders after a join.
3. **Revenue lives in `order_items`.** The item revenue is `price`. Freight is `freight_value`. The total paid by the customer is `payment_value` in `order_payments`, and can differ slightly from price plus freight because of vouchers and instalment interest.
4. **Payments can be split.** One order may have several rows in `order_payments` (for example a voucher plus a card). Sum `payment_value` per order.
5. **No refunds table exists.** Refund analysis uses proxies: cancelled orders and low review scores. See the refund policy and the metrics glossary.
6. **Geolocation has many rows per zip prefix.** It holds around one million samples, so joining on zip prefix multiplies rows. Aggregate first (for example the average latitude per prefix).
7. **Category names are in Portuguese** in `products`. Join `product_category_translation` for English.

## Order status values

| `order_status` | Meaning |
|---|---|
| `created` | Order placed, payment not yet confirmed |
| `approved` | Payment approved |
| `invoiced` | Invoice issued |
| `processing` | Seller is preparing the order |
| `shipped` | Handed to the carrier |
| `delivered` | Received by the customer |
| `unavailable` | Seller could not supply the product |
| `canceled` | Cancelled before delivery |

## Payment types

`credit_card`, `boleto` (bank slip), `voucher`, `debit_card`, and `not_defined` (rare, treat as unknown).

## Sensitive columns

`customers.customer_unique_id`, `customers.customer_zip_code_prefix`, `geolocation.geolocation_lat`, and `geolocation.geolocation_lng` can help identify a person or home area. Queries may use them inside aggregates (for example counts), but results must not list them row by row.

## Size guide

The full dataset holds roughly 99 thousand orders, 112 thousand order items, 103 thousand payments, 99 thousand reviews, 33 thousand products, 3 thousand sellers and 1 million geolocation rows. Large queries on `geolocation` should always include a `LIMIT` or an aggregate.

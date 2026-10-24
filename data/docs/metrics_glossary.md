# Metrics Glossary

Standard definitions for every business term used by the analyst. When a question uses one of these terms, use the definition below and state it in the answer.

## Time conventions

- **Month** is the calendar month of `order_purchase_timestamp`, written `YYYY-MM`.
- **Last week** means the 7 days before the latest purchase date in the data, not the real-world current date, because the data ends in 2018.
- If a question names no period, ask the user which period they mean before running a broad query.

## Volume metrics

| Metric | Definition |
|---|---|
| Orders | `COUNT(DISTINCT order_id)` in `orders` for the period |
| Order lines | Rows of `order_items` |
| Active customers | `COUNT(DISTINCT customer_unique_id)` of customers with at least one order in the period |
| Repeat customer | A `customer_unique_id` with 2 or more orders |

## Revenue metrics

| Metric | Definition |
|---|---|
| Item revenue (GMV) | `SUM(price)` over `order_items`, excluding orders with status `canceled` or `unavailable` |
| Freight revenue | `SUM(freight_value)` over the same rows |
| Order value | `SUM(price + freight_value)` per order |
| Average order value (AOV) | Total of price plus freight divided by `COUNT(DISTINCT order_id)`, using the same exclusions |
| Payment total | `SUM(payment_value)` from `order_payments`; do not add it to item revenue |

Revenue is attributed to the **purchase month**, not the delivery month.

## Delivery metrics

| Metric | Definition |
|---|---|
| Delivered order | `order_status = 'delivered'` and a non-NULL `order_delivered_customer_date` |
| Delivery time (days) | `julianday(order_delivered_customer_date) - julianday(order_purchase_timestamp)` |
| Late delivery | Delivered after the estimated date: `order_delivered_customer_date > order_estimated_delivery_date` |
| Late delivery rate | Late delivered orders divided by all delivered orders, as a percentage |
| Days late | `julianday(delivered) - julianday(estimated)`, only for late orders |

## Satisfaction metrics

| Metric | Definition |
|---|---|
| Average review score | `AVG(review_score)` across reviews in the period |
| Negative review rate | Reviews with score 1 or 2, divided by all reviews |
| 1-star rate | Reviews with score 1, divided by all reviews |
| Review response time | Days between `review_creation_date` and `review_answer_timestamp` |

Reviews are assigned to the month of the **order purchase**, so that they line up with delivery and revenue, unless the question explicitly asks about the review date.

## Cancellation and refund metrics

The database has no refund amounts, so the system uses proxies and must say so.

| Metric | Definition |
|---|---|
| Cancellation rate | Orders with status `canceled`, divided by all orders in the period, as a percentage |
| Refund proxy (cancelled value) | `SUM(price + freight_value)` of items in `canceled` or `unavailable` orders |
| Dissatisfaction rate | Share of delivered orders whose review score is 1 or 2 |

A "refund spike" question is answered by looking at cancellation rate, cancelled value and dissatisfaction rate, split by month, state, category and seller, then by looking for causes in the policy documents.

## Seller and product metrics

| Metric | Definition |
|---|---|
| Seller revenue | `SUM(price)` of the seller's items, excluding cancelled and unavailable orders |
| Seller late rate | Late delivered orders of the seller divided by its delivered orders |
| Top category | Category with the largest item revenue, using the English category name |

Seller and category rankings should exclude groups with fewer than **30 orders**, because small samples give extreme rates.

## Statistical cautions

1. State the denominator with every rate.
2. A change of less than **1 percentage point** in a rate based on fewer than 500 orders is within normal noise.
3. Percentages are rounded to two decimals; money to two decimals; day counts to one decimal.
4. Never report a number that was not returned by a query or found in a document.

# Seller Guidelines

Version 4.0, effective 1 January 2017. Every seller (`seller_id`) must follow these rules.

## 1. Onboarding

New sellers must provide a tax identifier, a bank account and a shipping origin zip code (`seller_zip_code_prefix`). Accounts are reviewed within **5 business days**. For the first **30 days** a new seller may list at most **50 products**, which is raised to 500 after a clean first month.

## 2. Listing quality

- Titles of at least **20 characters** and descriptions of at least **200 characters** (stored in the data as `product_name_lenght` and `product_description_lenght`).
- At least **3 photos** per product (`product_photos_qty`). Listings with one photo or fewer are ranked lower in search.
- Weight and dimensions (`product_weight_g`, `product_length_cm`, `product_height_cm`, `product_width_cm`) must be accurate. Wrong dimensions cause freight under-charging, which is billed back to the seller.
- Each product belongs to one category (`product_category_name`, in Portuguese). The English name is in the `product_category_translation` table.

## 3. Pricing and fees

Olist charges a commission of **16%** of the item price (`price` in `order_items`), plus a fixed fee of **BRL 5.00** per item for orders under BRL 30. Freight (`freight_value`) is paid by the customer and passed to the carrier; it is not part of the seller's revenue. The seller's gross revenue for a period is the sum of `price` over its items, excluding cancelled and unavailable orders.

## 4. Fulfilment duties

1. Hand the parcel to the carrier before the shipping limit date.
2. Pack the product to survive transport; damage caused by weak packaging is charged to the seller.
3. Answer customer messages within **24 hours** on business days.

## 5. Performance scorecard

Each seller is scored every quarter on four measures:

| Measure | Good | Warning | Suspension risk |
|---|---|---|---|
| Cancellation rate | Below 1% | 1% to 5% | Above 5% |
| Late delivery rate | Below 8% | 8% to 15% | Above 15% |
| Average review score | 4.0 or higher | 3.5 to 3.9 | Below 3.5 |
| Shipping limit date missed | Below 5% | 5% to 10% | Above 10% |

Sellers need at least **30 orders** in the quarter to be scored, because rates on small volumes are unreliable.

## 6. Consequences

- **Warning**: a written notice and a required improvement plan within 14 days.
- **Restriction**: new listings frozen and search ranking reduced for **60 days**.
- **Suspension**: sales paused until the seller passes a review. Pending orders are still fulfilled or refunded at the seller's cost.
- A seller who reaches suspension risk on two measures in the same quarter is suspended automatically.

## 7. Disputes and refunds

When a refund is caused by a seller error, the refund amount and a handling charge of **BRL 8.00** are deducted from the next payout. Sellers may appeal within **10 days** by providing proof of shipment and delivery.

## 8. Payouts

Payouts are made **30 days after the delivery date** (or after the 7-day withdrawal period if later), so that refunds can be netted first. Payouts are issued every Monday.

## 9. Seller data and privacy

Seller location is recorded at city and state level (`seller_city`, `seller_state`) and by zip code prefix. Sellers are businesses; their performance may be reported by `seller_id`. Customer information must never be shared back with sellers beyond what is needed to deliver the order.

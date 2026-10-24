# Refund and Cancellation Policy

Version 3.1, effective 1 January 2017. Currency: Brazilian reais (BRL).

## 1. Scope

This policy covers every order placed on the marketplace, whether the product is shipped by Olist's logistics partners or directly by the seller. The Olist database does not contain a refunds table. For analysis, the following **proxies** are used and must always be named as proxies in answers:

- **Cancelled order**: an order whose `order_status` is `canceled`. Money is returned to the customer in full.
- **Unavailable order**: an order whose `order_status` is `unavailable`. The seller could not supply the product, and the customer is refunded in full.
- **Dissatisfied delivered order**: a delivered order with a `review_score` of 1 or 2. These orders are the main source of refund requests after delivery.

## 2. Refund eligibility

| Situation | Refund | Deadline |
|---|---|---|
| Order cancelled before shipment | 100% of price and freight | Any time before the carrier pickup |
| Product never arrived | 100% of price and freight | 30 days after the estimated delivery date |
| Product arrived damaged or wrong | 100% of price, freight refunded if seller at fault | 7 days after delivery |
| Product not as described | 100% of price, return shipping paid by seller | 7 days after delivery |
| Change of mind (distance selling) | Price only, buyer pays return shipping | 7 days after delivery |

Under the Brazilian consumer code, the 7-day right of withdrawal applies to purchases made online. After 7 days, refunds are at Olist's discretion and depend on the seller's agreement.

## 3. Refund timing

- Credit card: the refund is requested on approval and appears within **1 to 2 billing cycles**.
- Boleto bancario: bank transfer within **10 business days** after the customer supplies bank details.
- Voucher: voucher balance is restored within **1 business day**.
- Debit card: **5 to 7 business days**.

## 4. Who pays

The seller bears the refund cost when the cause is a seller error: wrong item, damage caused by poor packaging, late shipment beyond the shipping limit date, or product not as described. Olist bears the cost when the cause is carrier damage or loss, and deducts it from the carrier settlement. Customers bear the cost only for change of mind.

## 5. Compensation tiers for late delivery

When a delivered order arrives after its estimated delivery date, the customer is entitled to compensation as a credit voucher:

| Days late | Compensation |
|---|---|
| 1 to 3 days | None; apology message only |
| 4 to 7 days | Voucher worth 5% of the item price |
| 8 to 14 days | Voucher worth 10% of the item price |
| 15 to 30 days | Voucher worth 20% of the item price, or free freight refund |
| More than 30 days | Full freight refund plus 25% voucher, and a case is opened with the seller |

Compensation is capped at BRL 150 per order.

## 6. Expected refund rate and escalation

The finance team treats a monthly cancellation rate (cancelled orders divided by all orders in the month) below **1.0%** as normal. If the rate exceeds **2.0%** in any month, or if any single seller has more than **5%** of its orders cancelled, Operations opens an investigation. Typical causes are stock-outs at a seller, a carrier failure in one region, or a payment problem such as boleto expiry.

## 7. Fraud and abuse

Accounts that request refunds on more than **3 orders in 90 days**, identified by `customer_unique_id`, are flagged for manual review. Refund history is personal data; analysts report counts and rates only, never individual customers.

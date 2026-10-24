# Delivery Service Level Agreement (SLA)

Version 2.6, effective 1 January 2017. Applies to all sellers and logistics partners.

## 1. Order lifecycle and timestamps

Every order passes through these stages. Each stage maps to a column in the `orders` table.

| Stage | Column | Meaning |
|---|---|---|
| Purchase | `order_purchase_timestamp` | Customer places the order |
| Approval | `order_approved_at` | Payment is approved |
| Carrier handover | `order_delivered_carrier_date` | Seller hands the parcel to the carrier |
| Delivery | `order_delivered_customer_date` | Customer receives the parcel |
| Promise | `order_estimated_delivery_date` | Date shown to the customer at checkout |

Only orders with `order_status = 'delivered'` normally have a delivery date. Orders that are cancelled, unavailable or still in transit have empty (NULL) delivery dates and must be excluded from delivery-time calculations.

## 2. Seller handling time

After payment approval, the seller must hand the parcel to the carrier before the **shipping limit date** (`shipping_limit_date` in `order_items`). The standard handling time is **3 business days**. A seller who misses the shipping limit date on more than **10%** of its orders in a quarter receives a written warning.

## 3. Estimated delivery date

The estimated delivery date is calculated at checkout as the seller handling time plus the carrier transit time for the destination state, plus a safety buffer of **3 days**. Typical transit estimates:

- Same state: 3 to 6 days
- Southeast to South or Centre-West: 6 to 10 days
- Southeast to North or Northeast: 10 to 20 days

The buffer exists so that most deliveries arrive early. In a healthy month, about **90%** of delivered orders arrive on or before the estimate.

## 4. Definition of "late delivery"

An order is **late** when it was delivered **after** the estimated date:

`order_delivered_customer_date > order_estimated_delivery_date`

An order delivered on the estimated date, or earlier, is **on time**. The comparison uses the full timestamp. **Days late** is the number of days between the delivery timestamp and the estimate, counted only for late orders.

**Late delivery rate** = late delivered orders / all delivered orders with a delivery date, for the chosen period.

## 5. Service targets

| Measure | Target | Escalation threshold |
|---|---|---|
| Late delivery rate (all orders) | Below 8% | Above 12% |
| Late delivery rate for one state | Below 12% | Above 20% |
| Average delivery time (purchase to delivery) | Below 12 days | Above 15 days |
| Orders delivered more than 14 days late | Below 1% | Above 2% |

Peaks in demand, such as Black Friday in late November, normally push the late rate up by **3 to 6 percentage points** for the following four weeks. Operations adjusts the estimate buffer for these periods.

## 6. Carrier responsibilities

Carriers must provide tracking events within 24 hours of pickup. A parcel with no tracking event for **7 days** is treated as lost. The customer is then refunded under the refund policy and the carrier is charged the item value.

## 7. Impact on customer satisfaction

Analysis of past orders shows that lateness is the strongest driver of low review scores. As a guide, delivered on-time orders average a review score of about **4.3**, orders 1 to 7 days late average about **3.0**, and orders more than 7 days late average about **1.7**. Treat these as policy benchmarks, not as measured results; measured values come from querying the database.

## 8. Reporting rules

Delivery performance is always reported by purchase month (`order_purchase_timestamp`), and by customer state (`customer_state` in `customers`) when comparing regions. Orders without a delivery date are excluded from late-rate calculations but counted separately as "not yet delivered".

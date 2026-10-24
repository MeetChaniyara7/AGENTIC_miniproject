# Review Moderation Policy

Version 1.8, effective 1 January 2017. Governs the `order_reviews` table.

## 1. How reviews work

After an order is delivered (or when the estimated delivery date passes), the customer receives a satisfaction survey by email. The survey asks for a **score from 1 to 5** and allows an optional comment with a title and a message. The record stores:

- `review_score`: the rating, 1 to 5
- `review_creation_date`: when the survey was sent
- `review_answer_timestamp`: when the customer replied
- `review_comment_title` and `review_comment_message`: free text in Portuguese, often empty

Roughly **58%** of reviews are expected to carry no written comment. A review without text is still a valid score.

## 2. Meaning of the review score

| Score | Label | Meaning |
|---|---|---|
| 5 | Excellent | Fully satisfied |
| 4 | Good | Satisfied, minor issue |
| 3 | Neutral | Mixed experience |
| 2 | Poor | Dissatisfied; refund request likely |
| 1 | Very poor | Very dissatisfied; escalated to support |

A **negative review** is a score of 1 or 2. A **positive review** is a score of 4 or 5. A score of 3 is neutral and counted in neither group. The **average review score** is the mean of `review_score` across the selected reviews, rounded to two decimals.

## 3. Targets

- Marketplace average review score: **4.0 or higher**.
- Share of negative reviews: below **15%**.
- Share of 1-star reviews: below **9%**.

If the monthly average falls by more than **0.3 points** compared with the previous month, Operations investigates delivery performance first, because late delivery is the most common cause.

## 4. Which reviews are published

Reviews appear on the product page after moderation. A review is **removed** if it:

1. contains personal data (phone numbers, addresses, tax IDs),
2. contains abusive language or threats,
3. concerns a different product than the one ordered,
4. is written by someone who did not buy the product.

Moderators decide within **48 hours**. Removed reviews keep their score in internal statistics, so the data counts them, but the text is hidden.

## 5. Multiple reviews per order

An order should have one review, but a customer who receives several parcels may reply more than once, and the source data holds some orders with more than one review. When calculating a score per order, analysts average the scores for that order. Counting rows in `order_reviews` counts **reviews**; counting distinct `order_id` counts **reviewed orders**. These two numbers differ and must not be mixed up.

## 6. Seller response

Sellers may respond publicly to a review within **7 days**. They may not offer money in exchange for changing a score. Offering incentives for good reviews leads to suspension under the seller guidelines.

## 7. Handling of comments in analysis

Comments are in Portuguese and may contain personal details. They are not loaded into the answers of the analyst system unless needed, and are never quoted with names. Aggregated statistics such as score distribution, response time (days between `review_creation_date` and `review_answer_timestamp`) and share of orders with comments are always safe to report.

## 8. Reviews and refunds

Orders with a score of 1 or 2 receive an automatic follow-up from support within **24 hours**. Support may offer a refund or compensation under the refund policy. Reviews are never required for a refund to be granted.

# Legacy Operational System Architecture and Business Calculation Policies

This document specifies the operational business policies, state-machine transitions, and calculation standards maintained by the legacy operational application layer in the operational database (`opdb`). These specifications are normative: legacy extract procedures read operational tables as maintained and persisted under these rules.

## 1. Temporal Representation and Time Zone Conventions

All operational event recording, financial timestamps, order placement, and account lifecycle state transitions are evaluated and stored in Berlin wall-clock time (`Europe/Berlin`) at the transaction commit instant. Calendar dates referenced across all operational rules denote the local calendar date of the Berlin commit instant. The dual-write period spans from `2025-03-01` through `2026-01-31`.

## 2. Foreign Exchange Rate Fixings and Banking Calendar

Foreign exchange rates (`fx_rates`) are published once daily on financial operating days, with official fixing rates taking effect at 16:00:00 Berlin wall-clock time (`Europe/Berlin`). The effective exchange rate for any operational transaction is the latest fixing published at or prior to the transaction's commit instant:
- Transactions committed strictly prior to 16:00:00 Berlin wall-clock time utilize the most recent rate published before that calendar date.
- Transactions committed at or after 16:00:00 Berlin wall-clock time utilize the fixing published on that calendar date (or the most recent preceding financial operating day if unpublished).

Non-operating periods include calendar weekends (Saturday and Sunday) and official TARGET interbank operating holidays:
- Good Friday (`2025-04-18`)
- Easter Monday (`2025-04-21`)
- Labour Day (`2025-05-01`)
- Christmas Day (`2025-12-25`)
- Boxing Day / St. Stephen's Day (`2025-12-26`)
- New Year's Day (`2026-01-01`)

During non-operating periods, the operational system falls back to the most recent published operating rate preceding the gap. The exchange rate for transactions denominated in EUR is exactly 1.0 at all times.

## 3. Currency Conversion and Monetary Precision

All monetary conversions to EUR follow exact half-even rounding (IEEE 754 round-to-nearest, ties-to-even) to two decimal places:

$$
\text{amount\_eur} = \text{round\_half\_even}\left(\frac{\text{amount\_minor}}{10^{\text{exponent}}} \times \text{rate}, 2\right)
$$

where `exponent` denotes the currency's minor-unit exponent (0 for JPY, 3 for KWD, and 2 for EUR, USD, and GBP) and `rate` denotes the effective exchange rate to EUR at write commit time. Conversions are stored at transaction commit time and are never retroactively recomputed against subsequent rate updates.

## 4. Order Line Valuation and Order Totals

Order line `net_eur` is evaluated using the line currency and order commit timestamp under the monetary conversion rule applied to `(unit_price_minor * quantity - discount_minor)` in minor units. Lines belonging to an order share the order's commit timestamp for currency rate evaluation. Promotional voucher discounts applied to a specific line may exceed line item value, resulting in negative `net_eur` on that line item.

An order's `total_eur` is the exact sum of its constituent lines' `net_eur` values:

$$
\text{total\_eur} = \sum_{\text{lines}} \text{net\_eur}
$$

## 5. Promotional Campaigns, Spend Eligibility, and Tie-Breaking

An order's `promo_id` identifies the active promotional application with the lowest sequence number (`seq`). Applications with a recorded removal timestamp (`removed_at` prior to extract cutoff) are non-effective. If multiple active promotional applications on the same order share the same lowest sequence number, the application with the earliest `applied_at` timestamp takes precedence.

Furthermore, promotional campaigns enforce qualifying spend thresholds:
- Promotional discount codes with the prefix `PROMO-SAVE` (e.g., `PROMO-SAVE10`, `PROMO-SAVE20`) require an order `total_eur` of at least 40.00 EUR. If an order's `total_eur` is strictly less than 40.00 EUR, the promo code is ineligible and does not apply to the order.
- Other promotional codes have no minimum spend threshold.

Unpromoted orders, orders where all applied promotions have been removed, or orders where no applied promotion meets the qualifying spend criteria record `NULL` in `orders.promo_id`.

## 6. Order Settlement and Lifecycle State Precedence

Operational order status (`orders.status`) reflects the hierarchical evaluation of cumulative financial settlement in EUR, terminal cancellation, and fulfillment lifecycle state:

1. `refunded`: Cumulative recorded `refund` payment EUR equals or exceeds cumulative `capture` payment EUR (where captured EUR > 0).
2. `partially_refunded`: Cumulative recorded `refund` payment EUR is strictly greater than 0, where captured EUR remains strictly greater than refunded EUR. Financial settlement status strictly precedes cancellation and fulfillment: orders with active recorded partial refunds retain `partially_refunded` status even if a subsequent lifecycle cancellation event is recorded.
3. `cancelled`: The order was cancelled in fulfillment lifecycle, or the ordering customer account was deleted prior to payment capture or fulfillment. Cancellation is an irreversible terminal state: once an order transitions to `cancelled`, neither subsequent account reinstatement, late payment capture, nor subsequent fulfillment lifecycle events (such as late `fulfilled` status or shipments) reopen or alter cancelled orders.
4. `shipped`: The order fulfillment lifecycle is `fulfilled` with zero recorded refunds.
5. `paid`: The order has recorded capture payments with zero recorded refunds.
6. `pending`: Unsettled orders with neither captures, cancellations, nor fulfillment.

## 7. Customer Account Lifecycle and Deduplication

Account deletion updates `deleted_at` to the operational deletion timestamp. Subsequent account restoration clears `deleted_at` to `NULL`.

Customer account deduplication identifies accounts sharing identical email addresses (case-insensitive). The canonical account is defined as the account with the minimum `customer_id` among active (non-deleted) accounts in the email group. Orders placed by registered accounts map to the canonical account ID of their deduplication group. Unmatched guest orders map to customer ID `0`.

## 8. Shipments Logistics

Operational shipment records track physical dispatches. Shipments cancelled prior to the extract cutoff are non-effective. The effective shipment date for order lead-time analysis is the earliest valid shipment dispatch timestamp.

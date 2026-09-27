# Platform data contract

This document specifies the tables published by the platform service. It is the normative specification for column meanings, types, units, and constraints. All tables reside in the `platform` schema.

## Time and extract execution

All timestamp columns in the platform schema are `TIMESTAMPTZ`, stored and evaluated in UTC at microsecond precision. The `committed_at` column represents the transaction commit instant of the underlying operational write.

The `extract_meta` table contains a single column, `as_of_utc` (`TIMESTAMPTZ`), indicating the batch extract execution cutoff timestamp for the current data window.

## `customer_versions`

Maintains temporal profile versions for customer accounts.

Columns:
- `customer_id` (`BIGINT`, not null)
- `email` (`TEXT`, not null)
- `segment` (`TEXT`, not null)
- `region` (`TEXT`, not null)
- `valid_from` (`TIMESTAMPTZ`, not null): Version start commit instant.
- `valid_to` (`TIMESTAMPTZ`, nullable): Version end commit instant (`NULL` for current version). Valid interval is `[valid_from, valid_to)`.

## `customer_status_events`

Records account lifecycle events.

Columns:
- `customer_id` (`BIGINT`, not null)
- `event_type` (`TEXT`, not null): `deleted` or `restored`.
- `committed_at` (`TIMESTAMPTZ`, not null)

## `orders`

Order records.

Columns:
- `order_id` (`BIGINT`, not null)
- `customer_id` (`BIGINT`, nullable): Account identifier, null for guest checkouts.
- `guest_email` (`TEXT`, nullable): Supplied guest checkout email.
- `committed_at` (`TIMESTAMPTZ`, not null): Order placement commit instant.

## `order_lines`

Individual line items associated with an order.

Columns:
- `order_line_id` (`BIGINT`, not null)
- `order_id` (`BIGINT`, not null)
- `sku` (`TEXT`, not null)
- `quantity` (`INTEGER`, not null)
- `unit_price_minor` (`BIGINT`, not null): Unit price in minor units.
- `discount_minor` (`BIGINT`, not null): Line discount in minor units.
- `currency` (`TEXT`, not null)
- `committed_at` (`TIMESTAMPTZ`, not null)

## `payment_events`

Financial transaction events recorded for orders.

Columns:
- `payment_id` (`BIGINT`, not null)
- `order_id` (`BIGINT`, not null)
- `kind` (`TEXT`, not null): `capture` or `refund`.
- `amount_minor` (`BIGINT`, not null): Payment amount in minor units.
- `currency` (`TEXT`, not null)
- `occurred_at` (`TIMESTAMPTZ`, not null): Provider authorization instant.
- `committed_at` (`TIMESTAMPTZ`, not null): Platform record commit instant.

## `order_lifecycle_events`

Order fulfillment state changes.

Columns:
- `event_id` (`BIGINT`, not null)
- `order_id` (`BIGINT`, not null)
- `state` (`TEXT`, not null): `open`, `fulfilled`, or `cancelled`.
- `committed_at` (`TIMESTAMPTZ`, not null)

## `order_promo_applications`

Promotional code applications applied to orders.

Columns:
- `order_id` (`BIGINT`, not null)
- `seq` (`INTEGER`, not null): Application sequence index (1-based).
- `promo_code` (`TEXT`, not null)
- `applied_at` (`TIMESTAMPTZ`, not null)
- `removed_at` (`TIMESTAMPTZ`, nullable): Revocation instant.

## `shipments`

Shipment dispatch records.

Columns:
- `shipment_id` (`BIGINT`, not null)
- `order_id` (`BIGINT`, not null)
- `shipped_at` (`TIMESTAMPTZ`, not null)
- `cancelled_at` (`TIMESTAMPTZ`, nullable): Cancellation instant.
- `committed_at` (`TIMESTAMPTZ`, not null)

## `products`

Product catalog.

Columns:
- `sku` (`TEXT`, not null, primary key)
- `name` (`TEXT`, not null)
- `category` (`TEXT`, not null)

## `currencies`

ISO currency definitions and exponents.

Columns:
- `code` (`TEXT`, not null, primary key)
- `exponent` (`INTEGER`, not null): Minor unit exponent (e.g. 2 for EUR/USD, 0 for JPY, 3 for KWD).

## `fx_daily`

Daily exchange rates to EUR.

Columns:
- `date` (`DATE`, not null)
- `currency` (`TEXT`, not null)
- `rate_to_eur` (`DECIMAL`, not null)

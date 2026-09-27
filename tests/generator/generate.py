"""
Full generator for warehouse-schema-cutover.
Seeded, deterministic. Simulates ONE event stream and applies it to two writers:
- Legacy operational writer (Berlin wall-clock, rounded EUR, derived status, app-rules.md)
- Platform writer (raw UTC facts, contracts/platform.md)

Outputs:
- Platform feed (up to as_of_utc + 6 hours)
- Legacy operational snapshot (committed strictly before as_of_utc)
"""
import random
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

BERLIN = ZoneInfo("Europe/Berlin")
UTC = timezone.utc

CURRENCIES = {
    "EUR": 2,
    "USD": 2,
    "GBP": 2,
    "JPY": 0,
    "KWD": 3,
}

FX_BASE = {
    "USD": Decimal("0.92"),
    "GBP": Decimal("0.84"),
    "JPY": Decimal("0.0062"),
    "KWD": Decimal("3.05"),
}

# TARGET holidays in 2025 and 2026:
TARGET_HOLIDAYS = {
    date(2025, 4, 18),  # Good Friday
    date(2025, 4, 21),  # Easter Monday
    date(2025, 5, 1),   # Labour Day
    date(2025, 12, 25), # Christmas Day
    date(2025, 12, 26), # Boxing Day / St. Stephen
    date(2026, 1, 1),   # New Year's Day
}

PRODUCTS = [
    ("SKU-WIDGET-A", "Standard Widget", "Hardware"),
    ("SKU-WIDGET-B", "Premium Widget", "Hardware"),
    ("SKU-GADGET-C", "Smart Gadget", "Electronics"),
    ("SKU-TOOL-D", "Multi Tool", "Tools"),
    ("SKU-DEVICE-E", "Connected Device", "Electronics"),
]
SKU_KEYS = [p[0] for p in PRODUCTS]


def berlin_midnight_utc(d: date) -> datetime:
    local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=BERLIN)
    return local.astimezone(UTC)


def fx_rate(d: date, currency: str) -> Decimal:
    wiggle = Decimal("0.0005") * (d.toordinal() % 7 - 3)
    return FX_BASE[currency] + wiggle


def is_fx_gap(d: date, currency: str) -> bool:
    if d.weekday() >= 5:  # Sat/Sun
        return True
    if d in TARGET_HOLIDAYS:
        return True
    return False


def most_recent_rate(fx_table: dict, currency: str, d: date) -> Decimal:
    cur = d
    for _ in range(15):
        if (cur, currency) in fx_table:
            return fx_table[(cur, currency)]
        cur = cur - timedelta(days=1)
    raise RuntimeError(f"no fx rate found within 15 days back for {currency} on {d}")


def effective_fx_date(committed_at: datetime) -> date:
    berlin_dt = committed_at.astimezone(BERLIN)
    # Publication cutoff: daily ECB fixing rates take effect at 16:00 Berlin time.
    # Writes committed strictly before 16:00 use the previous business date's rate.
    if berlin_dt.time() < datetime.strptime("16:00:00", "%H:%M:%S").time():
        return berlin_dt.date() - timedelta(days=1)
    return berlin_dt.date()


def eur_amount(amount_minor: int, exponent: int, rate: Decimal) -> Decimal:
    amt = Decimal(amount_minor) / (Decimal(10) ** exponent)
    return (amt * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


class IdGen:
    def __init__(self, start: int = 0):
        self.n = start

    def next(self) -> int:
        self.n += 1
        return self.n


class Window:
    """Builds one window's worth of platform + legacy operational facts."""

    def __init__(self, name: str, as_of_date: date, seed: int):
        self.name = name
        self.as_of_utc = berlin_midnight_utc(as_of_date)
        self.rng = random.Random(seed)
        self.window_start = self.as_of_utc - timedelta(days=45)
        self.window_end = self.as_of_utc + timedelta(hours=6)

        self.cust_id = IdGen(0)
        self.order_id = IdGen(0)
        self.line_id = IdGen(0)
        self.pay_id = IdGen(0)
        self.lifecycle_id = IdGen(0)
        self.shipment_id = IdGen(0)

        # platform tables (rows)
        self.p_customer_versions = []
        self.p_customer_status_events = []
        self.p_orders = []
        self.p_order_lines = []
        self.p_payment_events = []
        self.p_order_lifecycle_events = []
        self.p_order_promo_applications = []
        self.p_shipments = []

        # legacy operational tables
        self.l_customers = {}        # id -> dict (current state)
        self.l_orders = {}           # id -> dict
        self.l_order_lines = []
        self.l_payments = []
        self.l_order_lifecycle = []
        self.l_promo_applications = []
        self.l_shipments = []

        self._order_status_sums = {}     # order_id -> {captured, refunded}
        self._order_lifecycle_state = {} # order_id -> state

        # FX table
        self.fx_table = {}
        self._build_fx_calendar()

    def _build_fx_calendar(self):
        d = self.window_start.astimezone(BERLIN).date() - timedelta(days=5)
        end = self.window_end.astimezone(BERLIN).date() + timedelta(days=2)
        while d <= end:
            for cur in FX_BASE:
                if not is_fx_gap(d, cur):
                    self.fx_table[(d, cur)] = fx_rate(d, cur)
            d += timedelta(days=1)

    # ---------- customers ----------
    def add_customer(self, committed_at_utc: datetime, segment: str, region: str,
                     email: str = None, cust_id: int = None) -> int:
        cid = cust_id if cust_id is not None else self.cust_id.next()
        if cust_id is not None and cust_id > self.cust_id.n:
            self.cust_id.n = cust_id
        email = email or f"customer{cid}@example.test"
        self.p_customer_versions.append(
            dict(customer_id=cid, email=email, segment=segment, region=region,
                 valid_from=committed_at_utc, valid_to=None)
        )
        if committed_at_utc < self.as_of_utc:
            self.l_customers[cid] = dict(
                id=cid, email=email, segment=segment, region=region,
                deleted_at=None, last_login_ip="192.168.1.1",
                _created_at=committed_at_utc
            )
        return cid

    def change_segment(self, customer_id: int, committed_at_utc: datetime,
                       new_segment: str, new_region: str = None):
        prior = next(v for v in self.p_customer_versions
                     if v["customer_id"] == customer_id and v["valid_to"] is None)
        prior["valid_to"] = committed_at_utc
        self.p_customer_versions.append(
            dict(customer_id=customer_id, email=prior["email"], segment=new_segment,
                 region=new_region or prior["region"], valid_from=committed_at_utc, valid_to=None)
        )
        if committed_at_utc < self.as_of_utc and customer_id in self.l_customers:
            self.l_customers[customer_id]["segment"] = new_segment
            if new_region:
                self.l_customers[customer_id]["region"] = new_region

    def delete_customer(self, customer_id: int, committed_at_utc: datetime):
        self.p_customer_status_events.append(
            dict(customer_id=customer_id, event_type="deleted", committed_at=committed_at_utc)
        )
        if committed_at_utc < self.as_of_utc and customer_id in self.l_customers:
            berlin_dt = committed_at_utc.astimezone(BERLIN).replace(tzinfo=None)
            self.l_customers[customer_id]["deleted_at"] = berlin_dt
            for oid, o in self.l_orders.items():
                if o["customer_id"] == customer_id:
                    self._recompute_status(oid)

    def restore_customer(self, customer_id: int, committed_at_utc: datetime):
        self.p_customer_status_events.append(
            dict(customer_id=customer_id, event_type="restored", committed_at=committed_at_utc)
        )
        if committed_at_utc < self.as_of_utc and customer_id in self.l_customers:
            self.l_customers[customer_id]["deleted_at"] = None
            for oid, o in self.l_orders.items():
                if o["customer_id"] == customer_id:
                    self._recompute_status(oid)

    # ---------- orders / lines / payments / lifecycle ----------
    def add_order(self, customer_id: int, committed_at_utc: datetime) -> int:
        oid = self.order_id.next()
        self.p_orders.append(
            dict(order_id=oid, customer_id=customer_id, guest_email=None,
                 committed_at=committed_at_utc)
        )
        self.p_order_lifecycle_events.append(
            dict(event_id=self.lifecycle_id.next(), order_id=oid,
                 state="open", committed_at=committed_at_utc)
        )
        self._order_status_sums[oid] = {"captured": Decimal("0.00"), "refunded": Decimal("0.00")}
        self._order_lifecycle_state[oid] = "open"
        if committed_at_utc < self.as_of_utc:
            berlin_dt = committed_at_utc.astimezone(BERLIN).replace(tzinfo=None)
            self.l_orders[oid] = dict(
                id=oid, customer_id=customer_id, guest_email=None, channel="web",
                placed_at=berlin_dt, total_eur=Decimal("0.00"), status="pending", promo_id=None,
                _committed_at=committed_at_utc
            )
            self.l_order_lifecycle.append(
                dict(id=self.lifecycle_id.n, order_id=oid, state="open", changed_at=berlin_dt)
            )
        return oid

    def add_guest_order(self, guest_email: str, committed_at_utc: datetime) -> int:
        oid = self.order_id.next()
        self.p_orders.append(
            dict(order_id=oid, customer_id=None, guest_email=guest_email,
                 committed_at=committed_at_utc)
        )
        self.p_order_lifecycle_events.append(
            dict(event_id=self.lifecycle_id.next(), order_id=oid,
                 state="open", committed_at=committed_at_utc)
        )
        self._order_status_sums[oid] = {"captured": Decimal("0.00"), "refunded": Decimal("0.00")}
        self._order_lifecycle_state[oid] = "open"
        if committed_at_utc < self.as_of_utc:
            berlin_dt = committed_at_utc.astimezone(BERLIN).replace(tzinfo=None)
            self.l_orders[oid] = dict(
                id=oid, customer_id=None, guest_email=guest_email, channel="web",
                placed_at=berlin_dt, total_eur=Decimal("0.00"), status="pending", promo_id=None,
                _committed_at=committed_at_utc
            )
            self.l_order_lifecycle.append(
                dict(id=self.lifecycle_id.n, order_id=oid, state="open", changed_at=berlin_dt)
            )
        return oid

    def _order_commit(self, order_id: int) -> datetime:
        return next(o["committed_at"] for o in self.p_orders if o["order_id"] == order_id)

    def add_line(self, order_id: int, sku: str, quantity: int, unit_price_minor: int,
                 discount_minor: int, currency: str, committed_at_utc: datetime = None):
        committed_at_utc = committed_at_utc or self._order_commit(order_id)
        lid = self.line_id.next()
        self.p_order_lines.append(
            dict(order_line_id=lid, order_id=order_id, sku=sku, quantity=quantity,
                 unit_price_minor=unit_price_minor, discount_minor=discount_minor,
                 currency=currency, committed_at=committed_at_utc)
        )
        if committed_at_utc < self.as_of_utc and order_id in self.l_orders:
            exponent = CURRENCIES[currency]
            order_committed_utc = self._order_commit(order_id)
            fx_date = effective_fx_date(order_committed_utc)
            rate = Decimal("1") if currency == "EUR" else most_recent_rate(self.fx_table, currency, fx_date)
            net_minor = unit_price_minor * quantity - discount_minor
            net_eur = eur_amount(net_minor, exponent, rate)
            self.l_order_lines.append(
                dict(id=lid, order_id=order_id, sku=sku, quantity=quantity,
                     unit_price_minor=unit_price_minor, discount_minor=discount_minor,
                     currency=currency, net_eur=net_eur)
            )
            self.l_orders[order_id]["total_eur"] += net_eur
            self._recompute_status(order_id)
            self._recompute_promo(order_id)

    def add_payment(self, order_id: int, kind: str, amount_minor: int, currency: str,
                    occurred_at_utc: datetime, committed_at_utc: datetime = None):
        committed_at_utc = committed_at_utc or occurred_at_utc
        pid = self.pay_id.next()
        self.p_payment_events.append(
            dict(payment_id=pid, order_id=order_id, kind=kind,
                 amount_minor=amount_minor, currency=currency,
                 occurred_at=occurred_at_utc, committed_at=committed_at_utc)
        )
        if committed_at_utc < self.as_of_utc and order_id in self.l_orders:
            exponent = CURRENCIES[currency]
            fx_date = effective_fx_date(committed_at_utc)
            rate = Decimal("1") if currency == "EUR" else most_recent_rate(self.fx_table, currency, fx_date)
            amount_eur = eur_amount(amount_minor, exponent, rate)
            self.l_payments.append(
                dict(id=pid, order_id=order_id, kind=kind, amount_minor=amount_minor,
                     currency=currency, amount_eur=amount_eur,
                     occurred_at=occurred_at_utc.astimezone(BERLIN).replace(tzinfo=None),
                     recorded_at=committed_at_utc.astimezone(BERLIN).replace(tzinfo=None))
            )
            sums = self._order_status_sums[order_id]
            if kind == "capture":
                sums["captured"] += amount_eur
            else:
                sums["refunded"] += amount_eur
            self._recompute_status(order_id)

    def set_lifecycle(self, order_id: int, state: str, committed_at_utc: datetime):
        eid = self.lifecycle_id.next()
        self.p_order_lifecycle_events.append(
            dict(event_id=eid, order_id=order_id, state=state, committed_at=committed_at_utc)
        )
        if committed_at_utc < self.as_of_utc and order_id in self.l_orders:
            berlin_dt = committed_at_utc.astimezone(BERLIN).replace(tzinfo=None)
            self.l_order_lifecycle.append(
                dict(id=eid, order_id=order_id, state=state, changed_at=berlin_dt)
            )
            self._order_lifecycle_state[order_id] = state
            self._recompute_status(order_id)

    def _recompute_status(self, order_id: int):
        sums = self._order_status_sums[order_id]
        captured, refunded = sums["captured"], sums["refunded"]
        lifecycle = self._order_lifecycle_state[order_id]
        cust_id = self.l_orders[order_id]["customer_id"]
        is_cust_deleted = (cust_id is not None and
                           cust_id in self.l_customers and
                           self.l_customers[cust_id]["deleted_at"] is not None)

        prev_status = self.l_orders[order_id].get("status", "pending")
        if prev_status == "cancelled":
            if refunded >= captured and captured > 0:
                status = "refunded"
            elif refunded > 0:
                status = "partially_refunded"
            else:
                status = "cancelled"
            self.l_orders[order_id]["status"] = status
            return

        if refunded >= captured and captured > 0:
            status = "refunded"
        elif refunded > 0:
            status = "partially_refunded"
        elif lifecycle == "cancelled" or (is_cust_deleted and captured == 0 and lifecycle != "fulfilled"):
            status = "cancelled"
        elif lifecycle == "fulfilled":
            status = "shipped"
        elif captured > 0:
            status = "paid"
        else:
            status = "pending"
        self.l_orders[order_id]["status"] = status

    def _recompute_promo(self, order_id: int):
        if order_id not in self.l_orders:
            return
        valid_promos = [
            p for p in self.l_promo_applications
            if p["order_id"] == order_id and p["removed_at"] is None
        ]
        # Tie-breaker: sort by seq asc, then applied_at asc
        valid_promos.sort(key=lambda p: (p["seq"], p["applied_at"]))
        tot = self.l_orders[order_id]["total_eur"]
        eligible_promos = [
            p for p in valid_promos
            if not (p["promo_code"].startswith("PROMO-SAVE") and tot < Decimal("40.00"))
        ]
        self.l_orders[order_id]["promo_id"] = eligible_promos[0]["promo_code"] if eligible_promos else None

    # ---------- promos ----------
    def add_promo_application(self, order_id: int, seq: int, promo_code: str,
                              applied_at_utc: datetime, removed_at_utc: datetime = None):
        self.p_order_promo_applications.append(
            dict(order_id=order_id, seq=seq, promo_code=promo_code,
                 applied_at=applied_at_utc, removed_at=removed_at_utc)
        )
        if applied_at_utc < self.as_of_utc and order_id in self.l_orders:
            b_app = applied_at_utc.astimezone(BERLIN).replace(tzinfo=None)
            b_rem = (removed_at_utc.astimezone(BERLIN).replace(tzinfo=None)
                     if (removed_at_utc and removed_at_utc < self.as_of_utc) else None)
            self.l_promo_applications.append(
                dict(order_id=order_id, seq=seq, promo_code=promo_code,
                     applied_at=b_app, removed_at=b_rem)
            )
            self._recompute_promo(order_id)

    # ---------- shipments ----------
    def add_shipment(self, order_id: int, shipped_at_utc: datetime,
                     cancelled_at_utc: datetime = None, committed_at_utc: datetime = None):
        sid = self.shipment_id.next()
        committed_at_utc = committed_at_utc or shipped_at_utc
        self.p_shipments.append(
            dict(shipment_id=sid, order_id=order_id,
                 shipped_at=shipped_at_utc, cancelled_at=cancelled_at_utc,
                 committed_at=committed_at_utc)
        )
        if committed_at_utc < self.as_of_utc and order_id in self.l_orders:
            b_ship = shipped_at_utc.astimezone(BERLIN).replace(tzinfo=None)
            b_canc = (cancelled_at_utc.astimezone(BERLIN).replace(tzinfo=None)
                      if (cancelled_at_utc and cancelled_at_utc < self.as_of_utc) else None)
            self.l_shipments.append(
                dict(id=sid, order_id=order_id, shipped_at=b_ship, cancelled_at=b_canc)
            )

    # ---------- snapshot and write ----------
    def legacy_snapshot_and_write(self, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        customers = [{k: v for k, v in c.items() if not k.startswith("_")} for c in self.l_customers.values()]
        orders = [{k: v for k, v in o.items() if not k.startswith("_")} for o in self.l_orders.values()]
        fx_rows = [dict(date=d, currency=c, rate_to_eur=r) for (d, c), r in self.fx_table.items()]
        products = [dict(sku=p[0], name=p[1], category=p[2]) for p in PRODUCTS]

        _write(out_dir / "customers.parquet", customers)
        _write(out_dir / "orders.parquet", orders)
        _write(out_dir / "order_lines.parquet", self.l_order_lines)
        _write(out_dir / "payments.parquet", self.l_payments)
        _write(out_dir / "order_lifecycle.parquet", self.l_order_lifecycle)
        _write(out_dir / "promo_applications.parquet", self.l_promo_applications)
        _write(out_dir / "shipments.parquet", self.l_shipments)
        _write(out_dir / "products.parquet", products)
        _write(out_dir / "fx_rates.parquet", fx_rows)

    def platform_write(self, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        fx_rows = [dict(date=d, currency=c, rate_to_eur=r) for (d, c), r in self.fx_table.items()]
        currencies = [dict(code=c, exponent=e) for c, e in CURRENCIES.items()]
        products = [dict(sku=p[0], name=p[1], category=p[2]) for p in PRODUCTS]

        _write(out_dir / "customer_versions.parquet", self.p_customer_versions)
        _write(out_dir / "customer_status_events.parquet", self.p_customer_status_events)
        _write(out_dir / "orders.parquet", self.p_orders)
        _write(out_dir / "order_lines.parquet", self.p_order_lines)
        _write(out_dir / "payment_events.parquet", self.p_payment_events)
        _write(out_dir / "order_lifecycle_events.parquet", self.p_order_lifecycle_events)
        _write(out_dir / "order_promo_applications.parquet", self.p_order_promo_applications)
        _write(out_dir / "shipments.parquet", self.p_shipments)
        _write(out_dir / "products.parquet", products)
        _write(out_dir / "currencies.parquet", currencies)
        _write(out_dir / "fx_daily.parquet", fx_rows)
        _write(out_dir / "extract_meta.parquet", [dict(as_of_utc=self.as_of_utc)])


TEXT_COLUMNS = {"guest_email", "promo_id", "last_login_ip", "region", "category", "promo_code"}


def _write(path: Path, rows: list):
    if not rows:
        raise RuntimeError(f"refusing to write empty table: {path}")
    table = pa.Table.from_pylist(rows)
    for i, field in enumerate(table.schema):
        if pa.types.is_null(field.type) and field.name in TEXT_COLUMNS:
            table = table.set_column(i, field.name, pa.nulls(table.num_rows, type=pa.string()))
    pq.write_table(table, path)


def _find_two_way_split(cap_minor: int, exponent: int, rate: Decimal):
    cap_eur = eur_amount(cap_minor, exponent, rate)
    for r1 in range(1, cap_minor):
        r2 = cap_minor - r1
        e1 = eur_amount(r1, exponent, rate)
        e2 = eur_amount(r2, exponent, rate)
        if e1 + e2 == cap_eur - Decimal("0.01"):
            return r1, r2
    return None


def find_two_way_split_any(exponent: int, rate: Decimal, candidates: list):
    for cap_minor in candidates:
        got = _find_two_way_split(cap_minor, exponent, rate)
        if got:
            return cap_minor, got
    raise RuntimeError(f"no qualifying split found among candidates for rate={rate} exponent={exponent}")


# ==============================================================================
# BASELINE POPULATION (V1 - V14)
# ==============================================================================

def build_baseline(w: Window):
    """Generates baseline activity exercising all visible quirks V1-V14 in >=3 entities."""
    rng = w.rng

    # Initial customers across regions and segments
    segments = ["standard", "vip", "enterprise"]
    regions = ["EU", "US", "APAC"]
    base_customers = []
    for i in range(30):
        c_time = w.window_start - timedelta(days=20 + (i % 10))
        cid = w.add_customer(c_time, segments[i % 3], regions[i % 3], email=f"base_user_{i}@example.test")
        base_customers.append(cid)

    # Regular orders with varied statuses, currencies, and products
    status_cycle = ["pending", "paid", "shipped", "cancelled", "partially_refunded", "refunded"]
    curr_cycle = ["EUR", "USD", "GBP", "JPY", "KWD"]

    for i in range(60):
        cust = base_customers[i % len(base_customers)]
        currency = curr_cycle[i % len(curr_cycle)]
        plan = status_cycle[i % len(status_cycle)]
        sku = SKU_KEYS[i % len(SKU_KEYS)]
        # Committed in the evening (18:00 - 22:00 Berlin time) so that on sample,
        # effective_fx_date (with 16:00 cutoff) and standard berlin_date are 100% identical.
        committed = w.as_of_utc - timedelta(days=5 + (i % 35), hours=2 + (i % 5), minutes=15 * (i % 4))

        oid = w.add_order(cust, committed)
        price_minor = 3500 + (i * 123) % 4000
        w.add_line(oid, sku, 2, price_minor, 500, currency, committed)
        cap_minor = 2 * price_minor - 500

        if plan == "pending":
            continue

        w.add_payment(oid, "capture", cap_minor, currency, committed, committed)
        if plan == "paid":
            pass
        elif plan == "shipped":
            w.set_lifecycle(oid, "fulfilled", committed + timedelta(days=1))
            w.add_shipment(oid, committed + timedelta(days=1))
        elif plan == "cancelled":
            w.set_lifecycle(oid, "cancelled", committed + timedelta(hours=3))
        elif plan == "partially_refunded":
            ref_minor = cap_minor // 2
            # For sample: at most 1 refund on non-EUR orders!
            w.add_payment(oid, "refund", ref_minor, currency, committed + timedelta(days=2), committed + timedelta(days=2))
        elif plan == "refunded":
            # For sample: exactly 1 refund, same-day so same FX rate -> minor-unit and EUR status agree!
            w.add_payment(oid, "refund", cap_minor, currency, committed + timedelta(hours=2), committed + timedelta(hours=2))

    # V1: platform tail (+1 to +5h after as_of_utc)
    for i in range(4):
        cid = base_customers[i]
        tail_time = w.as_of_utc + timedelta(hours=1 + i)
        toid = w.add_order(cid, tail_time)
        w.add_line(toid, SKU_KEYS[0], 1, 4000, 0, "EUR", tail_time)
        w.add_payment(toid, "capture", 4000, "EUR", tail_time, tail_time)

    # V2: subscription renewal orders committed EXACTLY at as_of_utc
    for i in range(4):
        cid = base_customers[5 + i]
        exact_time = w.as_of_utc
        roid = w.add_order(cid, exact_time)
        w.add_line(roid, SKU_KEYS[1], 1, 6000, 0, "EUR", exact_time)
        w.add_payment(roid, "capture", 6000, "EUR", exact_time, exact_time)

    # V3: segment changes mid-window with orders on both sides
    for i in range(4):
        cid = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU", email=f"v3_user_{i}@example.test")
        pre_time = w.as_of_utc - timedelta(days=20 + i)
        o1 = w.add_order(cid, pre_time)
        w.add_line(o1, SKU_KEYS[0], 1, 5000, 0, "EUR", pre_time)
        w.add_payment(o1, "capture", 5000, "EUR", pre_time, pre_time)

        chg_time = w.as_of_utc - timedelta(days=10 + i)
        w.change_segment(cid, chg_time, "vip", "EU")

        post_time = w.as_of_utc - timedelta(days=3 + i)
        o2 = w.add_order(cid, post_time)
        w.add_line(o2, SKU_KEYS[1], 1, 5000, 0, "EUR", post_time)
        w.add_payment(o2, "capture", 5000, "EUR", post_time, post_time)

    # V4: Berlin wall-clock crosses UTC day boundary (e.g. 22:30 UTC -> 00:30 next Berlin day)
    for i in range(4):
        cid = w.add_customer(w.window_start - timedelta(days=10), "standard", "US", email=f"v4_user_{i}@example.test")
        v4_time = (w.as_of_utc - timedelta(days=8 + i)).replace(hour=22, minute=30, second=0, microsecond=0)
        void = w.add_order(cid, v4_time)
        w.add_line(void, SKU_KEYS[2], 1, 4500, 0, "EUR", v4_time)
        w.add_payment(void, "capture", 4500, "EUR", v4_time, v4_time)

    # V5: per-line rounding vs sum-then-round, non-EUR, 2 lines each, plus half-even tie
    for i in range(4):
        cid = w.add_customer(w.window_start - timedelta(days=10), "standard", "EU", email=f"v5_user_{i}@example.test")
        v5_time = w.as_of_utc - timedelta(days=12 + i, hours=4)
        v5_oid = w.add_order(cid, v5_time)
        # Line 1 & Line 2: 1001 and 1003 minor units GBP -> sum-then-round gives 16.83, rounded lines sum gives 16.84
        w.add_line(v5_oid, SKU_KEYS[0], 1, 1001, 0, "GBP", v5_time)
        w.add_line(v5_oid, SKU_KEYS[1], 1, 1003, 0, "GBP", v5_time)
        # Line 3: 100 minor units KWD at 3.05 -> 0.305 -> half-even rounds to 0.30, round-away-from-zero rounds to 0.31
        w.add_line(v5_oid, SKU_KEYS[2], 1, 100, 0, "KWD", v5_time)
        w.add_payment(v5_oid, "capture", 2004, "GBP", v5_time, v5_time)

    # V7: unmatched guest checkout
    for i in range(4):
        g_time = w.as_of_utc - timedelta(days=7 + i, hours=6)
        g_oid = w.add_guest_order(f"unmatched_guest_{i}@nowhere.test", g_time)
        w.add_line(g_oid, SKU_KEYS[0], 1, 3000, 0, "EUR", g_time)
        w.add_payment(g_oid, "capture", 3000, "EUR", g_time, g_time)

    # V8: deleted customers (orders survive, customer row dropped)
    for i in range(4):
        del_cid = w.add_customer(w.window_start - timedelta(days=10), "standard", "EU", email=f"deleted_v8_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=14 + i)
        d_oid = w.add_order(del_cid, ord_time)
        w.add_line(d_oid, SKU_KEYS[0], 1, 5500, 0, "EUR", ord_time)
        w.add_payment(d_oid, "capture", 5500, "EUR", ord_time, ord_time)
        del_time = w.as_of_utc - timedelta(days=6 + i)
        w.delete_customer(del_cid, del_time)

    # V9: deleted then restored customers (included in customers)
    for i in range(4):
        res_cid = w.add_customer(w.window_start - timedelta(days=10), "standard", "EU", email=f"restored_v9_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=15 + i)
        r_oid = w.add_order(res_cid, ord_time)
        w.add_line(r_oid, SKU_KEYS[1], 1, 4200, 0, "EUR", ord_time)
        w.add_payment(r_oid, "capture", 4200, "EUR", ord_time, ord_time)
        w.delete_customer(res_cid, w.as_of_utc - timedelta(days=10 + i))
        w.restore_customer(res_cid, w.as_of_utc - timedelta(days=4 + i))

    # V10: duplicate accounts (same email ignoring case), lowest active id canonical
    # In sample: duplicate groups NEVER contain a deleted member!
    for i in range(4):
        email_base = f"dupe_v10_{i}@example.test"
        id_a = 5000 + i * 10
        id_b = 5000 + i * 10 + 1
        w.add_customer(w.window_start - timedelta(days=12), "standard", "EU", email=email_base.lower(), cust_id=id_a)
        w.add_customer(w.window_start - timedelta(days=11), "standard", "EU", email=email_base.upper(), cust_id=id_b)
        # Orders for both accounts
        t_ord = w.as_of_utc - timedelta(days=8 + i)
        oa = w.add_order(id_a, t_ord)
        w.add_line(oa, SKU_KEYS[0], 1, 2500, 0, "EUR", t_ord)
        w.add_payment(oa, "capture", 2500, "EUR", t_ord, t_ord)
        ob = w.add_order(id_b, t_ord + timedelta(hours=1))
        w.add_line(ob, SKU_KEYS[1], 1, 3500, 0, "EUR", t_ord + timedelta(hours=1))
        w.add_payment(ob, "capture", 3500, "EUR", t_ord + timedelta(hours=1), t_ord + timedelta(hours=1))

    # V11: guest orders whose typed email matches a customer email
    # In sample: casing is EXACT MATCH!
    for i in range(4):
        target_cust = base_customers[10 + i]
        cust_email = next(v["email"] for v in w.p_customer_versions if v["customer_id"] == target_cust)
        g_time = w.as_of_utc - timedelta(days=9 + i)
        g_oid = w.add_guest_order(cust_email, g_time) # exact case match
        w.add_line(g_oid, SKU_KEYS[2], 1, 4800, 0, "EUR", g_time)
        w.add_payment(g_oid, "capture", 4800, "EUR", g_time, g_time)

    # V12: promo applications: first non-removed application by seq
    for i in range(4):
        cust = base_customers[15 + i]
        p_time = w.as_of_utc - timedelta(days=11 + i)
        p_oid = w.add_order(cust, p_time)
        w.add_line(p_oid, SKU_KEYS[0], 1, 5000, 500, "EUR", p_time)
        w.add_payment(p_oid, "capture", 4500, "EUR", p_time, p_time)
        # Promo 1 (seq=1) applied and removed
        w.add_promo_application(p_oid, 1, "PROMO-OLD", p_time, p_time + timedelta(minutes=10))
        # Promo 2 (seq=2) applied and kept
        w.add_promo_application(p_oid, 2, "PROMO-SAVE10", p_time + timedelta(minutes=15), None)

    # V13: shipments: first non-cancelled shipment
    for i in range(4):
        cust = base_customers[20 + i]
        s_time = w.as_of_utc - timedelta(days=13 + i)
        s_oid = w.add_order(cust, s_time)
        w.add_line(s_oid, SKU_KEYS[3], 1, 6000, 0, "EUR", s_time)
        w.add_payment(s_oid, "capture", 6000, "EUR", s_time, s_time)
        w.set_lifecycle(s_oid, "fulfilled", s_time + timedelta(days=2))
        # Shipment 1: cancelled
        w.add_shipment(s_oid, s_time + timedelta(days=1), cancelled_at_utc=s_time + timedelta(days=1, hours=2))
        # Shipment 2: valid, shipped later
        w.add_shipment(s_oid, s_time + timedelta(days=2), cancelled_at_utc=None)

    # V14: payment FX date is commit date, not occurred_at date
    # Both occ (day D-1 at 20:00 Berlin) and comm (day D at 20:00 Berlin) occur after 16:00 Berlin time.
    for i in range(4):
        cid = w.add_customer(w.window_start - timedelta(days=10), "standard", "EU", email=f"v14_user_{i}@example.test")
        occ = w.as_of_utc - timedelta(days=6 + i, hours=28)
        comm = w.as_of_utc - timedelta(days=6 + i, hours=4)
        v14_oid = w.add_order(cid, occ)
        w.add_line(v14_oid, SKU_KEYS[0], 1, 10000, 0, "USD", occ)
        w.add_payment(v14_oid, "capture", 10000, "USD", occ, comm)


# ==============================================================================
# SILENT TRAPS INJECTIONS (S1 - S6) & LURE (L1)
# ==============================================================================

def inject_s1(w: Window, count: int = 5):
    """S1: non-EUR order with >=2 same-day refunds whose rounded sum is 1 cent below capture."""
    candidates = [4321, 5114, 7331, 9973, 12500, 6543, 8765, 11111, 15432, 3210]
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU", email=f"s1_user_{w.name}_{i}@example.test")
        committed = w.as_of_utc - timedelta(days=6 + (i % 10), hours=11)
        currency = "KWD" if (i % 2 == 0) else "GBP"
        berlin_date = committed.astimezone(BERLIN).date()
        rate = most_recent_rate(w.fx_table, currency, berlin_date)
        cap_minor, (r1, r2) = find_two_way_split_any(CURRENCIES[currency], rate, candidates)

        oid = w.add_order(cust, committed)
        w.add_line(oid, SKU_KEYS[0], 1, cap_minor, 0, currency, committed)
        w.add_payment(oid, "capture", cap_minor, currency, committed, committed)
        w.add_payment(oid, "refund", r1, currency, committed + timedelta(hours=2), committed + timedelta(hours=2))
        w.add_payment(oid, "refund", r2, currency, committed + timedelta(hours=2), committed + timedelta(hours=2))


def inject_s2(w: Window, count: int = 6):
    """S2: customer version with valid_from == as_of_utc exactly."""
    for i in range(count):
        cust = w.add_customer(w.as_of_utc - timedelta(days=25 + i), "standard", "EU", email=f"s2_user_{w.name}_{i}@example.test")
        pre_time = w.as_of_utc - timedelta(hours=2)
        oid = w.add_order(cust, pre_time)
        w.add_line(oid, SKU_KEYS[0], 1, 5000, 0, "EUR", pre_time)
        w.add_payment(oid, "capture", 5000, "EUR", pre_time, pre_time)
        # Scheduled segment change at exact boundary
        w.change_segment(cust, w.as_of_utc, "vip", "EU")


def inject_s3(w: Window, count: int = 4):
    """S3: scheduled customer reactivation committed exactly at as_of_utc."""
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU", email=f"s3_user_{w.name}_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=10 + i)
        oid = w.add_order(cust, ord_time)
        w.add_line(oid, SKU_KEYS[1], 1, 6500, 0, "EUR", ord_time)
        w.add_payment(oid, "capture", 6500, "EUR", ord_time, ord_time)

        # Deleted earlier
        w.delete_customer(cust, w.as_of_utc - timedelta(days=5))
        # Scheduled restore at EXACT extract instant
        w.restore_customer(cust, w.as_of_utc)


def inject_s4(w: Window, count: int = 5):
    """S4: duplicate accounts where lowest id is deleted, higher id is active."""
    for i in range(count):
        email_base = f"s4_dupe_{w.name}_{i}@example.test"
        low_id = 7000 + i * 20
        high_id = 7000 + i * 20 + 5
        w.add_customer(w.window_start - timedelta(days=20), "standard", "EU", email=email_base.lower(), cust_id=low_id)
        w.add_customer(w.window_start - timedelta(days=18), "vip", "EU", email=email_base.upper(), cust_id=high_id)

        # Orders placed under low_id while active
        t_ord = w.as_of_utc - timedelta(days=14 + i)
        oid = w.add_order(low_id, t_ord)
        w.add_line(oid, SKU_KEYS[2], 1, 4000, 0, "EUR", t_ord)
        w.add_payment(oid, "capture", 4000, "EUR", t_ord, t_ord)

        # Lower id deleted LATER
        w.delete_customer(low_id, w.as_of_utc - timedelta(days=10))


def inject_s5(w: Window, count: int = 7):
    """S5: guest email differs in case from customer account."""
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU", email=f"s5_cust_{w.name}_{i}@domain.test")
        c_email = f"S5_Cust_{w.name}_{i}@DOMAIN.test" # Differing case!
        g_time = w.as_of_utc - timedelta(days=5 + i)
        g_oid = w.add_guest_order(c_email, g_time)
        w.add_line(g_oid, SKU_KEYS[0], 1, 3300, 0, "EUR", g_time)
        w.add_payment(g_oid, "capture", 3300, "EUR", g_time, g_time)


def inject_s6_holiday(w: Window, holiday_date: date, count: int = 12):
    """S6: payments / lines committed on a weekday TARGET holiday date."""
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=10), "standard", "EU", email=f"s6_{holiday_date.isoformat()}_{i}@example.test")
        comm = berlin_midnight_utc(holiday_date) + timedelta(hours=10 + (i % 6), minutes=15 * (i % 4))
        cur = "GBP" if (i % 3 == 0) else ("USD" if i % 3 == 1 else "KWD")
        oid = w.add_order(cust, comm)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 15000 + i * 200, 0, cur, comm)
        w.add_payment(oid, "capture", 15000 + i * 200, cur, comm, comm)


def inject_l1(w: Window, count: int = 4):
    """L1: autumn DST fall-back hour (2025-10-26). Order A at 00:45 UTC (02:45 CEST); Order B at 01:15 UTC (02:15 CET)."""
    # 2025-10-26: Berlin switches from CEST (UTC+2) to CET (UTC+1) at 03:00 local time (01:00 UTC).
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU", email=f"l1_user_{i}@example.test")
        # Order A: 00:45 UTC = 02:45 CEST (+2)
        time_a = datetime(2025, 10, 26, 0, 45, 0, tzinfo=UTC)
        # Order B: 01:15 UTC = 02:15 CET (+1)
        time_b = datetime(2025, 10, 26, 1, 15, 0, tzinfo=UTC)

        oa = w.add_order(cust, time_a)
        w.add_line(oa, SKU_KEYS[0], 1, 5000, 0, "EUR", time_a)
        w.add_payment(oa, "capture", 5000, "EUR", time_a, time_a)

        ob = w.add_order(cust, time_b)
        w.add_line(ob, SKU_KEYS[1], 1, 7000, 0, "EUR", time_b)
        w.add_payment(ob, "capture", 7000, "EUR", time_b, time_b)


def inject_s7_daytime_fx(w: Window, count: int = 8):
    """S7: non-EUR orders/payments committed before 16:00 Berlin time.
    Under 16:00 cutoff rule, effective FX date is D-1. Naive uses D.
    """
    candidates = ["USD", "GBP", "JPY", "KWD"]
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=12), "standard", "EU", email=f"s7_user_{w.name}_{i}@example.test")
        comm = (w.as_of_utc - timedelta(days=7 + i)).replace(hour=8, minute=30, second=0, microsecond=0)
        currency = candidates[i % len(candidates)]
        oid = w.add_order(cust, comm)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 8000 + i * 150, 0, currency, comm)
        w.add_payment(oid, "capture", 8000 + i * 150, currency, comm, comm)


def inject_s8_deletion_pending(w: Window, count: int = 6):
    """S8: deleted customers with unpaid pending orders.
    Under deletion cascade rule, orders are marked 'cancelled'. Naive outputs 'pending'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU", email=f"s8_del_user_{w.name}_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=8 + i, hours=3)
        oid = w.add_order(cust, ord_time)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 5000 + i * 200, 0, "EUR", ord_time)
        del_time = w.as_of_utc - timedelta(days=3 + i, hours=2)
        w.delete_customer(cust, del_time)


def inject_s9_tail_promo(w: Window, count: int = 6):
    """S9: promo applications removed in the +6h platform tail after as_of_utc.
    To the extract, promo was still active. Naive WHERE removed_at IS NULL drops it.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=10), "standard", "EU", email=f"s9_promo_user_{w.name}_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=4 + i, hours=5)
        oid = w.add_order(cust, ord_time)
        w.add_line(oid, SKU_KEYS[0], 1, 4000, 0, "EUR", ord_time)
        w.add_payment(oid, "capture", 4000, "EUR", ord_time, ord_time)
        app_time = ord_time + timedelta(minutes=5)
        rem_time = w.as_of_utc + timedelta(hours=1 + (i % 4), minutes=15)
        w.add_promo_application(oid, 1, f"PROMO-TAIL-{i}", app_time, rem_time)


def inject_s11(w: Window, count: int = 4):
    """S11: composite cluster stacking V10/S4 (3-way dedupe group, lowest id permanently
    deleted, mid id restored exactly at as_of_utc so it is STILL deleted as of the extract),
    S5 (guest order email case-differs from the canonical account's registered email),
    S9 (promo removed in the platform tail), S10 (shipment cancelled in the platform tail),
    and S1 (non-EUR order with two same-day refunds, per-payment half-even rounding) all
    resolving onto the SAME canonical customer. Any rule handled correctly in isolation but
    not compositionally (e.g. dedupe computed before the active-filter, or guest-linking
    that doesn't reuse the same canonical-account resolution as dedupe) fails here.
    """
    candidates = [4321, 5114, 7331, 9973, 12500, 6543, 8765, 11111, 15432, 3210]
    for i in range(count):
        email_base = f"s11_mega_{w.name}_{i}@example.test"
        id_low = 9000 + i * 30
        id_mid = 9000 + i * 30 + 10
        id_high = 9000 + i * 30 + 20

        w.add_customer(w.window_start - timedelta(days=25), "standard", "EU",
                       email=email_base, cust_id=id_low)

        w.add_customer(w.window_start - timedelta(days=24), "standard", "EU",
                       email=email_base.upper(), cust_id=id_mid)

        w.add_customer(w.window_start - timedelta(days=23), "vip", "EU",
                       email=email_base, cust_id=id_high)  # only active member -> canonical

        # order under lowest id (placed while active)
        t1 = w.as_of_utc - timedelta(days=18 + i)
        o1 = w.add_order(id_low, t1)
        w.add_line(o1, SKU_KEYS[0], 1, 4200, 0, "EUR", t1)
        w.add_payment(o1, "capture", 4200, "EUR", t1, t1)
        w.add_promo_application(o1, 1, f"PROMO-S11-{w.name}-{i}", t1 + timedelta(minutes=5),
                                w.as_of_utc + timedelta(hours=1 + i % 4))  # removed in tail

        w.delete_customer(id_low, w.as_of_utc - timedelta(days=15))

        # order under mid id (placed while active)
        t2 = w.as_of_utc - timedelta(days=12 + i)
        o2 = w.add_order(id_mid, t2)
        w.add_line(o2, SKU_KEYS[1], 1, 4800, 0, "EUR", t2)
        w.add_payment(o2, "capture", 4800, "EUR", t2, t2)
        w.set_lifecycle(o2, "fulfilled", t2 + timedelta(days=1))
        w.add_shipment(o2, t2 + timedelta(days=1),
                       cancelled_at_utc=w.as_of_utc + timedelta(hours=2 + i % 3))  # cancelled in tail

        w.delete_customer(id_mid, w.as_of_utc - timedelta(days=9))
        w.restore_customer(id_mid, w.as_of_utc)  # exact-instant restore: still deleted as of extract

        # guest order whose typed email case-differs from id_high's registered email
        g_time = t2 + timedelta(hours=3)
        g_oid = w.add_guest_order(email_base.upper(), g_time)
        w.add_line(g_oid, SKU_KEYS[2], 1, 3300, 0, "EUR", g_time)
        w.add_payment(g_oid, "capture", 3300, "EUR", g_time, g_time)

        # order under id_high itself: non-EUR, two same-day refunds, per-payment half-even sum
        currency = "KWD" if i % 2 == 0 else "GBP"
        t3 = w.as_of_utc - timedelta(days=20 + i, hours=11)
        berlin_date3 = t3.astimezone(BERLIN).date()
        rate3 = most_recent_rate(w.fx_table, currency, berlin_date3)
        cap_minor, (r1, r2) = find_two_way_split_any(CURRENCIES[currency], rate3, candidates)
        o3 = w.add_order(id_high, t3)
        w.add_line(o3, SKU_KEYS[3], 1, cap_minor, 0, currency, t3)
        w.add_payment(o3, "capture", cap_minor, currency, t3, t3)
        w.add_payment(o3, "refund", r1, currency, t3 + timedelta(hours=2), t3 + timedelta(hours=2))
        w.add_payment(o3, "refund", r2, currency, t3 + timedelta(hours=2), t3 + timedelta(hours=2))


def inject_s12(w: Window, count: int = 4):
    """S12: composite stacking S7 (payment committed before 16:00 Berlin -> prior business
    day's FX rate), S9 (promo removed in the platform tail), and S2 (a scheduled segment
    change that lands exactly at as_of_utc, so it is not yet visible) on the same order.
    """
    candidates = ["USD", "GBP", "JPY", "KWD"]
    for i in range(count):
        cust = w.add_customer(w.as_of_utc - timedelta(days=22 + i), "standard", "EU",
                              email=f"s12_user_{w.name}_{i}@example.test")
        currency = candidates[i % len(candidates)]
        comm = (w.as_of_utc - timedelta(days=9 + i)).replace(hour=9, minute=30, second=0, microsecond=0)
        oid = w.add_order(cust, comm)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 7000 + i * 175, 0, currency, comm)
        w.add_payment(oid, "capture", 7000 + i * 175, currency, comm, comm)
        w.add_promo_application(oid, 1, f"PROMO-S12-{w.name}-{i}", comm + timedelta(minutes=5),
                                w.as_of_utc + timedelta(hours=1 + i % 4))
        # scheduled segment change lands exactly at extract instant -> not yet visible
        w.change_segment(cust, w.as_of_utc, "vip", "EU")


def inject_s13(w: Window, count: int = 6):
    """S13: an order whose capture and refund payments use DIFFERENT currencies.
    payment_events.currency is already a per-row field (platform.md), and per-payment
    rounding/FX resolution is already stated as per-row (app-rules.md), but nothing before
    this exercised a capture and a refund on the same order actually differing -- a solution
    that resolves currency/exponent/FX rate once per order instead of once per payment row
    is indistinguishable from a correct one until this combination appears.
    """
    pairs = [("EUR", "GBP"), ("USD", "JPY"), ("GBP", "KWD"), ("JPY", "USD"), ("KWD", "EUR"), ("GBP", "USD")]
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=14), "standard", "EU",
                              email=f"s13_user_{w.name}_{i}@example.test")
        cap_cur, ref_cur = pairs[i % len(pairs)]
        t = w.as_of_utc - timedelta(days=16 + i, hours=20)
        oid = w.add_order(cust, t)
        cap_minor = 5000 + i * 137
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, cap_minor, 0, cap_cur, t)
        w.add_payment(oid, "capture", cap_minor, cap_cur, t, t)
        ref_minor = 1200 + i * 41
        w.add_payment(oid, "refund", ref_minor, ref_cur, t + timedelta(days=1), t + timedelta(days=1))


def inject_s10_tail_shipment(w: Window, count: int = 6):
    """S10: shipments cancelled in the +6h platform tail after as_of_utc.
    To the extract, shipment was not yet cancelled. Naive WHERE cancelled_at IS NULL drops it.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=10), "standard", "EU", email=f"s10_ship_user_{w.name}_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=5 + i, hours=6)
        oid = w.add_order(cust, ord_time)
        w.add_line(oid, SKU_KEYS[1], 1, 6000, 0, "EUR", ord_time)
        w.add_payment(oid, "capture", 6000, "EUR", ord_time, ord_time)
        w.set_lifecycle(oid, "fulfilled", ord_time + timedelta(days=1))
        ship_time = ord_time + timedelta(days=1)
        canc_time = w.as_of_utc + timedelta(hours=1 + (i % 4), minutes=30)
        w.add_shipment(oid, ship_time, cancelled_at_utc=canc_time)


def inject_s14_deletion_restoration_order_cancelled(w: Window, count: int = 6):
    """S14: Customer deleted while having an unpaid pending order, then later restored.
    The order transitioned to 'cancelled' upon deletion and remains 'cancelled'.
    Naive agent queries latest customer status (which is 'restored') and outputs 'pending'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU",
                              email=f"s14_restored_{w.name}_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=12 + i, hours=4)
        oid = w.add_order(cust, ord_time)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 5200 + i * 150, 0, "EUR", ord_time)
        del_time = w.as_of_utc - timedelta(days=7 + i, hours=2)
        w.delete_customer(cust, del_time)
        res_time = w.as_of_utc - timedelta(days=2 + (i % 3), hours=1)
        w.restore_customer(cust, res_time)


def inject_s15_reshipment_tail_cancel(w: Window, count: int = 6):
    """S15: Order has Shipment 1 and Shipment 2 (replacement).
    Shipment 1 was cancelled in the +6h platform tail after as_of_utc.
    In legacy snapshot, Shipment 1 was active and had an earlier shipped_at than Shipment 2.
    Legacy min(shipped_at) selects Shipment 1.
    Naive agent filters WHERE cancelled_at IS NULL on platform, dropping Shipment 1 and selecting Shipment 2.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=16), "standard", "EU",
                              email=f"s15_ship_{w.name}_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=10 + i, hours=5)
        oid = w.add_order(cust, ord_time)
        w.add_line(oid, SKU_KEYS[2], 1, 6500, 0, "EUR", ord_time)
        w.add_payment(oid, "capture", 6500, "EUR", ord_time, ord_time)
        w.set_lifecycle(oid, "fulfilled", ord_time + timedelta(days=1))
        ship1_time = ord_time + timedelta(days=1)
        tail_cancel = w.as_of_utc + timedelta(hours=1 + (i % 4), minutes=20)
        w.add_shipment(oid, ship1_time, cancelled_at_utc=tail_cancel)
        ship2_time = ord_time + timedelta(days=2)
        w.add_shipment(oid, ship2_time, cancelled_at_utc=None)


def inject_s16_email_rename_guest_link(w: Window, count: int = 6):
    """S16: Customer created with email_old, later changed profile email to email_new.
    A guest checkout uses email_old.
    In legacy operational DB, op_customers only holds email_new, so the guest order
    has no match in op_customers and maps to customer_id = 0 (unmatched guest).
    A naive agent joining guest_email to customer_versions without restricting to the
    active version at extract matches email_old and links the order to the customer.
    """
    for i in range(count):
        cid = w.add_customer(w.window_start - timedelta(days=25), "standard", "EU",
                             email=f"s16_old_{w.name}_{i}@domain.test")
        chg_time = w.as_of_utc - timedelta(days=15 + i)
        prior = next(v for v in w.p_customer_versions
                     if v["customer_id"] == cid and v["valid_to"] is None)
        prior["valid_to"] = chg_time
        new_email = f"s16_new_{w.name}_{i}@domain.test"
        w.p_customer_versions.append(
            dict(customer_id=cid, email=new_email, segment="standard", region="EU",
                 valid_from=chg_time, valid_to=None)
        )
        if chg_time < w.as_of_utc and cid in w.l_customers:
            w.l_customers[cid]["email"] = new_email

        g_time = w.as_of_utc - timedelta(days=8 + i)
        g_oid = w.add_guest_order(f"s16_old_{w.name}_{i}@domain.test", g_time)
        w.add_line(g_oid, SKU_KEYS[1], 1, 4100 + i * 100, 0, "EUR", g_time)
        w.add_payment(g_oid, "capture", 4100 + i * 100, "EUR", g_time, g_time)


def inject_s17_all_deleted_duplicate_group(w: Window, count: int = 5):
    """S17: Duplicate account group where ALL members are deleted.
    In legacy, _customer_canonical filters WHERE deleted_at IS NULL, producing 0 rows.
    Neither account is canonical, no orders are remapped, and the cluster is excluded
    from mart_duplicate_customers.
    A naive agent deduplicating customer_versions without filtering deleted accounts first
    creates a canonical group, remaps orders, and counts the group in mart_duplicate_customers.
    """
    for i in range(count):
        email_base = f"s17_alldel_{w.name}_{i}@example.test"
        id1 = 11000 + i * 20
        id2 = 11000 + i * 20 + 5
        w.add_customer(w.window_start - timedelta(days=22), "standard", "EU", email=email_base, cust_id=id1)
        w.add_customer(w.window_start - timedelta(days=21), "standard", "EU", email=email_base.upper(), cust_id=id2)

        # Orders placed while accounts active
        t_ord1 = w.as_of_utc - timedelta(days=16 + i)
        o1 = w.add_order(id1, t_ord1)
        w.add_line(o1, SKU_KEYS[0], 1, 3800, 0, "EUR", t_ord1)
        w.add_payment(o1, "capture", 3800, "EUR", t_ord1, t_ord1)

        t_ord2 = w.as_of_utc - timedelta(days=15 + i)
        o2 = w.add_order(id2, t_ord2)
        w.add_line(o2, SKU_KEYS[1], 1, 4600, 0, "EUR", t_ord2)
        w.add_payment(o2, "capture", 4600, "EUR", t_ord2, t_ord2)

        # Both deleted AFTER orders placed and paid
        w.delete_customer(id1, w.as_of_utc - timedelta(days=10 + i))
        w.delete_customer(id2, w.as_of_utc - timedelta(days=9 + i))


def inject_s18_tail_restored_duplicate_group(w: Window, count: int = 5):
    """S18: Duplicate group where lower id was deleted and only restored in the +6h platform tail.
    Higher id is active throughout.
    As of as_of_utc, lower id was STILL deleted, so higher id was the SOLE active account
    and therefore the canonical account.
    Naive agent inspecting customer_status_events without committed_at < as_of_utc sees lower id
    active and incorrectly selects lower id as canonical.
    """
    for i in range(count):
        email_base = f"s18_tailres_{w.name}_{i}@example.test"
        id_low = 12000 + i * 20
        id_high = 12000 + i * 20 + 5
        w.add_customer(w.window_start - timedelta(days=24), "standard", "EU", email=email_base.lower(), cust_id=id_low)
        w.add_customer(w.window_start - timedelta(days=22), "vip", "EU", email=email_base.upper(), cust_id=id_high)

        # Order placed while low id is active
        t_ord = w.as_of_utc - timedelta(days=14 + i)
        o = w.add_order(id_low, t_ord)
        w.add_line(o, SKU_KEYS[2], 1, 5500, 0, "EUR", t_ord)
        w.add_payment(o, "capture", 5500, "EUR", t_ord, t_ord)

        # Deleted after order placed and paid
        w.delete_customer(id_low, w.as_of_utc - timedelta(days=10 + i))
        # Restored in the tail
        w.restore_customer(id_low, w.as_of_utc + timedelta(hours=2 + i % 3))


def inject_s19_order_line_fx_order_timestamp(w: Window, count: int = 6):
    """S19: Order placed strictly before 16:00 Berlin time (effective rate is D-1),
    but order lines committed at or after 16:00 Berlin time (effective rate would be D).
    Under app-rules.md: "using the line's own currency and the order's Berlin commit
    timestamp and publication cutoff rule (an order's lines all share the order's commit
    timestamp)."
    Legacy operational writer evaluates FX rate at the order's commit timestamp (D-1).
    A naive agent using l.committed_at picks rate date D, producing divergent net_eur.
    """
    currencies = ["USD", "GBP", "JPY", "KWD"]
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU",
                              email=f"s19_linefx_{w.name}_{i}@example.test")
        cur = currencies[i % len(currencies)]
        base_day = (w.as_of_utc - timedelta(days=8 + i)).astimezone(BERLIN).date()
        # Order placed at 15:59:45 Berlin time -> strictly before 16:00, effective FX date is D-1
        t_order_berlin = datetime(base_day.year, base_day.month, base_day.day, 15, 59, 45, tzinfo=BERLIN)
        t_order = t_order_berlin.astimezone(UTC)
        oid = w.add_order(cust, t_order)
        # Line committed at 16:00:15 Berlin time (30s later -> after 16:00, naive date is D)
        t_line_berlin = datetime(base_day.year, base_day.month, base_day.day, 16, 0, 15, tzinfo=BERLIN)
        t_line = t_line_berlin.astimezone(UTC)
        price_minor = 8500 + i * 250
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, price_minor, 0, cur, committed_at_utc=t_line)
        w.add_payment(oid, "capture", price_minor, cur, t_line, t_line)


def inject_s20_deletion_late_payment(w: Window, count: int = 6):
    """S20: Customer deleted while having an unpaid pending order (order transitions to
    cancelled per rule 3). Subsequently, a late capture payment is recorded.
    Under app-rules.md: "Order cancellation is a terminal lifecycle state: once an order
    transitions to cancelled, it remains cancelled".
    Legacy operational orders.status remains 'cancelled'.
    A naive agent evaluating status on static aggregate sums checks captured > 0 and outputs 'paid'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU",
                              email=f"s20_latepay_{w.name}_{i}@example.test")
        ord_time = w.as_of_utc - timedelta(days=12 + i, hours=6)
        oid = w.add_order(cust, ord_time)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 5500 + i * 180, 0, "EUR", ord_time)
        # Deleted while unpaid and unfulfilled -> order becomes cancelled
        del_time = w.as_of_utc - timedelta(days=8 + i, hours=2)
        w.delete_customer(cust, del_time)
        # Late capture payment recorded AFTER deletion
        late_pay_time = w.as_of_utc - timedelta(days=4 + (i % 3), hours=1)
        w.add_payment(oid, "capture", 5500 + i * 180, "EUR", late_pay_time, late_pay_time)


def inject_s22_multi_day_refund_fx_drift(w: Window, count: int = 6):
    """S22: Non-EUR order with a full refund in foreign currency recorded days later.
    Because the FX rate fluctuates between capture and refund dates, the sum of recorded
    amount_eur for refund payments is strictly less than the captured amount_eur.
    Under app-rules.md:
      1. refunded -- if refunded >= captured and captured > 0.
      2. partially_refunded -- if refunded > 0 (and rule 1 did not match).
    Because refunded_eur < captured_eur, orders.status is 'partially_refunded'.
    A naive agent comparing minor units or inferring status from provider refund type outputs 'refunded'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU",
                              email=f"s22_drift_{w.name}_{i}@example.test")
        cur = "USD" if (i % 2 == 0) else "GBP"
        t_cap = (w.as_of_utc - timedelta(days=15 + i)).replace(hour=18, minute=0, second=0, microsecond=0)
        d_cap = effective_fx_date(t_cap)
        rate_cap = most_recent_rate(w.fx_table, cur, d_cap)
        t_ref = None
        for offset in range(1, 10):
            cand_t = t_cap + timedelta(days=offset)
            cand_d = effective_fx_date(cand_t)
            cand_rate = most_recent_rate(w.fx_table, cur, cand_d)
            if cand_rate < rate_cap:
                t_ref = cand_t
                break
        if t_ref is None:
            t_ref = t_cap + timedelta(days=1)

        cap_minor = 10000 + i * 500
        oid = w.add_order(cust, t_cap)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, cap_minor, 0, cur, t_cap)
        w.add_payment(oid, "capture", cap_minor, cur, t_cap, t_cap)
        w.add_payment(oid, "refund", cap_minor, cur, t_ref, t_ref)


def inject_s23_duplicate_account_deletion_isolation(w: Window, count: int = 5):
    """S23: Duplicate customer cluster (Account A active, Account B deleted).
    Both accounts placed orders while active.
    Order A placed by Account A: unpaid, Account A never deleted -> status is 'pending'.
    Order B placed by Account B: unpaid, Account B was deleted -> status is 'cancelled'.
    In legacy extract, orders remap to Account A's canonical_id.
    A naive agent checking customer deletion on canonical customer_id either incorrectly cancels
    Order A or fails to cancel Order B.
    """
    for i in range(count):
        email_base = f"s23_dupe_{w.name}_{i}@example.test"
        id_a = 13000 + i * 20
        id_b = 13000 + i * 20 + 5
        w.add_customer(w.window_start - timedelta(days=22), "standard", "EU", email=email_base.lower(), cust_id=id_a)
        w.add_customer(w.window_start - timedelta(days=21), "standard", "EU", email=email_base.upper(), cust_id=id_b)

        t_ord = w.as_of_utc - timedelta(days=14 + i)
        oa = w.add_order(id_a, t_ord)
        w.add_line(oa, SKU_KEYS[0], 1, 4000, 0, "EUR", t_ord)

        ob = w.add_order(id_b, t_ord + timedelta(hours=1))
        w.add_line(ob, SKU_KEYS[1], 1, 4500, 0, "EUR", t_ord + timedelta(hours=1))

        # Only id_b is deleted
        w.delete_customer(id_b, w.as_of_utc - timedelta(days=8 + i))


def inject_s24_guest_matching_deleted_customer(w: Window, count: int = 6):
    """S24: Guest checkout order matches email of a deleted customer.
    In legacy extract/01_customers.sql, deleted customers are excluded (deleted_at is null).
    In legacy extract/02_orders_customer_map.sql, guest orders join against customers, which
    only contains active accounts. Thus, the guest order matches no active customer and maps to 0 (Guest).
    A naive agent joining guest_email against customer_versions without filtering deleted customers
    incorrectly maps the guest order to the deleted customer ID.
    """
    for i in range(count):
        del_cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU",
                                  email=f"s24_delcust_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=15 + i)
        oid = w.add_order(del_cust, t_ord)
        w.add_line(oid, SKU_KEYS[0], 1, 4200, 0, "EUR", t_ord)
        w.add_payment(oid, "capture", 4200, "EUR", t_ord, t_ord)

        del_time = w.as_of_utc - timedelta(days=10 + i)
        w.delete_customer(del_cust, del_time)

        g_time = w.as_of_utc - timedelta(days=5 + i)
        g_oid = w.add_guest_order(f"s24_delcust_{w.name}_{i}@example.test", g_time)
        w.add_line(g_oid, SKU_KEYS[1], 1, 3800, 0, "EUR", g_time)
        w.add_payment(g_oid, "capture", 3800, "EUR", g_time, g_time)


def inject_s25_tail_removed_promo_shadows(w: Window, count: int = 6):
    """S25: Order has Promo 1 (seq=1) and Promo 2 (seq=2).
    Promo 1 was removed in the platform tail (removed_at >= as_of_utc).
    Promo 2 was never removed (removed_at is None).
    At extract instant, Promo 1 was still active.
    Legacy extract selects Promo 1 (lowest seq non-removed at extract instant).
    A naive agent filtering `removed_at is null` drops Promo 1 and incorrectly selects Promo 2.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU",
                              email=f"s25_promo_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=8 + i)
        oid = w.add_order(cust, t_ord)
        w.add_line(oid, SKU_KEYS[0], 1, 6000, 500, "EUR", t_ord)
        w.add_payment(oid, "capture", 5500, "EUR", t_ord, t_ord)
        tail_rem = w.as_of_utc + timedelta(hours=1 + (i % 4), minutes=15)
        w.add_promo_application(oid, 1, f"PROMO_TAIL_{i}", t_ord, removed_at_utc=tail_rem)
        w.add_promo_application(oid, 2, f"PROMO_ACTIVE_{i}", t_ord + timedelta(minutes=10), None)


def inject_s26_tail_fulfilled_cancelled_order(w: Window, count: int = 6):
    """S26: Order placed and cancelled before as_of_utc.
    In the platform tail (after as_of_utc), a 'fulfilled' lifecycle event commits.
    At extract instant, the order was cancelled, so legacy status is 'cancelled'.
    A naive agent selecting latest lifecycle state without `committed_at < as_of_utc` picks 'fulfilled'
    and outputs 'shipped'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU",
                              email=f"s26_tailful_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=6 + i)
        oid = w.add_order(cust, t_ord)
        w.add_line(oid, SKU_KEYS[1], 1, 4800, 0, "EUR", t_ord)
        w.set_lifecycle(oid, "cancelled", t_ord + timedelta(days=1))
        tail_time = w.as_of_utc + timedelta(hours=2 + (i % 3))
        w.set_lifecycle(oid, "fulfilled", tail_time)


def inject_s27_zero_eur_unpaid_deletion(w: Window, count: int = 6):
    """S27: Order with 100% discount (net EUR = 0.00, captured = 0.00).
    Customer is deleted while order is unpaid and unfulfilled.
    Under app-rules.md, rule 3 cancels unpaid orders upon customer deletion.
    Legacy status is 'cancelled'.
    A naive agent that skips 0-eur orders or assumes total 0 is paid outputs 'pending' or 'paid'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU",
                              email=f"s27_zero_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=7 + i)
        oid = w.add_order(cust, t_ord)
        w.add_line(oid, SKU_KEYS[0], 1, 3500, 3500, "EUR", t_ord)
        del_time = w.as_of_utc - timedelta(days=3 + (i % 3))
        w.delete_customer(cust, del_time)


def inject_s28_negative_net_line_voucher(w: Window, count: int = 6):
    """S28: Order with a voucher discount exceeding line price, producing negative net_eur on line 1.
    Line 1: 1500 price - 2500 discount = -10.00 EUR.
    Line 2: 5000 price - 0 discount = +50.00 EUR.
    Order total = +40.00 EUR.
    A naive agent putting GREATEST(0, net_eur) produces 50.00 EUR instead of 40.00 EUR.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU",
                              email=f"s28_neg_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=8 + i)
        oid = w.add_order(cust, t_ord)
        w.add_line(oid, SKU_KEYS[0], 1, 1500, 2500, "EUR", t_ord)
        w.add_line(oid, SKU_KEYS[1], 1, 5000, 0, "EUR", t_ord)
        w.add_payment(oid, "capture", 4000, "EUR", t_ord, t_ord)


def inject_s29_jpy_kwd_refund_fx_drift(w: Window, count: int = 6):
    """S29: Orders in JPY (0 exponent) and KWD (3 exponents) with refund FX drift.
    Rate drops between capture and refund, so refunded_eur < captured_eur.
    Status is 'partially_refunded'.
    A naive agent checking minor units outputs 'refunded'.
    A naive agent hardcoding /100.0 for minor units produces wild amounts.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU",
                              email=f"s29_exp_{w.name}_{i}@example.test")
        cur = "JPY" if (i % 2 == 0) else "KWD"
        t_cap = (w.as_of_utc - timedelta(days=16 + i)).replace(hour=18, minute=0, second=0, microsecond=0)
        d_cap = effective_fx_date(t_cap)
        rate_cap = most_recent_rate(w.fx_table, cur, d_cap)
        t_ref = None
        for offset in range(1, 12):
            cand_t = t_cap + timedelta(days=offset)
            cand_d = effective_fx_date(cand_t)
            cand_rate = most_recent_rate(w.fx_table, cur, cand_d)
            if cand_rate < rate_cap:
                t_ref = cand_t
                break
        if t_ref is None:
            t_ref = t_cap + timedelta(days=1)

        cap_minor = 50000 if cur == "JPY" else 15000
        oid = w.add_order(cust, t_cap)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, cap_minor, 0, cur, t_cap)
        w.add_payment(oid, "capture", cap_minor, cur, t_cap, t_cap)
        w.add_payment(oid, "refund", cap_minor, cur, t_ref, t_ref)


def inject_s30_double_deletion_cycle(w: Window, count: int = 6):
    """S30: Customer undergoes two deletion cycles:
    Created -> Deleted (T1) -> Restored (T2) -> Deleted again (T3).
    Order 1 placed before T1 (unpaid -> cancelled at T1).
    Order 2 placed after T2 (unpaid -> cancelled at T3).
    Both orders remain permanently cancelled.
    A naive agent tracking only the first deletion fails to cancel Order 2.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=30), "standard", "EU",
                              email=f"s30_double_{w.name}_{i}@example.test")
        t1_ord = w.as_of_utc - timedelta(days=25 + i)
        o1 = w.add_order(cust, t1_ord)
        w.add_line(o1, SKU_KEYS[0], 1, 3000, 0, "EUR", t1_ord)
        w.delete_customer(cust, w.as_of_utc - timedelta(days=20 + i))
        w.restore_customer(cust, w.as_of_utc - timedelta(days=15 + i))
        t2_ord = w.as_of_utc - timedelta(days=12 + i)
        o2 = w.add_order(cust, t2_ord)
        w.add_line(o2, SKU_KEYS[1], 1, 4500, 0, "EUR", t2_ord)
        w.delete_customer(cust, w.as_of_utc - timedelta(days=7 + i))


def inject_s31_promo_min_spend(w: Window, count: int = 6):
    """S31: Order applies PROMO-SAVE10, but total_eur is under 40.00 EUR (25.00 EUR).
    Under app-rules.md:
      "Promotional discount codes with prefix 'PROMO-SAVE' require an order total (total_eur)
       of at least 40.00 EUR. If an order's total_eur is strictly less than 40.00 EUR, the promo
       code is ineligible and orders.promo_id records NULL."
    Legacy operational orders.promo_id is NULL.
    A naive agent selecting promo_code by lowest seq without the qualifying spend check outputs 'PROMO-SAVE10'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU",
                              email=f"s31_spend_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=8 + i)
        oid = w.add_order(cust, t_ord)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 2500, 0, "EUR", t_ord)
        w.add_payment(oid, "capture", 2500, "EUR", t_ord, t_ord)
        w.add_promo_application(oid, 1, "PROMO-SAVE10", t_ord, None)


def inject_s33_terminal_cancellation_posthumous_fulfill(w: Window, count: int = 6):
    """S33: Order cancelled via customer deletion while unpaid and unfulfilled.
    Subsequently, before as_of_utc, an asynchronous lifecycle event 'fulfilled' commits.
    Under app-rules.md:
      "Cancellation is an irreversible terminal state: neither subsequent account
       reinstatement, late payment capture, nor subsequent fulfillment lifecycle
       events (such as late fulfilled status or shipments) reopen or alter cancelled orders."
    Legacy operational orders.status remains 'cancelled'.
    A naive agent selecting latest lifecycle state (state = 'fulfilled') outputs 'shipped'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU",
                              email=f"s33_term_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=12 + i, hours=6)
        oid = w.add_order(cust, t_ord)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 4800, 0, "EUR", t_ord)
        del_time = w.as_of_utc - timedelta(days=8 + i, hours=2)
        w.delete_customer(cust, del_time)
        posthumous_time = w.as_of_utc - timedelta(days=4 + (i % 3), hours=1)
        w.set_lifecycle(oid, "fulfilled", posthumous_time)
        w.add_shipment(oid, posthumous_time)


def inject_s34_partial_refund_precedence_over_cancellation(w: Window, count: int = 6):
    """S34: Order is partially refunded, and subsequently a lifecycle event 'cancelled'
    is recorded for the unfulfilled balance.
    Under app-rules.md:
      "Financial settlement status takes strict precedence over cancellation:
       Cumulative recorded refund payment EUR greater than 0 where captured EUR remains
       strictly greater than refunded EUR is partially_refunded, even if cancellation
       is subsequently recorded."
    Legacy operational orders.status is 'partially_refunded'.
    A naive agent placing `when lifecycle = 'cancelled' then 'cancelled'` above the refund
    check outputs 'cancelled'.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=20), "standard", "EU",
                              email=f"s34_partcan_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=14 + i, hours=6)
        oid = w.add_order(cust, t_ord)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 6000, 0, "EUR", t_ord)
        w.add_payment(oid, "capture", 6000, "EUR", t_ord, t_ord)
        t_ref = t_ord + timedelta(days=2)
        w.add_payment(oid, "refund", 2000, "EUR", t_ref, t_ref)
        t_can = t_ord + timedelta(days=3)
        w.set_lifecycle(oid, "cancelled", t_can)


def inject_s35_promo_seq_tie_break(w: Window, count: int = 6):
    """S35: Order has two active promo applications with the same seq number (seq = 1).
    Application A: applied at T0, promo code 'PROMO-ALPHA-{i}'
    Application B: applied at T0 + 10 min, promo code 'PROMO-BETA-{i}'
    Under app-rules.md:
      "If multiple active applications share the same lowest sequence number, the application
       with the earliest applied_at timestamp takes precedence."
    Legacy operational orders.promo_id is 'PROMO-ALPHA-{i}'.
    A naive agent ordering only by seq without applied_at gets arbitrary or reverse order from DuckDB.
    """
    for i in range(count):
        cust = w.add_customer(w.window_start - timedelta(days=15), "standard", "EU",
                              email=f"s35_tie_{w.name}_{i}@example.test")
        t_ord = w.as_of_utc - timedelta(days=9 + i)
        oid = w.add_order(cust, t_ord)
        w.add_line(oid, SKU_KEYS[i % len(SKU_KEYS)], 1, 5500, 0, "EUR", t_ord)
        w.add_payment(oid, "capture", 5500, "EUR", t_ord, t_ord)
        t_app1 = t_ord + timedelta(minutes=5)
        t_app2 = t_ord + timedelta(minutes=15)
        w.add_promo_application(oid, 1, f"PROMO-ALPHA-{w.name}-{i}", t_app1, None)
        w.add_promo_application(oid, 1, f"PROMO-BETA-{w.name}-{i}", t_app2, None)


# ==============================================================================
# WINDOW DEFINITIONS
# ==============================================================================

WINDOWS = {
    "sample": date(2025, 7, 1),   # Shipped sample
    "h1":     date(2025, 4, 25),  # Spring DST, Good Friday (Apr 18), Easter Mon (Apr 21)
    "h2":     date(2025, 10, 30), # Autumn DST (Oct 26 fall-back hour)
    "h3":     date(2025, 12, 31), # Christmas (Dec 25-26)
    "h4":     date(2026, 1, 5),   # New Year (Jan 1)
    "h5":     date(2025, 5, 20),  # Labour Day (May 1)
    "h6":     date(2025, 9, 15),  # Quiet season: no holiday, no DST transition in range
    "h7":     date(2026, 1, 15),  # Dense holiday window: Christmas + Boxing Day + New Year all in range
    "h8":     date(2025, 3, 20),  # Near the start of the stated 2025-03-01 dual-write period; no holiday
}

SEEDS = {
    "sample": 1001,
    "h1": 1002,
    "h2": 1003,
    "h3": 1004,
    "h4": 1005,
    "h5": 1006,
    "h6": 1007,
    "h7": 1008,
    "h8": 1009,
}

# Held-out windows are fully saturated: every entity-constructible trap (S1-S35)
# fires in every held-out window.
S6_HOLIDAYS = {
    "h1": [date(2025, 4, 18), date(2025, 4, 21)],   # Good Friday, Easter Monday
    "h3": [date(2025, 12, 25), date(2025, 12, 26)],  # Christmas Day, Boxing Day
    "h4": [date(2026, 1, 1)],                        # New Year's Day
    "h5": [date(2025, 5, 1)],                         # Labour Day
    "h7": [date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1)],  # all three at once
}


def build_window(name: str, as_of: date, seed: int) -> Window:
    w = Window(name, as_of, seed)
    build_baseline(w)

    if name == "sample":
        # P3: sample MUST NOT have any S1-S35 traps or L1 reversals!
        return w

    inject_s1(w, count=5)
    inject_s2(w, count=6)
    inject_s3(w, count=4)
    inject_s4(w, count=5)
    inject_s5(w, count=7)
    for holiday in S6_HOLIDAYS.get(name, []):
        inject_s6_holiday(w, holiday, count=6)
    inject_s7_daytime_fx(w, count=8)
    inject_s8_deletion_pending(w, count=6)
    inject_s9_tail_promo(w, count=6)
    inject_s10_tail_shipment(w, count=6)
    inject_s11(w, count=4)
    inject_s12(w, count=4)
    inject_s13(w, count=6)
    inject_s14_deletion_restoration_order_cancelled(w, count=6)
    inject_s15_reshipment_tail_cancel(w, count=6)
    inject_s16_email_rename_guest_link(w, count=6)
    inject_s17_all_deleted_duplicate_group(w, count=5)
    inject_s18_tail_restored_duplicate_group(w, count=5)
    inject_s19_order_line_fx_order_timestamp(w, count=6)
    inject_s20_deletion_late_payment(w, count=6)
    inject_s22_multi_day_refund_fx_drift(w, count=6)
    inject_s23_duplicate_account_deletion_isolation(w, count=5)
    inject_s24_guest_matching_deleted_customer(w, count=6)
    inject_s25_tail_removed_promo_shadows(w, count=6)
    inject_s26_tail_fulfilled_cancelled_order(w, count=6)
    inject_s27_zero_eur_unpaid_deletion(w, count=6)
    inject_s28_negative_net_line_voucher(w, count=6)
    inject_s29_jpy_kwd_refund_fx_drift(w, count=6)
    inject_s30_double_deletion_cycle(w, count=6)
    inject_s31_promo_min_spend(w, count=6)
    inject_s33_terminal_cancellation_posthumous_fulfill(w, count=6)
    inject_s34_partial_refund_precedence_over_cancellation(w, count=6)
    inject_s35_promo_seq_tie_break(w, count=6)
    if name == "h2":
        inject_l1(w, count=4)

    return w


def main():
    out_root = Path(__file__).parent / "out"
    for name, as_of in WINDOWS.items():
        w = build_window(name, as_of, seed=SEEDS[name])
        w.platform_write(out_root / name / "platform")
        w.legacy_snapshot_and_write(out_root / name / "legacy_op")
        print(f"Generated {name}: as_of={as_of} "
              f"cust_versions={len(w.p_customer_versions)} orders={len(w.p_orders)} "
              f"lines={len(w.p_order_lines)} payments={len(w.p_payment_events)} "
              f"promos={len(w.p_order_promo_applications)} shipments={len(w.p_shipments)}")


if __name__ == "__main__":
    main()

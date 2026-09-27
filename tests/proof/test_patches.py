"""Dual-Write Migration Regression Invariance Test Suite:
Evaluates 38 regression scenarios across 9 temporal windows:
- NV1..NV14 (visible boundary conditions and quirks)
- NS1..NS10, NS19, NS20, NS22..NS26, NS28, NS31, NS33..NS35 (silent temporal, financial, and lifecycle traps)
- NL1 (daylight saving time wall-clock vs UTC ordering)
- NAIVE (composite baseline simulating naive migration interpretations)
"""
import copy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CUR_DIR = Path(__file__).resolve().parent
ROOT = CUR_DIR.parents[1] if (CUR_DIR.parents[1] / "environment").exists() else CUR_DIR.parent
ENV_PROJECT = (ROOT / "environment" / "project") if (ROOT / "environment" / "project").exists() else (ROOT / "project")
SOL_MODELS = (ROOT / "solution" / "models") if (ROOT / "solution" / "models").exists() else (CUR_DIR / "ref" / "models")
SOL_MACROS = (ROOT / "solution" / "macros") if (ROOT / "solution" / "macros").exists() else (CUR_DIR / "ref" / "macros")
WINDOWS = ["sample", "h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8"]
HELDOUT_WINDOWS = ["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8"]


def run_project(project_dir: Path, window: str, out_dir: Path):
    plat_data = ROOT / "tests" / "generator" / "out" / window / "platform"
    if not plat_data.exists():
        plat_data = ROOT / "generator" / "out" / window / "platform"
    if not plat_data.exists():
        plat_data = ROOT / "heldout" / window if window != "sample" else (ROOT / "project" / "data" / "sample" / "platform")
    cmd = [
        sys.executable, str(project_dir / "tools" / "run.py"),
        "--sources", "platform", "--data", str(plat_data), "--out", str(out_dir),
        "--project-dir", str(project_dir)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"run.py failed for {window}:\n{r.stderr}")


def compare_marts(leg_dir: Path, test_dir: Path) -> tuple[bool, int, list]:
    cmd = [
        sys.executable, str(ENV_PROJECT / "tools" / "compare.py"),
        str(leg_dir), str(test_dir)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out_lines = r.stdout.strip().splitlines()
    if r.returncode == 0:
        return True, 0, []
    diff_count = 0
    diff_marts = []
    for line in out_lines:
        if "mart(s) differ" in line:
            parts = line.split()
            diff_count = int(parts[0])
        elif ":" in line and not line.startswith(" "):
            m_name = line.split(":")[0].strip()
            if m_name and m_name not in diff_marts:
                diff_marts.append(m_name)
    return False, diff_count or len(diff_marts), diff_marts


def build_patched_project(staging_overrides: dict = None, int_overrides: dict = None, macro_overrides: dict = None) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="patch_proj_"))
    shutil.copytree(ENV_PROJECT, tmp, dirs_exist_ok=True)
    shutil.copytree(SOL_MACROS, tmp / "macros", dirs_exist_ok=True)
    shutil.copytree(SOL_MODELS, tmp / "models", dirs_exist_ok=True)

    if staging_overrides:
        for name, content in staging_overrides.items():
            (tmp / "models" / "staging" / f"{name}.sql").write_text(content)
    if int_overrides:
        for name, content in int_overrides.items():
            (tmp / "models" / "intermediate" / f"{name}.sql").write_text(content)
    if macro_overrides:
        for name, content in macro_overrides.items():
            (tmp / "macros" / f"{name}.sql").write_text(content)
    return tmp


# Read base solution files
BASE_STG = {f.stem: f.read_text() for f in (SOL_MODELS / "staging").glob("*.sql")}
BASE_INT = {f.stem: f.read_text() for f in (SOL_MODELS / "intermediate").glob("*.sql")}
BASE_MACROS = {f.stem: f.read_text() for f in SOL_MACROS.glob("*.sql")}


def get_patch_overrides(patch_name: str) -> tuple[dict, dict, dict]:
    stg = {}
    intl = {}
    macros = {}

    if patch_name == "NV1":
        # Ignore V1: include orders committed in the +6h platform tail
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "where o.committed_at < m.as_of_utc", ""
        )
    elif patch_name == "NV2":
        # Ignore V2: change < as_of_utc to <= as_of_utc in orders
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "where o.committed_at < m.as_of_utc", "where o.committed_at <= m.as_of_utc"
        )
    elif patch_name == "NV3":
        # Ignore V3: use initial/earliest version instead of current state
        stg["stg_customers"] = BASE_STG["stg_customers"].replace(
            "order by v.valid_from desc", "order by v.valid_from asc"
        )
    elif patch_name == "NV4":
        # Ignore V4: use UTC timestamp directly for placed_at
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "berlin_ts(o.committed_at) as placed_at", "o.committed_at as placed_at"
        )
    elif patch_name == "NV5":
        # Ignore V5: round-half-away-from-zero instead of half-even (exact decimal, no
        # DOUBLE involved, isolating the tie-break rule from any float-precision confound).
        # Only the eur_amount definition is swapped; berlin_ts/berlin_date/effective_fx_date
        # in the same file are left intact.
        macros["money"] = BASE_MACROS["money"].replace(
            "CREATE OR REPLACE MACRO eur_amount(amount_minor, exponent, rate) AS\n"
            "    CAST(\n"
            "        round_half_even_exact(\n"
            "            (amount_minor::DECIMAL(38,10) / CAST(POWER(10, exponent) AS DECIMAL(38,10)))\n"
            "                * rate::DECIMAL(38,10),\n"
            "            100\n"
            "        ) AS DECIMAL(18,2)\n"
            "    );",
            "CREATE OR REPLACE MACRO eur_amount(amount_minor, exponent, rate) AS\n"
            "    CAST(\n"
            "        FLOOR(\n"
            "            (amount_minor::DECIMAL(38,10) / CAST(POWER(10, exponent) AS DECIMAL(38,10)) "
            "* rate::DECIMAL(38,10)) * 100 + 0.5\n"
            "        )::DECIMAL(38,10) / 100\n"
            "        AS DECIMAL(18,2)\n"
            "    );"
        )
    elif patch_name == "NV6":
        # Ignore V6: ignore refund precedence, check fulfilled before refunded
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "when coalesce(ps.refunded, 0) >= coalesce(ps.captured, 0) and coalesce(ps.captured, 0) > 0\n            then 'refunded'\n        when coalesce(ps.refunded, 0) > 0\n            then 'partially_refunded'",
            "when lc.state = 'fulfilled'\n            then 'shipped'"
        )
    elif patch_name == "NV7":
        # Ignore V7: leave guest customer_id as NULL instead of 0
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "else 0\n        end as customer_id",
            "else null\n        end as customer_id"
        )
    elif patch_name == "NV8":
        # Ignore V8: do not filter out deleted customers
        stg["stg_customers"] = BASE_STG["stg_customers"].replace(
            "where s.event_type is null or s.event_type != 'deleted'", ""
        )
    elif patch_name == "NV9":
        # Ignore V9: exclude restored customers (filter any deleted event)
        stg["stg_customers"] = BASE_STG["stg_customers"].replace(
            "where s.event_type is null or s.event_type != 'deleted'",
            "where c.customer_id not in (select customer_id from {{ source('platform', 'customer_status_events') }})"
        )
    elif patch_name == "NV10":
        # Ignore V10: do not deduplicate customer accounts, no remapping
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "when b.customer_id is not null then coalesce(d.canonical_id, b.customer_id)",
            "when b.customer_id is not null then b.customer_id"
        )
    elif patch_name == "NV11":
        # Ignore V11: do not link guest orders to customer accounts
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "when b.guest_email is not null and g.canonical_id is not null then g.canonical_id",
            "when b.guest_email is not null then 0"
        )
    elif patch_name == "NV12":
        # Ignore V12: ignore promo removal, pick seq=1 always
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "where p.removed_at is null", ""
        )
    elif patch_name == "NV13":
        # Ignore V13: include cancelled shipments
        stg["stg_shipments"] = BASE_STG["stg_shipments"].replace(
            "and (s.cancelled_at is null or s.cancelled_at >= m.as_of_utc)", ""
        )
    elif patch_name == "NV14":
        # Ignore V14: use occurred_at date for payment FX rate
        stg["stg_payments"] = BASE_STG["stg_payments"].replace(
            "effective_fx_date(p.committed_at)",
            "effective_fx_date(p.occurred_at)"
        )
    # --- SILENT TRAPS (NS1..NS10) ---
    elif patch_name == "NS1":
        # NS1: compare status in minor units instead of rounded EUR sums
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "sum(case when kind = 'capture' then amount_eur else 0 end) as captured,\n        sum(case when kind = 'refund' then amount_eur else 0 end) as refunded",
            "sum(case when kind = 'capture' then amount_minor else 0 end) as captured,\n        sum(case when kind = 'refund' then amount_minor else 0 end) as refunded"
        )
    elif patch_name == "NS2":
        # NS2: half-open (<=) customer version lookup
        stg["stg_customers"] = BASE_STG["stg_customers"].replace(
            "where v.valid_from < m.as_of_utc", "where v.valid_from <= m.as_of_utc"
        )
    elif patch_name == "NS3":
        # NS3: treat restore committed at as_of_utc as visible (committed_at <= as_of_utc)
        stg["stg_customers"] = BASE_STG["stg_customers"].replace(
            "where committed_at < m.as_of_utc", "where committed_at <= m.as_of_utc"
        )
    elif patch_name == "NS4":
        # NS4: deduplicate all accounts first, then drop deleted ones
        stg["stg_customers"] = BASE_STG["stg_customers"].replace(
            "canonical_active as (\n    select\n        lower(email) as email_key,\n        min(customer_id) as canonical_id\n    from active_customers\n    group by lower(email)\n)",
            "canonical_all as (\n    select\n        lower(email) as email_key,\n        min(customer_id) as canonical_id\n    from current_versions\n    group by lower(email)\n),\ncanonical_active as (\n    select c.email_key, c.canonical_id from canonical_all c join active_customers a on a.customer_id = c.canonical_id\n)"
        )
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "canonical_active as (\n    select\n        lower(email) as email_key,\n        min(customer_id) as canonical_id\n    from active_customers\n    group by lower(email)\n)",
            "canonical_all as (\n    select\n        lower(email) as email_key,\n        min(customer_id) as canonical_id\n    from current_versions\n    group by lower(email)\n),\ncanonical_active as (\n    select c.email_key, c.canonical_id from canonical_all c join active_customers a on a.customer_id = c.canonical_id\n)"
        )
    elif patch_name == "NS5":
        # NS5: case-sensitive join for guest email to customer email
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "left join canonical_active g on g.email_key = lower(b.guest_email)",
            "left join (select email, customer_id as canonical_id from active_customers) g on g.email = b.guest_email"
        )
    elif patch_name == "NS6":
        # NS6: weekend-only FX fallback
        weekend_only = (
            "case when extract(dow from berlin_date({ts})) = 0 then berlin_date({ts}) - 2 "
            "when extract(dow from berlin_date({ts})) = 6 then berlin_date({ts}) - 1 "
            "else berlin_date({ts}) end"
        )
        stg["stg_order_lines"] = BASE_STG["stg_order_lines"].replace(
            "and f.date <= effective_fx_date(o.committed_at)\n                order by f.date desc\n                limit 1",
            "and f.date = " + weekend_only.format(ts="o.committed_at")
        )
        stg["stg_payments"] = BASE_STG["stg_payments"].replace(
            "and f.date <= effective_fx_date(p.committed_at)\n                order by f.date desc\n                limit 1",
            "and f.date = " + weekend_only.format(ts="p.committed_at")
        )
    elif patch_name == "NS7":
        # NS7: ignore 16:00 FX publication cutoff, use plain calendar date
        stg["stg_order_lines"] = BASE_STG["stg_order_lines"].replace(
            "effective_fx_date(o.committed_at)", "berlin_date(o.committed_at)"
        )
        stg["stg_payments"] = BASE_STG["stg_payments"].replace(
            "effective_fx_date(p.committed_at)", "berlin_date(p.committed_at)"
        )
    elif patch_name == "NS8":
        # NS8: ignore customer deletion cascade in order status
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "or cd.order_id is not null",
            ""
        )
    elif patch_name == "NS9":
        # NS9: naive promo removal check (drops promos removed in tail)
        stg["stg_promo_applications"] = BASE_STG["stg_promo_applications"].replace(
            """    case
        when p.removed_at is not null and p.removed_at < m.as_of_utc
            then berlin_ts(p.removed_at)
        else null
    end as removed_at""",
            "berlin_ts(p.removed_at) as removed_at"
        )
    elif patch_name == "NS10":
        # NS10: naive shipment cancellation check (drops shipments cancelled in tail)
        stg["stg_shipments"] = BASE_STG["stg_shipments"].replace(
            "and (s.cancelled_at is null or s.cancelled_at >= m.as_of_utc)",
            "and s.cancelled_at is null"
        )
    elif patch_name == "NS19":
        # NS19: order lines use l.committed_at instead of o.committed_at
        stg["stg_order_lines"] = BASE_STG["stg_order_lines"].replace(
            "effective_fx_date(o.committed_at)", "effective_fx_date(l.committed_at)"
        )
    elif patch_name == "NS20":
        # NS20: naive static check captured == 0 on final aggregate sums, missing terminal cancellation before late payment
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "or cd.order_id is not null",
            "or (cd.order_id is not null and coalesce(ps.captured, 0) = 0)"
        )
    elif patch_name == "NS22":
        # NS22: order status marks refunded based on original currency / payment count instead of EUR sums
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "when coalesce(ps.refunded, 0) >= coalesce(ps.captured, 0) and coalesce(ps.captured, 0) > 0",
            "when (select count(*) from {{ ref('stg_payments') }} where order_id = r.order_id and kind = 'refund') > 0 and (select sum(amount_minor) from {{ ref('stg_payments') }} where order_id = r.order_id and kind = 'refund') >= (select sum(amount_minor) from {{ ref('stg_payments') }} where order_id = r.order_id and kind = 'capture')"
        )
    elif patch_name == "NS23":
        # NS23: check deletion on canonical customer_id instead of original placing customer
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "join {{ source('platform', 'customer_status_events') }} s\n        on s.customer_id = b.customer_id",
            "left join dedupe_map dm on dm.member_id = b.customer_id\n    join {{ source('platform', 'customer_status_events') }} s\n        on s.customer_id = coalesce(dm.canonical_id, b.customer_id)"
        )
    elif patch_name == "NS24":
        # NS24: guest order links directly to customer_versions without filtering deleted accounts
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "left join canonical_active g on g.email_key = lower(b.guest_email)",
            "left join (select lower(email) as email_key, min(customer_id) as canonical_id from current_versions group by lower(email)) g on g.email_key = lower(b.guest_email)"
        )
    elif patch_name == "NS25":
        # NS25: promo applications uses removed_at is null directly (drops tail-removed promos)
        stg["stg_promo_applications"] = BASE_STG["stg_promo_applications"].replace(
            """    case
        when p.removed_at is not null and p.removed_at < m.as_of_utc
            then berlin_ts(p.removed_at)
        else null
    end as removed_at""",
            "berlin_ts(p.removed_at) as removed_at"
        )
    elif patch_name == "NS26":
        # NS26: lifecycle events without extract boundary cutoff (picks tail fulfilled state)
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "where e.committed_at < m.as_of_utc",
            ""
        ).replace(
            "when fcan.order_id is not null\n             or cd.order_id is not null\n            then 'cancelled'",
            "when lc.state = 'cancelled' or cd.order_id is not null then 'cancelled'"
        )
    elif patch_name == "NS28":
        # NS28: clipping line net EUR at 0 (greatest(0, net_eur))
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "sum(net_eur)::decimal(18,2)",
            "sum(case when net_eur < 0 then 0 else net_eur end)::decimal(18,2)"
        )
    elif patch_name == "NS31":
        # NS31: naive promo spend threshold (ignores minimum 40.00 EUR for PROMO-SAVE)
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "and not (p.promo_code like 'PROMO-SAVE%' and coalesce(lt.total_eur, 0) < 40.00)",
            ""
        )
    elif patch_name == "NS33":
        # NS33: naive lifecycle state (picks fulfilled when order was cancelled before fulfillment)
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "when fcan.order_id is not null\n             or cd.order_id is not null\n            then 'cancelled'\n        when lc.state = 'fulfilled'\n            then 'shipped'",
            "when lc.state = 'fulfilled'\n            then 'shipped'\n        when fcan.order_id is not null or cd.order_id is not null\n            then 'cancelled'"
        )
    elif patch_name == "NS34":
        # NS34: naive status precedence (checks cancelled before partial refund)
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "when coalesce(ps.refunded, 0) > 0\n            then 'partially_refunded'\n        when fcan.order_id is not null\n             or cd.order_id is not null\n            then 'cancelled'",
            "when fcan.order_id is not null or cd.order_id is not null\n            then 'cancelled'\n        when coalesce(ps.refunded, 0) > 0\n            then 'partially_refunded'"
        )
    elif patch_name == "NS35":
        # NS35: promo sequence tie-breaking without applied_at (arbitrary/wrong tie break)
        stg["stg_orders"] = BASE_STG["stg_orders"].replace(
            "order by p.seq, p.applied_at",
            "order by p.seq, p.applied_at desc"
        )
    elif patch_name == "NL1":
        # NL1: rewrite L1 mart to order by placed_at_utc instead of placed_at wall-clock
        intl["int_customer_first_order"] = BASE_INT["int_customer_first_order"].replace(
            "order by placed_at, order_id",
            "order by placed_at_utc, order_id"
        )
    elif patch_name == "NAIVE":
        # NAIVE: composite natural wrongs
        stg["stg_orders"] = BASE_STG["stg_orders"]
        # NS1: minor units
        stg["stg_orders"] = stg["stg_orders"].replace(
            "sum(case when kind = 'capture' then amount_eur else 0 end) as captured,\n        sum(case when kind = 'refund' then amount_eur else 0 end) as refunded",
            "sum(case when kind = 'capture' then amount_minor else 0 end) as captured,\n        sum(case when kind = 'refund' then amount_minor else 0 end) as refunded"
        )
        # NS4: dedupe before filter
        stg["stg_orders"] = stg["stg_orders"].replace(
            "canonical_active as (\n    select\n        lower(email) as email_key,\n        min(customer_id) as canonical_id\n    from active_customers\n    group by lower(email)\n)",
            "canonical_all as (\n    select\n        lower(email) as email_key,\n        min(customer_id) as canonical_id\n    from current_versions\n    group by lower(email)\n),\ncanonical_active as (\n    select c.email_key, c.canonical_id from canonical_all c join active_customers a on a.customer_id = c.canonical_id\n)"
        )
        # NS5: case-sensitive guest
        stg["stg_orders"] = stg["stg_orders"].replace(
            "left join canonical_active g on g.email_key = lower(b.guest_email)",
            "left join (select email, customer_id as canonical_id from active_customers) g on g.email = b.guest_email"
        )
        # NS8: ignore deletion cascade in status
        stg["stg_orders"] = stg["stg_orders"].replace(
            "or cd.order_id is not null",
            ""
        )
        # NS31: ignore promo spend threshold
        stg["stg_orders"] = stg["stg_orders"].replace(
            "and not (p.promo_code like 'PROMO-SAVE%' and coalesce(lt.total_eur, 0) < 40.00)",
            ""
        )
        # NS35: promo tie break
        stg["stg_orders"] = stg["stg_orders"].replace(
            "order by p.seq, p.applied_at",
            "order by p.seq"
        )
        # NS2 & NS3 & NS4 in stg_customers
        stg["stg_customers"] = BASE_STG["stg_customers"].replace(
            "where v.valid_from < m.as_of_utc", "where v.valid_from <= m.as_of_utc"
        ).replace(
            "where committed_at < m.as_of_utc", "where committed_at <= m.as_of_utc"
        ).replace(
            "canonical_active as (\n    select\n        lower(email) as email_key,\n        min(customer_id) as canonical_id\n    from active_customers\n    group by lower(email)\n)",
            "canonical_all as (\n    select\n        lower(email) as email_key,\n        min(customer_id) as canonical_id\n    from current_versions\n    group by lower(email)\n),\ncanonical_active as (\n    select c.email_key, c.canonical_id from canonical_all c join active_customers a on a.customer_id = c.canonical_id\n)"
        )
        # NS6 & NS7 & NS19 in stg_order_lines and stg_payments
        stg["stg_order_lines"] = BASE_STG["stg_order_lines"].replace(
            "effective_fx_date(o.committed_at)", "berlin_date(l.committed_at)"
        )
        stg["stg_payments"] = BASE_STG["stg_payments"].replace(
            "effective_fx_date(p.committed_at)", "berlin_date(p.committed_at)"
        )
        # NS9: naive promo removal
        stg["stg_promo_applications"] = BASE_STG["stg_promo_applications"].replace(
            """    case
        when p.removed_at is not null and p.removed_at < m.as_of_utc
            then berlin_ts(p.removed_at)
        else null
    end as removed_at""",
            "berlin_ts(p.removed_at) as removed_at"
        )
        # NS10: naive shipment cancellation
        stg["stg_shipments"] = BASE_STG["stg_shipments"].replace(
            "and (s.cancelled_at is null or s.cancelled_at >= m.as_of_utc)",
            "and s.cancelled_at is null"
        )

    return stg, intl, macros


def test_patch(patch_name: str) -> dict:
    stg, intl, macros = get_patch_overrides(patch_name)
    proj_dir = build_patched_project(stg, intl, macros)
    results = {}

    # NV patches only need sample
    windows_to_run = ["sample"] if patch_name.startswith("NV") else WINDOWS

    try:
        for w in windows_to_run:
            with tempfile.TemporaryDirectory() as out_tmp:
                run_project(proj_dir, w, Path(out_tmp))
                leg_out = ROOT / "tests" / "generator" / "out" / w / "_proof_legacy"
                if not leg_out.exists():
                    leg_out = ROOT / "generator" / "out" / w / "_proof_legacy"
                if not leg_out.exists():
                    leg_out = ROOT / "expected" / w
                matches, diff_cnt, diff_list = compare_marts(leg_out, Path(out_tmp))
                results[w] = {
                    "match": matches,
                    "diff_count": diff_cnt,
                    "diff_marts": diff_list,
                }
    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)
    return results


def main():
    patches_to_test = sys.argv[1:] or (
        [f"NV{i}" for i in range(1, 15)] +
        [f"NS{i}" for i in range(1, 11)] +
        ["NS19", "NS20", "NS22", "NS23", "NS24", "NS25", "NS26", "NS28", "NS31", "NS33", "NS34", "NS35"] +
        ["NL1", "NAIVE"]
    )

    all_passed = True
    summary = {}

    print(f"=== Testing {len(patches_to_test)} patches ===")
    for p in patches_to_test:
        res = test_patch(p)
        summary[p] = res

        if p.startswith("NV"):
            diff_on_sample = not res["sample"]["match"]
            status = "PASS" if diff_on_sample else "FAIL (passed sample!)"
            print(f"{p:6s}: sample differ={not res['sample']['match']} ({res['sample']['diff_count']} marts) -> {status}")
            if not diff_on_sample:
                all_passed = False
        elif p.startswith("NS"):
            match_sample = res["sample"]["match"]
            heldout_diffs = sum(1 for w in HELDOUT_WINDOWS if not res[w]["match"])
            status = "PASS" if (match_sample and heldout_diffs >= 4) else "FAIL"
            print(f"{p:6s}: sample match={match_sample}, heldout_diffs={heldout_diffs}/8 -> {status}")
            if not (match_sample and heldout_diffs >= 4):
                all_passed = False
        elif p == "NL1":
            match_sample = res["sample"]["match"]
            diff_h2 = not res["h2"]["match"]
            status = "PASS" if (match_sample and diff_h2) else "FAIL"
            print(f"{p:6s}: sample match={match_sample}, h2 differ={diff_h2} -> {status}")
            if not (match_sample and diff_h2):
                all_passed = False
        elif p == "NAIVE":
            match_sample = res["sample"]["match"]
            heldout_diffs = sum(1 for w in HELDOUT_WINDOWS if not res[w]["match"])
            status = "PASS" if (match_sample and heldout_diffs >= 6) else "FAIL"
            print(f"{p:6s}: sample match={match_sample}, heldout_diffs={heldout_diffs}/8 -> {status}")
            if not (match_sample and heldout_diffs >= 6):
                all_passed = False

    print("\n=== SUMMARY ===")
    print(f"Overall Direction A verification: {'ALL PASS' if all_passed else 'SOME FAILED'}")
    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()

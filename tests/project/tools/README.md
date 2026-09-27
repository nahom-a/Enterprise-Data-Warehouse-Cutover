# `tools/run.py` and `tools/compare.py`

## `run.py`

```
python tools/run.py --sources platform --data <dir-of-parquet> --out <dir>
python tools/run.py --sources legacy   --data <dir-of-parquet> --out <dir>
```

`--data` is a directory containing one Parquet file per source table (file name = table
name, e.g. `orders.parquet`). `--sources` states which schema those tables belong to;
inside the project, `{{ source('legacy', 'orders') }}` and `{{ source('platform', 'orders') }}`
resolve to `legacy.orders` and `platform.orders` respectively, so running with
`--sources legacy` against platform data (or vice versa) fails with a missing-table error
rather than silently mixing the two.

The runner loads every `.sql` file under `macros/`, then every model under
`models/staging`, `models/intermediate` and `models/marts`, builds them as
`CREATE OR REPLACE TABLE <model> AS <select>` in dependency order (from each model's
`{{ ref(...) }}` calls), and writes every model under `models/marts` to
`<out>/<mart>.parquet`.

## `compare.py`

```
python tools/compare.py <dir-a> <dir-b>
```

Compares every mart Parquet file present in both directories (exits non-zero if the set of
marts differs). For each mart:

- **Columns**: the set of column names must be identical. Declared types beyond a value's
  type family are not compared (a `DECIMAL(18,2)` and a `DECIMAL(18,4)` column holding the
  same numeric values are equal).
- **Rows**: compared as a multiset (row order does not matter; duplicate rows must occur
  the same number of times on both sides).
- **Values**, normalised by type family before comparison:
  - integers compare as Python `int`;
  - decimals compare as Python `Decimal`, normalised so `1.50` and `1.5` are equal;
  - text compares exactly, including case;
  - dates and timestamps compare as ISO-8601 strings;
  - booleans compare as booleans;
  - `NULL` equals `NULL`.

Exit code `0` means every mart matched exactly under this definition; `1` means at least
one mart differed, or the two directories didn't contain the same set of marts.

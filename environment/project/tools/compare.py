#!/usr/bin/env python3
"""Comparator: for every mart present in both directories, checks the same set of column
names and the same multiset of rows, values normalised by type family. See tools/README.md
for the exact equality definition -- this is the standard implementation of it."""
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq


def normalise_value(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return int(v)
    if isinstance(v, Decimal):
        return Decimal(v).normalize() if v == v.to_integral_value() else Decimal(v)
    if isinstance(v, float):
        # no mart column should be float/double; if one leaks through, compare it as-is
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def normalise_decimal(v):
    # Decimal('1.50') and Decimal('1.5') must compare equal; Decimal.normalize() on an
    # integral value strips to '1', which also compares equal across differing declared
    # scales as long as both sides are normalised the same way.
    if isinstance(v, Decimal):
        return v.normalize()
    return v


def load_rows(path: Path):
    table = pq.read_table(path)
    cols = table.column_names
    rows = []
    for row in table.to_pylist():
        rows.append(tuple(normalise_decimal(normalise_value(row[c])) for c in cols))
    return set(cols), rows


def compare_mart(name: str, path_a: Path, path_b: Path) -> list:
    errors = []
    cols_a, rows_a = load_rows(path_a)
    cols_b, rows_b = load_rows(path_b)
    if cols_a != cols_b:
        errors.append(f"{name}: column mismatch: {cols_a ^ cols_b}")
        return errors
    count_a, count_b = Counter(rows_a), Counter(rows_b)
    if count_a != count_b:
        only_a = list((count_a - count_b).elements())
        only_b = list((count_b - count_a).elements())
        errors.append(f"{name}: row multiset mismatch: {len(only_a)} rows only in A, "
                      f"{len(only_b)} rows only in B (first of each shown)")
        if only_a:
            errors.append(f"  only in A: {only_a[0]}")
        if only_b:
            errors.append(f"  only in B: {only_b[0]}")
    return errors


def main():
    if len(sys.argv) != 3:
        print("usage: compare.py <dir-a> <dir-b>", file=sys.stderr)
        sys.exit(2)
    dir_a, dir_b = Path(sys.argv[1]), Path(sys.argv[2])
    marts_a = {p.stem for p in dir_a.glob("*.parquet")}
    marts_b = {p.stem for p in dir_b.glob("*.parquet")}
    if marts_a != marts_b:
        print(f"mart set mismatch: {marts_a ^ marts_b}", file=sys.stderr)
        sys.exit(1)

    all_errors = []
    for mart in sorted(marts_a):
        all_errors.extend(compare_mart(mart, dir_a / f"{mart}.parquet", dir_b / f"{mart}.parquet"))

    if all_errors:
        for e in all_errors:
            print(e)
        print(f"\n{len([e for e in all_errors if not e.startswith(' ')])} mart(s) differ")
        sys.exit(1)
    print(f"all {len(marts_a)} marts match")
    sys.exit(0)


if __name__ == "__main__":
    main()

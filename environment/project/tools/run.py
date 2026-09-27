#!/usr/bin/env python3
"""Runner: builds the project's models against one source (legacy or platform) and writes
each mart to a Parquet file. See tools/README.md for the full contract."""
import argparse
import re
import sys
import tempfile
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([a-zA-Z0-9_]+)['\"]\s*\)\s*\}\}")
SOURCE_RE = re.compile(r"\{\{\s*source\(\s*['\"]([a-zA-Z0-9_]+)['\"]\s*,\s*['\"]([a-zA-Z0-9_]+)['\"]\s*\)\s*\}\}")


def strip_line_comments(sql_text: str) -> str:
    out = []
    for line in sql_text.splitlines():
        idx = line.find("--")
        out.append(line[:idx] if idx != -1 else line)
    return "\n".join(out)


def load_models(models_dir: Path) -> dict:
    models = {}
    for sub in ("staging", "intermediate", "marts"):
        d = models_dir / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.sql")):
            name = f.stem
            if name in models:
                print(f"error: duplicate model name '{name}'", file=sys.stderr)
                sys.exit(1)
            models[name] = dict(path=f, layer=sub, raw=strip_line_comments(f.read_text()))
    return models


def topo_sort(models: dict) -> list:
    deps = {name: set(REF_RE.findall(m["raw"])) for name, m in models.items()}
    for name, d in deps.items():
        for dep in d:
            if dep not in models:
                print(f"error: model '{name}' refs unknown model '{dep}'", file=sys.stderr)
                sys.exit(1)
    order, visiting, visited = [], set(), set()

    def visit(n):
        if n in visited:
            return
        if n in visiting:
            print(f"error: dependency cycle at '{n}'", file=sys.stderr)
            sys.exit(1)
        visiting.add(n)
        for dep in sorted(deps[n]):
            visit(dep)
        visiting.discard(n)
        visited.add(n)
        order.append(n)

    for name in sorted(models):
        visit(name)
    return order


def substitute(raw: str, sources_schema: str) -> str:
    sql = REF_RE.sub(lambda m: m.group(1), raw)
    sql = SOURCE_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)}", sql)
    return sql


def run_sql_script(con, script: str, label: str):
    for stmt in [s.strip() for s in script.split(";") if s.strip()]:
        try:
            con.execute(stmt)
        except Exception:
            print(f"error executing statement from {label}:\n{stmt}", file=sys.stderr)
            raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True, choices=["legacy", "platform"])
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--project-dir", type=Path, default=None, help="Root directory of project")
    args = ap.parse_args()

    if args.project_dir:
        project_root = args.project_dir
    elif Path("/app/project/models").exists():
        project_root = Path("/app/project")
    else:
        project_root = Path(__file__).resolve().parents[1]
    models_dir = project_root / "models"
    macros_dir = project_root / "macros"

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "run.duckdb"
        con = duckdb.connect(str(db_path), config={"enable_external_access": True})
        try:
            con.execute(f"create schema if not exists {args.sources}")
            parquet_files = sorted(args.data.glob("*.parquet"))
            if not parquet_files:
                print(f"error: no parquet files found under {args.data}", file=sys.stderr)
                sys.exit(1)
            for p in parquet_files:
                table = p.stem
                con.execute(
                    f"create table {args.sources}.{table} as select * from read_parquet('{p.as_posix()}')"
                )

            con.execute("LOAD icu")
            con.execute("SET enable_external_access = false")
            con.execute("SET autoinstall_known_extensions = false")
            con.execute("SET autoload_known_extensions = false")
            con.execute("SET lock_configuration = true")

            for f in sorted(macros_dir.glob("*.sql")):
                run_sql_script(con, strip_line_comments(f.read_text()), f.name)

            models = load_models(models_dir)
            order = topo_sort(models)
            for name in order:
                m = models[name]
                sql = substitute(m["raw"], args.sources)
                try:
                    con.execute(f"create or replace table {name} as {sql}")
                except Exception:
                    print(f"error building model '{name}' ({m['path']})", file=sys.stderr)
                    raise

            mart_dir = models_dir / "marts"
            mart_names = sorted(f.stem for f in mart_dir.glob("*.sql"))
            args.out.mkdir(parents=True, exist_ok=True)
            for mart in mart_names:
                table = con.table(mart).fetch_arrow_table()
                pq.write_table(table, args.out / f"{mart}.parquet")
            print(f"built {len(order)} models, wrote {len(mart_names)} marts to {args.out}")
        finally:
            con.close()


if __name__ == "__main__":
    main()

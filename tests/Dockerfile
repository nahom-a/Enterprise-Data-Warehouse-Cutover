FROM python:3.12-slim-bookworm AS proof
RUN pip install --no-cache-dir duckdb==1.1.3 pyarrow==18.1.0
COPY . /work/
WORKDIR /work
RUN python proof/run_all.py && echo ok > /work/PROOF_OK

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir pytest==9.1.1 pytest-json-ctrf==0.5.2 duckdb==1.1.3 pyarrow==18.1.0
RUN /opt/venv/bin/python -c "import duckdb, pyarrow, pytest; assert duckdb.__version__ == '1.1.3'; assert pyarrow.__version__ == '18.1.0'"
RUN pip install --no-cache-dir duckdb==1.1.3 pyarrow==18.1.0
COPY . /tests/
COPY --from=proof /work/expected /tests/expected
COPY --from=proof /work/heldout /tests/heldout
COPY --from=proof /work/PROOF_OK /tests/.proof_ok
RUN mkdir -p /app/project/models /app/project/macros

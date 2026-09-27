FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir duckdb==1.1.3 pyarrow==18.1.0
RUN python -c "import duckdb; assert duckdb.__version__ == '1.1.3'"
COPY project /app/project
COPY legacy-system /app/legacy-system
WORKDIR /app/project

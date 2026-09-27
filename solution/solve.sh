#!/bin/bash
set -e

PROJECT_DIR="/app/project"
SOLUTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_DIR="$SOLUTION_DIR/../tests/expected/sample"

# 1. Replace project models and macros with solution copies
rm -rf "$PROJECT_DIR/models" "$PROJECT_DIR/macros"
cp -r "$SOLUTION_DIR/models" "$PROJECT_DIR/models"
cp -r "$SOLUTION_DIR/macros" "$PROJECT_DIR/macros"

# 2. Build the platform side on the sample window. The solution models are rewritten
# staging models that read source('platform', ...) only (see contracts/platform.md); a
# --sources legacy build against them would reference platform.* tables that don't exist
# under the legacy schema, so only the platform side is built here, same as the verifier.
PLATFORM_DATA="$PROJECT_DIR/data/sample/platform"

OUT_PLATFORM=$(mktemp -d)

python "$PROJECT_DIR/tools/run.py" --sources platform --data "$PLATFORM_DATA" --out "$OUT_PLATFORM"

# 3. Compare against the static expected legacy marts baked for the sample window
python "$PROJECT_DIR/tools/compare.py" "$OUT_PLATFORM" "$EXPECTED_DIR"

rm -rf "$OUT_PLATFORM"
echo "Solution applied and verified successfully."

#!/bin/bash
set -u
mkdir -p /logs/verifier
chmod 700 /logs/verifier
echo 0 > /logs/verifier/reward.txt
WORK=$(mktemp -d); chmod 755 "$WORK"
/opt/venv/bin/python -m pytest /tests/test_cutover.py --ctrf "$WORK/ctrf.json" -rA \
  -p no:cacheprovider > "$WORK/pytest.log" 2>&1
rc=$?
cp "$WORK/ctrf.json" /logs/verifier/ctrf.json 2>/dev/null
cp "$WORK/pytest.log" /logs/verifier/pytest.log 2>/dev/null
ok=$(/opt/venv/bin/python /tests/ctrf_check.py /logs/verifier/ctrf.json 144)
if [ "$rc" -eq 0 ] && [ "$ok" = "OK" ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
exit 0

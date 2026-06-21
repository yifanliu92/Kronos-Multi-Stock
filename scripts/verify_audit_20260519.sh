#!/usr/bin/env bash
set -euo pipefail
AUDIT="/Users/wxo/Desktop/Kronos/audit"
files=(
  "$AUDIT/check_summary_20260519.md"
  "$AUDIT/schedule_trace_20260519.md"
  "$AUDIT/trade_event_verify_20260519.md"
  "$AUDIT/final_audit_20260519.md"
)
for f in "${files[@]}"; do
  [[ -f "$f" ]] || { echo "MISSING: $f"; exit 1; }
done

grep -q "total_checks:" "$AUDIT/check_summary_20260519.md"
grep -q "missing_slots:" "$AUDIT/schedule_trace_20260519.md"
grep -q "hard_rule_check:" "$AUDIT/trade_event_verify_20260519.md"
grep -q "final_confidence:" "$AUDIT/final_audit_20260519.md"

echo "VERIFY_PASS"
shasum -a 256 "${files[@]}"
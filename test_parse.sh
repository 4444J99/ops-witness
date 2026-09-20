#!/bin/bash
set -euo pipefail
DAY="2026-06-19"
HYGIENE_REPORT="../ops/reports/${DAY}-hygiene.md"
FLAGGED=0
REPORT="test_report.md"

echo "start" > "$REPORT"

if [ -f "$HYGIENE_REPORT" ]; then
  echo "" >> "$REPORT"
  echo "## Stale Repositories (Actionable Signals)" >> "$REPORT"
  echo "" >> "$REPORT"
  echo "| Repo | Signal |" >> "$REPORT"
  echo "|------|--------|" >> "$REPORT"

  while IFS='|' read -r empty repo prs oldest push issues empty2; do
    repo=$(echo "$repo" | xargs || true)
    oldest=$(echo "$oldest" | xargs || true)
    push=$(echo "$push" | xargs || true)
    
    if [ -n "$repo" ] && [ "$repo" != "Repo" ] && echo "$repo" | grep -q '\`'; then
      repo_clean=$(echo "$repo" | tr -d '\`')
      if [ "$oldest" != "-" ] && [ "$oldest" -gt 30 ] 2>/dev/null; then
        echo "| \`${repo_clean}\` | **FLAG**: Oldest PR is $oldest days old |" >> "$REPORT"
        FLAGGED=$((FLAGGED + 1))
      fi
      if [ "$push" != "-" ] && [ "$push" -gt 90 ] 2>/dev/null; then
        echo "| \`${repo_clean}\` | **FLAG**: No default branch push in $push days |" >> "$REPORT"
        FLAGGED=$((FLAGGED + 1))
      fi
    fi
  done < <(tail -n +7 "$HYGIENE_REPORT" 2>/dev/null || true)
fi

echo "FLAGGED=$FLAGGED"
cat test_report.md

#!/bin/bash
          set -euo pipefail
          DAY="$(date -u +%Y-%m-%d)"
          mkdir -p audit
          REPORT="audit/${DAY}-witness.md"
          WORK="$(mktemp -d)"

          LOCAL_AUDIT_COUNT="$(ls -1 audit/*.md 2>/dev/null | wc -l | tr -d ' ')"
          BOOKEND_LIST=""
          OPS_REPO="foo"
          WATCHED_JOB="job"
          CF_TARGETS="a b"
          SCHEDULER_URL=""

          {
            echo "# Cross-plane witness — ${DAY}"
            echo ""
            echo "_Generated ${DAY} $(date -u +%H:%M:%SZ) by the witness plane._"
            echo ""
            echo "- Watched plane: \`${OPS_REPO}\` (plane i)"
            echo "- Watched job (GitHub): \`${WATCHED_JOB}\`"
            echo "- Watched jobs (Cloudflare): \`${CF_TARGETS}\`"
            echo "- Local audit reports on file: ${LOCAL_AUDIT_COUNT}"
            echo ""
            echo "## Last 7 days — bookend pairing"
            echo ""
            echo "| Day | Job | start | end | verdict |"
            echo "|-----|-----|:-----:|:---:|---------|"
          } > "$REPORT"

          FLAGGED=0

          for i in $(seq 0 6); do
            D="$(date -u -d "-${i} day" +%Y-%m-%d)"
            FNAME="${D}.tsv"
            
            # --- Evaluate GitHub Job ---
            if echo "$BOOKEND_LIST" | grep -qx "$FNAME"; then
              gh api "repos/${OPS_REPO}/contents/bookends/${FNAME}" --jq '.content' 2>/dev/null \
                | base64 -d > "${WORK}/${FNAME}" 2>/dev/null || true

              HAS_START="$(awk -F'\t' -v j="$WATCHED_JOB" '$2==j && $5=="start"{c++} END{print c+0}' "${WORK}/${FNAME}" 2>/dev/null || echo 0)"
              HAS_END="$(awk -F'\t' -v j="$WATCHED_JOB" '$2==j && $5=="end"{c++} END{print c+0}' "${WORK}/${FNAME}" 2>/dev/null || echo 0)"

              if [ "$HAS_START" -gt 0 ] && [ "$HAS_END" -gt 0 ]; then
                VERDICT="healthy"
                SMARK="yes"; EMARK="yes"
              elif [ "$HAS_START" -gt 0 ] && [ "$HAS_END" -eq 0 ]; then
                VERDICT="**FLAG: fired but no end (died mid-run)**"
                SMARK="yes"; EMARK="no"
                FLAGGED=$((FLAGGED + 1))
              else
                VERDICT="**FLAG: no bookend on a day with a TSV**"
                SMARK="no"; EMARK="no"
                FLAGGED=$((FLAGGED + 1))
              fi
            else
              VERDICT="**FLAG: no bookend file (job never fired?)**"
              SMARK="no"; EMARK="no"
              FLAGGED=$((FLAGGED + 1))
            fi
            echo "| ${D} | ${WATCHED_JOB} | ${SMARK} | ${EMARK} | ${VERDICT} |" >> "$REPORT"

            # --- Evaluate Cloudflare Jobs ---
            CF_TSV="${WORK}/${D}-cf.tsv"
            if [ -n "${SCHEDULER_URL:-}" ]; then
              curl -s -f "${SCHEDULER_URL}/bookends?date=${D}" | jq -r '.bookends[]?' > "$CF_TSV" || touch "$CF_TSV"
            else
              touch "$CF_TSV"
            fi

            for target in $CF_TARGETS; do
              HAS_START="$(awk -F'\t' -v j="$target" '$2==j && $5=="start"{c++} END{print c+0}' "$CF_TSV" 2>/dev/null || echo 0)"
              HAS_END="$(awk -F'\t' -v j="$target" '$2==j && $5=="end"{c++} END{print c+0}' "$CF_TSV" 2>/dev/null || echo 0)"

              if [ "$HAS_START" -gt 0 ] && [ "$HAS_END" -gt 0 ]; then
                VERDICT="healthy"
                SMARK="yes"; EMARK="yes"
              elif [ "$HAS_START" -gt 0 ] && [ "$HAS_END" -eq 0 ]; then
                VERDICT="**FLAG: fired but no end (died mid-run)**"
                SMARK="yes"; EMARK="no"
                FLAGGED=$((FLAGGED + 1))
              else
                VERDICT="**FLAG: no bookend found (job never fired?)**"
                SMARK="no"; EMARK="no"
                FLAGGED=$((FLAGGED + 1))
              fi
              echo "| ${D} | ${target} | ${SMARK} | ${EMARK} | ${VERDICT} |" >> "$REPORT"
            done
          done

          {
            echo ""
            echo "## Summary"
            echo ""
            if [ "$FLAGGED" -eq 0 ]; then
              echo "All 7 days have paired bookends across all targets. No gaps. **Healthy.**"
            else
              echo "**${FLAGGED}** flag(s) raised over the last 7 days. A silent gap is a failure,"
              echo "not a non-event — investigate the flagged runs above."
            fi
            echo ""
            echo "_Note: a newly stood-up backbone or newly added targets will show flags for days predating their"
            echo "first fire. That is correct — those days genuinely had no run._"
          } >> "$REPORT"

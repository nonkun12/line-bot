#!/usr/bin/env bash
# Run the existing safe single-PR runner across a list or inclusive range.
set -uo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/mac_goal_pr_batch_test.sh <PR_OR_RANGE[,PR_OR_RANGE...]> [PYTEST_TARGET]

Examples:
  bash scripts/mac_goal_pr_batch_test.sh 1251-1255
  bash scripts/mac_goal_pr_batch_test.sh 1253,1254,1255
  bash scripts/mac_goal_pr_batch_test.sh 1251-1255 tests/test_mac_bonsai_goal_review_worker.py

The batch continues after an individual PR fails and prints a final summary.
Duplicate PRs, zero, malformed selectors, descending ranges, and ranges over 50 PRs are rejected before any test starts.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage >&2
  exit 2
fi

SPEC="$1"
TEST_TARGET="${2-tests/test_mac_bonsai_goal_review_worker.py}"

# Validate the shared target once before starting any PR, so a bad path cannot
# cause a partially executed batch. Keep this in sync with the single runner.
if [[ -z "$TEST_TARGET" || "$TEST_TARGET" == /* || "$TEST_TARGET" == -* ]]; then
  echo "ERROR: pytest target must be a relative path inside the PR worktree: $TEST_TARGET" >&2
  exit 2
fi
IFS='/' read -r -a TARGET_PARTS <<< "$TEST_TARGET"
for part in "${TARGET_PARTS[@]}"; do
  if [[ -z "$part" || "$part" == "." || "$part" == ".." ]]; then
    echo "ERROR: pytest target contains an unsafe path component: $TEST_TARGET" >&2
    exit 2
  fi
done
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SINGLE_RUNNER="$SCRIPT_DIR/mac_goal_pr_test.sh"
if [[ ! -f "$SINGLE_RUNNER" ]]; then
  echo "ERROR: single-PR runner not found: $SINGLE_RUNNER" >&2
  exit 2
fi

declare -a PRS=()

append_pr() {
  local candidate="$1"
  local existing
  for existing in "${PRS[@]}"; do
    if [[ "$existing" == "$candidate" ]]; then
      echo "ERROR: duplicate PR number: $candidate" >&2
      return 1
    fi
  done
  PRS+=("$candidate")
}

IFS=',' read -r -a PARTS <<< "$SPEC"
for part in "${PARTS[@]}"; do
  if [[ "$part" =~ ^([1-9][0-9]{0,8})-([1-9][0-9]{0,8})$ ]]; then
    start="${BASH_REMATCH[1]}"
    end="${BASH_REMATCH[2]}"
    if (( start > end || end - start > 49 )); then
      echo "ERROR: invalid or too-large PR range: $part (maximum 50 PRs, ascending only)" >&2
      exit 2
    fi
    for ((pr=start; pr<=end; pr++)); do
      append_pr "$pr" || exit 2
    done
  elif [[ "$part" =~ ^[1-9][0-9]{0,8}$ ]]; then
    append_pr "$part" || exit 2
  else
    echo "ERROR: invalid PR selector: $part" >&2
    exit 2
  fi
done

if (( ${#PRS[@]} == 0 )); then
  echo "ERROR: no PRs selected" >&2
  exit 2
fi

declare -a RESULTS=()
passed=0
failed=0
echo "Batch target: $TEST_TARGET"
echo "PRs: ${PRS[*]}"
echo "Each PR runs in its own worktree; the batch continues after failures."
echo

for pr in "${PRS[@]}"; do
  echo "============================================================"
  echo "START PR #$pr"
  echo "============================================================"
  if bash "$SINGLE_RUNNER" "$pr" "$TEST_TARGET"; then
    RESULTS+=("#$pr PASS")
    passed=$((passed + 1))
  else
    status=$?
    RESULTS+=("#$pr FAIL (exit $status)")
    failed=$((failed + 1))
  fi
  echo
done

echo "==================== BATCH SUMMARY ===================="
printf '%s\n' "${RESULTS[@]}"
echo "TOTAL: ${#PRS[@]}  PASS: $passed  FAIL: $failed"
if (( failed > 0 )); then
  exit 1
fi
exit 0

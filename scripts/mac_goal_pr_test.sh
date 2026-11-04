#!/usr/bin/env bash
# Fetch a GitHub PR into a dedicated worktree and run the Mac Goal-review tests.
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/mac_goal_pr_test.sh <PR_NUMBER> [PYTEST_TARGET]

Examples:
  scripts/mac_goal_pr_test.sh 1255
  scripts/mac_goal_pr_test.sh 1255 tests/test_mac_bonsai_goal_review_worker.py

Environment:
  PYTHON   Optional explicit Python interpreter.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -lt 1 || $# -gt 2 || ! "${1:-}" =~ ^[0-9]+$ ]]; then
  usage >&2
  exit 2
fi

PR="$1"
TEST_TARGET="${2:-tests/test_mac_bonsai_goal_review_worker.py}"

# Pytest targets must be plain relative paths inside the PR worktree.
# Reject traversal, absolute paths, empty components, and option-like targets
# before fetching or creating/updating any worktree.
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

REPO_ROOT="$(git rev-parse --show-toplevel)"
REMOTE="$(git -C "$REPO_ROOT" remote get-url origin)"
WORKTREE="$(cd "$REPO_ROOT/.." && pwd)/line-bot-goal-pr$PR"
REF="refs/remotes/origin/pr/$PR"
LOG_DIR="$HOME/Library/Logs/line-bot-goal-pr-tests"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/pr-$PR-$STAMP.log"
LOG_RETENTION=5

# Keep only this PR's newest logs; other PRs and unrelated files are untouched.
prune_old_logs() {
  local count=0 candidate files
  files="$(ls -1t "$LOG_DIR"/pr-"$PR"-*.log 2>/dev/null || true)"
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    count=$((count + 1))
    if (( count > LOG_RETENTION )); then
      rm -f "$candidate"
    fi
  done <<< "$files"
}

case "$REMOTE" in
  *github.com/nonkun12/line-bot*|*github.com:nonkun12/line-bot*) ;;
  *)
    echo "ERROR: origin is not nonkun12/line-bot: $REMOTE" >&2
    exit 2
    ;;
esac

mkdir -p "$LOG_DIR"
echo "== Fetch PR #$PR =="
git -C "$REPO_ROOT" fetch --no-tags origin "+refs/pull/$PR/head:$REF"

if [[ -e "$WORKTREE" ]]; then
  if ! git -C "$WORKTREE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: target path exists but is not a Git worktree: $WORKTREE" >&2
    exit 2
  fi
  WORKTREE_ROOT="$(git -C "$WORKTREE" rev-parse --show-toplevel)"
  if [[ "$WORKTREE_ROOT" != "$WORKTREE" ]]; then
    echo "ERROR: existing worktree path resolves unexpectedly: $WORKTREE_ROOT" >&2
    exit 2
  fi
  if [[ -n "$(git -C "$WORKTREE" status --porcelain)" ]]; then
    echo "ERROR: worktree has local changes; refusing to overwrite: $WORKTREE" >&2
    exit 2
  fi
  git -C "$WORKTREE" checkout --detach "$REF"
else
  git -C "$REPO_ROOT" worktree add --detach "$WORKTREE" "$REF"
fi

# Reject symlinked path components so a relative path cannot escape the worktree.
TARGET_CURSOR="$WORKTREE"
for part in "${TARGET_PARTS[@]}"; do
  TARGET_CURSOR="$TARGET_CURSOR/$part"
  if [[ -L "$TARGET_CURSOR" ]]; then
    echo "ERROR: pytest target traverses a symlink: $TEST_TARGET" >&2
    exit 2
  fi
done

if [[ ! -f "$WORKTREE/$TEST_TARGET" ]]; then
  echo "ERROR: test target not found: $WORKTREE/$TEST_TARGET" >&2
  exit 2
fi

PY=""
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x "$REPO_ROOT/../line-bot-media-pr1222/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/../line-bot-media-pr1222/.venv/bin/python"
elif [[ -x "$WORKTREE/.venv/bin/python" ]]; then
  PY="$WORKTREE/.venv/bin/python"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "ERROR: Python not found. Set PYTHON=/path/to/python." >&2
  exit 2
fi

if ! "$PY" -m pytest --version >/dev/null 2>&1; then
  echo "ERROR: pytest is unavailable in $PY. Set PYTHON to the project's tested venv." >&2
  exit 2
fi

echo "PR:        #$PR"
echo "Commit:    $(git -C "$WORKTREE" rev-parse HEAD)"
echo "Worktree:  $WORKTREE"
echo "Python:    $PY"
echo "Test:      $TEST_TARGET"
echo "Log:       $LOG_FILE"
echo "Retention: newest $LOG_RETENTION logs for this PR"
echo
set +e
(
  cd "$WORKTREE"
  "$PY" -m pytest -q "$TEST_TARGET"
) 2>&1 | tee "$LOG_FILE"
TEST_STATUS=${PIPESTATUS[0]}
set -e

prune_old_logs

if [[ $TEST_STATUS -eq 0 ]]; then
  echo
  echo "RESULT: PASS (Mac pytest exit code 0)"
  echo "LOG: $LOG_FILE"
  echo "LOG CLEANUP: kept newest $LOG_RETENTION logs for PR #$PR"
  exit 0
fi

echo
echo "RESULT: FAIL (pytest exit code $TEST_STATUS)"
echo "LOG: $LOG_FILE"
echo "LOG CLEANUP: kept newest $LOG_RETENTION logs for PR #$PR"
exit "$TEST_STATUS"

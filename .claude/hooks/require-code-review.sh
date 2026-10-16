#!/usr/bin/env bash
# Enforces the "run /code-review before opening a PR" rule from CLAUDE.md.
#
#   record  - PostToolUse(Skill) / UserPromptSubmit: when /code-review runs,
#             remember the commit it reviewed (HEAD).
#   check   - PreToolUse(Bash): deny `gh pr create` unless the recorded
#             commit is the current HEAD.
#
# The marker lives in .git/, so it is never committed.
set -euo pipefail

mode="${1:-}"
input="$(cat)"
cd "${CLAUDE_PROJECT_DIR:-.}"
marker="$(git rev-parse --git-path claude-code-review-head)"

case "$mode" in
  record)
    skill="$(jq -r '.tool_input.skill // empty' <<<"$input")"
    prompt="$(jq -r '.prompt // empty' <<<"$input")"
    if [[ "$skill" == "code-review" || "$prompt" =~ ^[[:space:]]*/code-review([[:space:]]|$) ]]; then
      git rev-parse HEAD >"$marker"
    fi
    ;;
  check)
    cmd="$(jq -r '.tool_input.command // empty' <<<"$input")"
    grep -Eq '(^|[^[:alnum:]_-])gh[[:space:]]+pr[[:space:]]+create' <<<"$cmd" || exit 0
    head="$(git rev-parse HEAD)"
    reviewed="$(cat "$marker" 2>/dev/null || true)"
    [[ "$reviewed" == "$head" ]] && exit 0
    if [[ -z "$reviewed" ]]; then
      reason="No /code-review has been run on this repository yet."
    else
      reason="The last /code-review covered ${reviewed:0:7}, but HEAD is now ${head:0:7}."
    fi
    jq -n --arg r "$reason Run /code-review on the current HEAD (commit your changes first), then create the PR. See CLAUDE.md, Development process." \
      '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
    ;;
  *)
    echo "usage: $0 record|check" >&2
    exit 1
    ;;
esac

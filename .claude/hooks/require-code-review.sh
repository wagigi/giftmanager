#!/usr/bin/env bash
# Enforces the "run /code-review before opening a PR" rule from CLAUDE.md.
#
# A review only counts once it has finished, on the current branch, with a
# clean tree:
#   record  - PostToolUse(Skill): /code-review runs forked, so this fires after
#             the review completed successfully. Records HEAD.
#   pending - UserPromptSubmit: a typed /code-review only marks HEAD as pending;
#             any other prompt discards a pending review.
#   promote - Stop: the turn finished normally (not interrupted, no API error),
#             so a pending review is promoted to recorded. Known gap: after an
#             interrupt, a turn started without a user prompt (e.g. a
#             background task waking Claude) can still promote it.
#   check   - PreToolUse(Bash): deny PR creation unless the recorded commit is
#             the current HEAD.
#
# Markers live in the (per-worktree) git dir, so they are never committed.
# This is a guardrail for Claude, not a security boundary: `gh api` or a PR
# opened outside Claude Code is not covered.
set -euo pipefail

mode="${1:-}"
input="$(cat)"

enter_cwd() {
  cd "$(jq -r '.cwd // empty' <<<"$input" | grep . || echo "${CLAUDE_PROJECT_DIR:-.}")"
  marker="$(git rev-parse --git-path claude-code-review-head)"
  pending="$(git rev-parse --git-path claude-code-review-pending)"
}

# Succeeds when /code-review args target the current branch (no target, or a
# target naming it, e.g. "main...<branch>") and the tree is clean.
reviews_current_head() {
  local branch
  branch="$(git branch --show-current)"
  [[ -n "$branch" ]] || return 1
  set -f
  set -- $1
  set +f
  while (($#)); do
    case "$1" in
      low|medium|high|xhigh|max|ultra|--fix|--comment|--post|--no-post) ;;
      --max-findings=*) ;;
      --max-findings) (($# > 1)) && shift ;;
      "$branch"|HEAD|*.."$branch"|*..HEAD) ;;
      *) return 1 ;;
    esac
    shift
  done
  # A review with uncommitted tracked changes did not review HEAD.
  git diff --quiet HEAD --
}

case "$mode" in
  record)
    [[ "$input" == *code-review* ]] || exit 0
    [[ "$(jq -r '.tool_input.skill // empty' <<<"$input")" == "code-review" ]] || exit 0
    enter_cwd
    if reviews_current_head "$(jq -r '.tool_input.args // empty' <<<"$input")"; then
      git rev-parse HEAD >"$marker"
    fi
    ;;
  pending)
    enter_cwd
    [[ "$input" == *code-review* || -f "$pending" ]] || exit 0
    rm -f "$pending"
    prompt="$(jq -r '.prompt // empty' <<<"$input")"
    if [[ "$prompt" =~ ^[[:space:]]*/code-review([[:space:]]+(.*))?$ ]] &&
      reviews_current_head "${BASH_REMATCH[2]}"; then
      git rev-parse HEAD >"$pending"
    fi
    ;;
  promote)
    enter_cwd
    [[ -f "$pending" ]] || exit 0
    if [[ "$(cat "$pending")" == "$(git rev-parse HEAD)" ]] && git diff --quiet HEAD --; then
      mv "$pending" "$marker"
    else
      rm -f "$pending"
    fi
    ;;
  check)
    # Fail open fast for the vast majority of commands, before any jq/git.
    [[ "$input" == *gh* ]] || exit 0
    cmd="$(jq -r '.tool_input.command // empty' <<<"$input")"
    # Ignore quoted text (commit messages, grep patterns, echo) in a single
    # left-to-right pass, and join backslash-continued lines.
    unquoted="$(tr '\n' ' ' <<<"$cmd" | sed -E "s/\\\\ / /g; s/'[^']*'|\"[^\"]*\"//g")"
    grep -Eq '(^|[^[:alnum:]_-])gh([[:space:]]+-{1,2}[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+pr[[:space:]]+(create|new)([[:space:]]|$)' <<<"$unquoted" || exit 0
    enter_cwd
    head="$(git rev-parse HEAD)"
    reviewed="$(cat "$marker" 2>/dev/null || true)"
    [[ "$reviewed" == "$head" ]] && exit 0
    if [[ -z "$reviewed" ]]; then
      reason="No completed /code-review has been recorded for this checkout."
    else
      reason="The last /code-review covered ${reviewed:0:7}, but HEAD is now ${head:0:7}."
    fi
    jq -n --arg r "$reason Commit your changes, run /code-review on the current branch, then create the PR. See CLAUDE.md, Development process." \
      '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
    ;;
  *)
    echo "usage: $0 record|pending|promote|check" >&2
    exit 1
    ;;
esac

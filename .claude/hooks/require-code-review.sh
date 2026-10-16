#!/usr/bin/env bash
# Enforces the "run /code-review before opening a PR" rule from CLAUDE.md.
#
#   record  - PostToolUse(Skill) / UserPromptSubmit: when /code-review runs on
#             the current branch with a clean tree, remember HEAD.
#   check   - PreToolUse(Bash): deny PR creation unless the recorded commit is
#             the current HEAD.
#
# The marker lives in the (per-worktree) git dir, so it is never committed.
# This is a guardrail for Claude, not a security boundary: `gh api` or a PR
# opened outside Claude Code is not covered.
set -euo pipefail

mode="${1:-}"
input="$(cat)"

case "$mode" in
  record)
    # Cheap pre-filter: most prompts / skills are unrelated.
    [[ "$input" == *code-review* ]] || exit 0
    cd "$(jq -r '.cwd // empty' <<<"$input" | grep . || echo "${CLAUDE_PROJECT_DIR:-.}")"
    skill="$(jq -r '.tool_input.skill // empty' <<<"$input")"
    prompt="$(jq -r '.prompt // empty' <<<"$input")"
    if [[ "$skill" == "code-review" ]]; then
      args="$(jq -r '.tool_input.args // empty' <<<"$input")"
    elif [[ "$prompt" =~ ^[[:space:]]*/code-review([[:space:]]+(.*))?$ ]]; then
      args="${BASH_REMATCH[2]}"
    else
      exit 0
    fi
    branch="$(git branch --show-current)"
    [[ -n "$branch" ]] || exit 0
    # Only a review of the current branch counts: no target, or a target
    # naming this branch (e.g. "main...<branch>").
    set -f
    set -- $args
    set +f
    while (($#)); do
      case "$1" in
        low|medium|high|xhigh|max|ultra|--fix|--comment|--post|--no-post) ;;
        --max-findings=*) ;;
        --max-findings) (($# > 1)) && shift ;;
        "$branch"|*..."$branch"|*.."$branch") ;;
        *) exit 0 ;;
      esac
      shift
    done
    # A review with uncommitted tracked changes did not review HEAD.
    git diff --quiet HEAD -- || exit 0
    git rev-parse HEAD >"$(git rev-parse --git-path claude-code-review-head)"
    ;;
  check)
    # Fail open fast for the vast majority of commands, before any jq/git.
    [[ "$input" == *gh* ]] || exit 0
    cmd="$(jq -r '.tool_input.command // empty' <<<"$input")"
    # Ignore quoted text (commit messages, grep patterns, echo) in a single
    # left-to-right pass, and join backslash-continued lines.
    unquoted="$(tr '\n' ' ' <<<"$cmd" | sed -E "s/\\\\ / /g; s/'[^']*'|\"[^\"]*\"//g")"
    grep -Eq '(^|[^[:alnum:]_-])gh([[:space:]]+-{1,2}[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+pr[[:space:]]+(create|new)([[:space:]]|$)' <<<"$unquoted" || exit 0
    cd "$(jq -r '.cwd // empty' <<<"$input" | grep . || echo "${CLAUDE_PROJECT_DIR:-.}")"
    head="$(git rev-parse HEAD)"
    reviewed="$(cat "$(git rev-parse --git-path claude-code-review-head)" 2>/dev/null || true)"
    [[ "$reviewed" == "$head" ]] && exit 0
    if [[ -z "$reviewed" ]]; then
      reason="No /code-review has been recorded for this checkout."
    else
      reason="The last /code-review covered ${reviewed:0:7}, but HEAD is now ${head:0:7}."
    fi
    jq -n --arg r "$reason Commit your changes, run /code-review on the current branch, then create the PR. See CLAUDE.md, Development process." \
      '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
    ;;
  *)
    echo "usage: $0 record|check" >&2
    exit 1
    ;;
esac

#!/usr/bin/env bash
# dev-skills remote-readiness check hook.
#
# Warns when the current branch is behind its upstream so the user can pull
# before doing feature work (the feature-* skills create files; doing so on a
# behind branch invites a needless divergence). It never pulls. It surfaces the
# warning two ways: a `systemMessage` shown directly to the user (so it is never
# silent), plus an `additionalContext` note that lets Claude offer a one-click
# `git pull`. (additionalContext alone is injected into Claude's context only and
# is not displayed to the user — which is why a visible systemMessage is needed.)
#
# Modes (passed as $1 by hooks/hooks.json):
#   sessionstart  -> always fetch, and reset the throttle window.
#   userprompt    -> fetch only when the last check is older than the window;
#                    otherwise stay silent (so it never nags every prompt).
#
# State (last-fetch epoch) lives in the repo's git dir, so it is per-repo and
# never committed. The hook is a no-op outside a git repo, with no upstream,
# or when offline — it must never block or error the session.

set -u

MODE="${1:-userprompt}"
THROTTLE_SECONDS=7200   # 2 hours
FETCH_TIMEOUT=15        # bound the network call (UserPromptSubmit budget is 30s)

# --- locate the repo from the hook payload (cwd), falling back to $PWD --------
payload="$(cat 2>/dev/null || true)"
cwd="$(printf '%s' "$payload" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
if [ -n "${cwd:-}" ]; then
  cd "$cwd" 2>/dev/null || true
fi

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

git_dir="$(git rev-parse --git-dir 2>/dev/null)" || exit 0
state_file="$git_dir/dev-skills-remote-check"

now="$(date +%s)"

last_fetch=0
if [ -f "$state_file" ]; then
  last_fetch="$(sed -n '1p' "$state_file" 2>/dev/null)"
  case "$last_fetch" in *[!0-9]* | "") last_fetch=0 ;; esac
fi

# --- decide whether to fetch --------------------------------------------------
should_fetch=0
if [ "$MODE" = "sessionstart" ]; then
  should_fetch=1
elif [ $((now - last_fetch)) -ge "$THROTTLE_SECONDS" ]; then
  should_fetch=1
fi

# Throttled prompt within the window: stay silent (no nag, no network).
[ "$should_fetch" -eq 1 ] || exit 0

# --- bounded fetch (portable: timeout is absent on stock macOS) ---------------
if command -v timeout >/dev/null 2>&1; then
  timeout "$FETCH_TIMEOUT" git fetch --quiet 2>/dev/null || true
elif command -v gtimeout >/dev/null 2>&1; then
  gtimeout "$FETCH_TIMEOUT" git fetch --quiet 2>/dev/null || true
else
  git fetch --quiet 2>/dev/null || true
fi
# Record the attempt regardless of success, so a failing/offline remote is not
# retried on every prompt (the next sessionstart will fetch again anyway).
printf '%s\n' "$now" >"$state_file" 2>/dev/null || true

# --- compute behind count against the upstream --------------------------------
upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)" || exit 0
[ -n "$upstream" ] || exit 0
behind="$(git rev-list --count "HEAD..$upstream" 2>/dev/null)" || exit 0
case "$behind" in *[!0-9]* | "") behind=0 ;; esac

# Up to date or only ahead: nothing to warn about.
[ "$behind" -gt 0 ] || exit 0

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"

if [ "$MODE" = "sessionstart" ]; then
  event="SessionStart"
else
  event="UserPromptSubmit"
fi

# Two parts to the output, both single-quoted refs to keep double quotes out of
# the JSON strings:
#   - systemMessage   -> shown directly to the user as a terminal warning, so the
#                        behind-state is never silent (additionalContext alone is
#                        injected into Claude's context and is not user-visible).
#   - additionalContext -> lets Claude offer a one-click 'git pull --ff-only'.
warn="[dev-skills remote-check] Branch '${branch}' is ${behind} commit(s) behind its upstream '${upstream}'. Run 'git pull --ff-only' to sync before making changes."
ctx="[dev-skills remote-check] Branch '${branch}' is ${behind} commit(s) behind its upstream '${upstream}'. The user has been shown this as a warning. Before any feature work (creating/editing files or running /feature-* skills), offer the user a one-click 'git pull --ff-only' to sync first — avoid creating files on a behind branch. Do not pull automatically; ask first."

# JSON-escape backslashes and double quotes defensively (ref names are tame, but be safe).
warn_esc="$(printf '%s' "$warn" | sed 's/\\/\\\\/g; s/"/\\"/g')"
ctx_esc="$(printf '%s' "$ctx" | sed 's/\\/\\\\/g; s/"/\\"/g')"

printf '{"systemMessage":"%s","hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$warn_esc" "$event" "$ctx_esc"
exit 0

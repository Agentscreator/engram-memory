#!/usr/bin/env bash
#
# Engram PR Conflict Scanner
#
# Queries workspace memory with the PR context and posts a comment
# if known facts may contradict the proposed changes.
#
set -euo pipefail

# ── Validate required env vars ────────────────────────────────────────

if [[ -z "${ENGRAM_SERVER_URL:-}" ]]; then
  echo "::warning::ENGRAM_SERVER_URL is not configured for this workflow run — skipping scan."
  echo "facts_found=0" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [[ -z "${ENGRAM_INVITE_KEY:-}" ]]; then
  echo "::warning::ENGRAM_INVITE_KEY is not configured for this workflow run — skipping scan."
  echo "facts_found=0" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [[ -z "${PR_NUMBER:-}" ]]; then
  echo "::error::Not running in a pull_request context (PR_NUMBER is empty)"
  exit 1
fi

RELEVANCE_THRESHOLD="${RELEVANCE_THRESHOLD:-0.3}"
MAX_RESULTS="${MAX_RESULTS:-10}"
POST_COMMENT="${POST_COMMENT:-true}"
BASE_URL="${ENGRAM_SERVER_URL%/}"

# ── Health check ──────────────────────────────────────────────────────

echo "Checking Engram server health..."
HEALTH_RESPONSE=$(curl -sf --max-time 10 "${BASE_URL}/api/health" 2>&1) || {
  echo "::warning::Engram server unreachable at ${BASE_URL}/api/health — skipping scan."
  echo "facts_found=0" >> "$GITHUB_OUTPUT"
  exit 0
}

HEALTH_STATUS=$(echo "$HEALTH_RESPONSE" | jq -r '.status // "unknown"')
if [[ "$HEALTH_STATUS" != "ok" ]]; then
  echo "::warning::Engram server is degraded (status: ${HEALTH_STATUS}) — skipping scan."
  echo "facts_found=0" >> "$GITHUB_OUTPUT"
  exit 0
fi

echo "Server healthy."

# ── Gather PR context ─────────────────────────────────────────────────

PR_TITLE="${PR_TITLE:-}"
PR_BODY="${PR_BODY:-}"

CHANGED_FILES=""
if [[ -n "${GH_REPO:-}" ]]; then
  CHANGED_FILES=$(curl -sf --max-time 15 \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GH_REPO}/pulls/${PR_NUMBER}/files" \
    | jq -r '.[].filename' 2>/dev/null) || CHANGED_FILES=""
fi

# ── Build search query ────────────────────────────────────────────────

build_query() {
  local title="$1"
  local body="$2"
  local files="$3"

  local query=""

  if [[ -n "$title" ]]; then
    query="$title"
  fi

  # Extract first 200 chars of body (strip markdown noise)
  if [[ -n "$body" ]]; then
    local clean_body
    clean_body=$(echo "$body" | sed 's/[#*`>_~\[\]]//g' | head -c 200)
    if [[ -n "$clean_body" ]]; then
      query="${query} ${clean_body}"
    fi
  fi

  # Add up to 10 file paths (directory names are more useful than full paths)
  if [[ -n "$files" ]]; then
    local file_context
    file_context=$(echo "$files" | head -10 | xargs -I{} dirname {} | sort -u | tr '\n' ' ')
    if [[ -n "$file_context" ]]; then
      query="${query} ${file_context}"
    fi
  fi

  # Trim whitespace
  echo "$query" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | head -c 500
}

SEARCH_QUERY=$(build_query "$PR_TITLE" "$PR_BODY" "$CHANGED_FILES")

if [[ -z "$SEARCH_QUERY" ]]; then
  echo "::warning::Could not build a search query from PR context — skipping."
  echo "facts_found=0" >> "$GITHUB_OUTPUT"
  exit 0
fi

echo "Search query: ${SEARCH_QUERY:0:100}..."

# ── Query Engram ──────────────────────────────────────────────────────

QUERY_PAYLOAD=$(jq -n \
  --arg topic "$SEARCH_QUERY" \
  --argjson limit "$MAX_RESULTS" \
  '{"topic": $topic, "limit": $limit}')

QUERY_RESPONSE=$(curl -sf --max-time 30 \
  -X POST "${BASE_URL}/api/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ENGRAM_INVITE_KEY}" \
  -d "$QUERY_PAYLOAD" 2>&1) || {
  echo "::warning::Engram query failed — skipping scan."
  echo "facts_found=0" >> "$GITHUB_OUTPUT"
  exit 0
}

# ── Filter by relevance threshold ─────────────────────────────────────

FILTERED=$(echo "$QUERY_RESPONSE" | jq \
  --argjson threshold "$RELEVANCE_THRESHOLD" \
  '[.[] | select(.relevance_score >= $threshold)]')

FACT_COUNT=$(echo "$FILTERED" | jq 'length')

echo "facts_found=${FACT_COUNT}" >> "$GITHUB_OUTPUT"
echo "Found ${FACT_COUNT} fact(s) above relevance threshold ${RELEVANCE_THRESHOLD}."

if [[ "$FACT_COUNT" -eq 0 ]]; then
  echo "No relevant facts found. PR looks clear."
  exit 0
fi

# ── Format comment ────────────────────────────────────────────────────

format_comment() {
  local facts_json="$1"
  local pr_title="$2"
  local count="$3"

  local comment=""
  comment+="### Engram Memory Check\n\n"
  comment+="Found **${count}** fact(s) in workspace memory that may be relevant to this PR.\n"
  comment+="Review these before merging to avoid contradicting established team knowledge.\n\n"
  comment+="| Fact | Scope | Agent | Confidence | Date |\n"
  comment+="|------|-------|-------|------------|------|\n"

  while IFS= read -r row; do
    local content scope agent confidence date relevance
    content=$(echo "$row" | jq -r '.content' | head -c 120)
    scope=$(echo "$row" | jq -r '.scope // "-"')
    agent=$(echo "$row" | jq -r '.agent_id // "unknown"')
    confidence=$(echo "$row" | jq -r '.confidence // 0')
    date=$(echo "$row" | jq -r '.committed_at // "-"' | cut -c1-10)
    relevance=$(echo "$row" | jq -r '.relevance_score // 0')

    # Escape pipe characters in content for markdown table
    content=$(echo "$content" | sed 's/|/\\|/g')

    comment+="| ${content} | \`${scope}\` | \`${agent}\` | ${confidence} | ${date} |\n"
  done < <(echo "$facts_json" | jq -c '.[]')

  comment+="\n---\n"
  comment+="<sub>Scanned by [Engram](https://github.com/Agentscreator/Engram) · "
  comment+="Relevance threshold: ${RELEVANCE_THRESHOLD} · "
  comment+="[What is this?](https://github.com/Agentscreator/Engram/blob/main/docs/pr-scanner.md)</sub>"

  echo -e "$comment"
}

COMMENT_BODY=$(format_comment "$FILTERED" "$PR_TITLE" "$FACT_COUNT")

# Write comment body to output (escaped for GitHub Actions)
{
  echo "comment_body<<ENGRAM_EOF"
  echo "$COMMENT_BODY"
  echo "ENGRAM_EOF"
} >> "$GITHUB_OUTPUT"

# ── Post comment ──────────────────────────────────────────────────────

if [[ "$POST_COMMENT" == "true" ]]; then
  echo "Posting comment to PR #${PR_NUMBER}..."

  # Check for existing Engram comment to update instead of spamming
  EXISTING_COMMENT_ID=$(curl -sf --max-time 10 \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GH_REPO}/issues/${PR_NUMBER}/comments" \
    | jq '[.[] | select(.body | startswith("### Engram Memory Check"))][0].id // empty' 2>/dev/null) || EXISTING_COMMENT_ID=""

  if [[ -n "$EXISTING_COMMENT_ID" ]]; then
    # Update existing comment
    curl -sf --max-time 10 \
      -X PATCH \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${GH_REPO}/issues/comments/${EXISTING_COMMENT_ID}" \
      -d "$(jq -n --arg body "$COMMENT_BODY" '{"body": $body}')" > /dev/null

    echo "Updated existing Engram comment on PR #${PR_NUMBER}."
  else
    # Post new comment
    curl -sf --max-time 10 \
      -X POST \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${GH_REPO}/issues/${PR_NUMBER}/comments" \
      -d "$(jq -n --arg body "$COMMENT_BODY" '{"body": $body}')" > /dev/null

    echo "Posted Engram comment on PR #${PR_NUMBER}."
  fi
else
  echo "Dry-run mode — comment not posted."
  echo ""
  echo "$COMMENT_BODY"
fi

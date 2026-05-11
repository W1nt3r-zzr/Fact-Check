#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GITHUB_REPO="${GITHUB_REPO:-W1nt3r-zzr/Fact-Check}"
GIT_REMOTE="${GIT_REMOTE:-Fact-Check}"
BACKEND_QUEUE_URL="${BACKEND_QUEUE_URL:-https://fact-check-production-8d0f.up.railway.app/api/v1/queue-status}"
GH_BIN="${GH_BIN:-.tools/bin/gh}"
PUBLISH=0

usage() {
  cat <<'USAGE'
Usage:
  scripts/release_browser_extension.sh VERSION [--publish]

Examples:
  scripts/release_browser_extension.sh 2.0.2
  scripts/release_browser_extension.sh 2.0.2 --publish

Environment:
  GITHUB_REPO        default: W1nt3r-zzr/Fact-Check
  GIT_REMOTE         default: Fact-Check
  BACKEND_QUEUE_URL  default: Railway queue-status endpoint
  GH_BIN             default: .tools/bin/gh
USAGE
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

VERSION="$1"
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --publish)
      PUBLISH=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
  shift
done

if [[ ! "$VERSION" =~ ^[0-9]+[.][0-9]+[.][0-9]+$ ]]; then
  echo "Version must look like 2.0.2, got: $VERSION" >&2
  exit 2
fi

TAG="v$VERSION"
ZIP_PATH="release/browser-extension-$TAG.zip"

section() {
  printf '\n==> %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

read_versions() {
  python3 - "$VERSION" <<'PY'
import json
import pathlib
import re
import sys

expected = sys.argv[1]
manifest = json.loads(pathlib.Path("browser-extension/manifest.json").read_text())
config = pathlib.Path("browser-extension/config.js").read_text()
match = re.search(r"VERSION:\s*['\"]([^'\"]+)['\"]", config)
if not match:
    raise SystemExit("browser-extension/config.js does not define VERSION")

manifest_version = manifest.get("version")
config_version = match.group(1)
if manifest_version != expected:
    raise SystemExit(f"manifest version {manifest_version!r} does not match expected {expected!r}")
if config_version != expected:
    raise SystemExit(f"config VERSION {config_version!r} does not match expected {expected!r}")
if "W1nt3r-zzr/Fact-Check" not in config:
    raise SystemExit("config.js UPDATE_CHECK repo is not W1nt3r-zzr/Fact-Check")

print(f"version ok: {expected}")
PY
}

check_required_files() {
  local files=(
    "browser-extension/manifest.json"
    "browser-extension/config.js"
    "browser-extension/background.js"
    "browser-extension/content/content.js"
    "browser-extension/content/content.css"
    "browser-extension/popup/popup.html"
    "browser-extension/popup/popup.js"
    "browser-extension/popup/popup.css"
    "browser-extension/utils/dom.js"
    "browser-extension/utils/highlight.js"
    "browser-extension/utils/markdown.js"
    "browser-extension/utils/update.js"
    "backend/config.py"
    "backend/routers/fact_check.py"
    "backend/services/task_queue.py"
  )

  local missing=0
  for file in "${files[@]}"; do
    if [[ ! -f "$file" ]]; then
      echo "Missing required release file: $file" >&2
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    exit 1
  fi
}

check_release_sources_tracked() {
  local untracked
  untracked="$(git status --short browser-extension backend/services/task_queue.py backend/tests/test_task_queue.py | awk '$1 == "??" {print $2}')"
  if [[ -n "$untracked" ]]; then
    echo "Untracked release-critical files exist. Add or ignore them before publishing:" >&2
    echo "$untracked" >&2
    exit 1
  fi
}

run_tests() {
  section "Running browser-extension tests"
  node --test browser-extension/tests/*.test.js

  section "Running backend queue/search tests"
  python3 -m pytest \
    backend/tests/test_task_queue.py \
    backend/tests/test_fact_check_evidence_limit.py \
    backend/tests/test_search_rules.py
}

build_zip() {
  section "Building $ZIP_PATH"
  mkdir -p release
  rm -f "$ZIP_PATH"
  (
    cd browser-extension
    zip -r "../$ZIP_PATH" . -x "*.DS_Store" "tests/*"
  )
}

verify_zip() {
  section "Verifying ZIP contents"
  unzip -p "$ZIP_PATH" manifest.json | python3 -c "import json,sys; data=json.load(sys.stdin); assert data['version'] == '$VERSION', data['version']; print('zip manifest version ok')"
  local config_js
  local content_js
  local content_css
  local zip_entries
  config_js="$(unzip -p "$ZIP_PATH" config.js)"
  content_js="$(unzip -p "$ZIP_PATH" content/content.js)"
  content_css="$(unzip -p "$ZIP_PATH" content/content.css)"
  zip_entries="$(unzip -Z1 "$ZIP_PATH")"

  [[ "$config_js" == *"VERSION: '$VERSION'"* ]]
  [[ "$content_js" == *"queue-status"* ]]
  [[ "$content_js" == *"updateQueueStatus"* ]]
  [[ "$content_js" == *"服务负载"* ]]
  [[ "$content_css" == *".queue-status"* ]]
  [[ "$zip_entries" == *"utils/markdown.js"* ]]
  [[ "$zip_entries" == *"utils/highlight.js"* ]]
  echo "zip queue-status frontend ok"
}

commit_and_publish() {
  section "Preparing publish"
  check_release_sources_tracked

  if [[ ! -x "$GH_BIN" ]]; then
    echo "GitHub CLI not found or not executable: $GH_BIN" >&2
    exit 1
  fi

  if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "Tag already exists locally: $TAG" >&2
    exit 1
  fi

  if git ls-remote --exit-code --tags "$GIT_REMOTE" "$TAG" >/dev/null 2>&1; then
    echo "Tag already exists on remote: $TAG" >&2
    exit 1
  fi

  section "Committing release sources"
  git add \
    browser-extension \
    backend/config.py \
    backend/routers/fact_check.py \
    backend/services/llm_service.py \
    backend/services/task_queue.py \
    backend/tests/test_task_queue.py \
    RELEASE_CHECKLIST.md \
    DEPLOYMENT.md \
    scripts/release_browser_extension.sh \
    .gitignore

  if git diff --cached --quiet; then
    echo "No staged changes to commit."
  else
    git commit -m "发布浏览器插件 $TAG"
  fi

  section "Tagging and pushing"
  git tag "$TAG"
  git push "$GIT_REMOTE" main
  git push "$GIT_REMOTE" "$TAG"

  section "Creating GitHub Release"
  "$GH_BIN" release create "$TAG" "$ZIP_PATH" \
    --repo "$GITHUB_REPO" \
    --title "AI信息核查助手 $TAG" \
    --notes "同步发布 browser-extension $TAG 与后端队列状态支持。" \
    --latest

  section "Waiting for Railway queue endpoint"
  for attempt in {1..18}; do
    if curl -fsS "$BACKEND_QUEUE_URL" | grep -q '"max_concurrent"'; then
      echo "Railway queue endpoint ok"
      return 0
    fi
    echo "Railway not ready yet ($attempt/18); waiting 10s..."
    sleep 10
  done

  echo "Railway queue endpoint did not verify in time: $BACKEND_QUEUE_URL" >&2
  exit 1
}

section "Checking required tools and files"
require_cmd git
require_cmd node
require_cmd python3
require_cmd zip
require_cmd unzip
require_cmd curl
check_required_files
read_versions

run_tests
build_zip
verify_zip

if [[ "$PUBLISH" -eq 1 ]]; then
  commit_and_publish
else
  section "Dry run complete"
  echo "Built: $ZIP_PATH"
  echo "Run with --publish to commit, tag, push, create GitHub Release, and verify Railway."
fi

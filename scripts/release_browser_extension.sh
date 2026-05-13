#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GITHUB_REPO="${GITHUB_REPO:-W1nt3r-zzr/Fact-Check}"
GIT_REMOTE="${GIT_REMOTE:-Fact-Check}"
BACKEND_QUEUE_URL="${BACKEND_QUEUE_URL:-https://fact-check-production-8d0f.up.railway.app/api/v1/queue-status}"
GH_BIN="${GH_BIN:-.tools/bin/gh}"
RELEASE_NOTES_FILE="${RELEASE_NOTES_FILE:-}"
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
  RELEASE_NOTES_FILE optional markdown/text file used for GitHub Release notes
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
  untracked="$(git status --short browser-extension backend/routers backend/services backend/tests/test_task_queue.py backend/tests/test_fact_check_evidence_limit.py backend/tests/test_search_rules.py | awk '$1 == "??" {print $2}')"
  if [[ -n "$untracked" ]]; then
    echo "存在未跟踪的发布关键文件。发布前请先加入 Git 或忽略：" >&2
    echo "$untracked" >&2
    exit 1
  fi
}

run_tests() {
  section "运行浏览器插件测试"
  node --test browser-extension/tests/*.test.js

  section "运行后端队列、证据与搜索测试"
  python3 -m pytest \
    backend/tests/test_task_queue.py \
    backend/tests/test_fact_check_evidence_limit.py \
    backend/tests/test_search_rules.py
}

build_zip() {
  section "构建插件压缩包 $ZIP_PATH"
  mkdir -p release
  rm -f "$ZIP_PATH"
  (
    cd browser-extension
    zip -r "../$ZIP_PATH" . -x "*.DS_Store" "tests/*"
  )
}

verify_zip() {
  section "校验插件压缩包内容"
  unzip -p "$ZIP_PATH" manifest.json | python3 -c "import json,sys; data=json.load(sys.stdin); assert data['version'] == '$VERSION', data['version']; print('zip manifest 版本校验通过')"
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
  echo "zip 队列状态前端资源校验通过"
}

commit_and_publish() {
  section "准备发布"
  check_release_sources_tracked

  if [[ ! -x "$GH_BIN" ]]; then
    echo "找不到 GitHub CLI，或文件不可执行：$GH_BIN" >&2
    exit 1
  fi

  if [[ -n "$RELEASE_NOTES_FILE" && ! -f "$RELEASE_NOTES_FILE" ]]; then
    echo "找不到发布说明文件：$RELEASE_NOTES_FILE" >&2
    exit 1
  fi

  if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "本地标签已存在：$TAG" >&2
    exit 1
  fi

  if git ls-remote --exit-code --tags "$GIT_REMOTE" "$TAG" >/dev/null 2>&1; then
    echo "远端标签已存在：$TAG" >&2
    exit 1
  fi

  section "提交发布源码"
  # 发布包依赖前端插件与后端服务接口协同工作。凡涉及后端服务的改动，
  # 必须随插件版本一起提交并推送，避免线上前端与后端字段不一致。
  git add \
    browser-extension \
    backend/config.py \
    backend/routers \
    backend/services \
    backend/tests/test_task_queue.py \
    backend/tests/test_fact_check_evidence_limit.py \
    backend/tests/test_search_rules.py \
    RELEASE_CHECKLIST.md \
    DEPLOYMENT.md \
    scripts/release_browser_extension.sh \
    .gitignore

  if git diff --cached --quiet; then
    echo "没有可提交的发布改动。"
  else
    git commit -m "发布浏览器插件 $TAG"
  fi

  section "打标签并推送"
  git tag "$TAG"
  git push "$GIT_REMOTE" main
  git push "$GIT_REMOTE" "$TAG"

  section "创建 GitHub Release"
  local notes_args
  if [[ -n "$RELEASE_NOTES_FILE" ]]; then
    notes_args=(--notes-file "$RELEASE_NOTES_FILE")
  else
    notes_args=(--notes "发布浏览器插件 $TAG。本次发布会同步推送插件前端与相关后端服务改动，确保线上字段、证据展示和版本号保持一致。请在正式发布前通过 RELEASE_NOTES_FILE 补充更详细的中文发布说明。")
  fi

  "$GH_BIN" release create "$TAG" "$ZIP_PATH" \
    --repo "$GITHUB_REPO" \
    --title "AI信息核查助手 $TAG" \
    "${notes_args[@]}" \
    --latest

  section "等待 Railway 队列接口恢复"
  for attempt in {1..18}; do
    if curl -fsS "$BACKEND_QUEUE_URL" | grep -q '"max_concurrent"'; then
      echo "Railway 队列接口校验通过"
      return 0
    fi
    echo "Railway 暂未就绪（$attempt/18），等待 10 秒..."
    sleep 10
  done

  echo "Railway 队列接口未在预期时间内通过校验：$BACKEND_QUEUE_URL" >&2
  exit 1
}

section "检查必需工具和文件"
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
  section "预演完成"
  echo "已构建：$ZIP_PATH"
  echo "使用 --publish 可提交、打标签、推送、创建 GitHub Release，并校验 Railway。"
fi

"""
信息核查插件后端服务
Entry point: creates app, wires dependencies, starts server.
"""

import os
import re
import subprocess
import sys
import time
from typing import Optional
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config, logger

from services.link_validator import LinkValidator
from services.consistency_scorer import ConsistencyScorer
from services.evidence_chain_generator import EvidenceChainGenerator

from routers.fact_check import router as fact_check_router, init_dependencies as fc_init
from routers.evidence import router as evidence_router, init_dependencies as ev_init
from routers.validation import router as validation_router, init_dependencies as val_init
from routers.experiment import router as experiment_router

# ---- FastAPI app ----
app = FastAPI(
    title="信息核查插件后端服务",
    description="基于Bocha搜索 + LLM的信息核查API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ---- Initialize services ----
llm_client = None
try:
    from openai import AsyncOpenAI
    llm_client = AsyncOpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL
    )
    logger.info(f"LLM客户端初始化成功 (DeepSeek, model={config.LLM_MODEL})")
except ImportError:
    logger.error("未安装openai库，请运行: pip install openai")
except Exception as e:
    logger.error(f"LLM客户端初始化失败: {e}")

link_validator = LinkValidator(timeout=10.0)
consistency_scorer = ConsistencyScorer()
evidence_chain_generator = EvidenceChainGenerator(
    glm_client=llm_client,
    model_name=config.LLM_MODEL
)

# ---- Inject dependencies into routers ----
fc_init(llm_client, link_validator, consistency_scorer, evidence_chain_generator)
ev_init(evidence_chain_generator)
val_init(link_validator, consistency_scorer)

# ---- Register routers ----
app.include_router(fact_check_router)
app.include_router(evidence_router)
app.include_router(validation_router)
app.include_router(experiment_router)


BUILD_MARKER = "stream-await-fix-20260510"


# ---- Static routes ----
@app.get("/")
async def root():
    return {
        "service": "信息核查插件后端",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "Bocha Web Search",
            "LLM推理（支持深度思考模式）",
            "链接活性检测",
            "一致性评分",
            "证据链生成",
            "流式输出"
        ],
        "endpoints": {
            "fact_check": "/api/v1/check",
            "fact_check_stream": "/api/v1/check/stream",
            "evidence_chain": "/api/v1/evidence-chain",
            "health": "/health",
            "link_validate": "/api/v1/validate-links",
            "consistency_check": "/api/v1/check-consistency",
            "experiment_decision": "/api/v1/experiment/decision"
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/version")
async def version():
    return {
        "version": "2.0.0",
        "build_marker": BUILD_MARKER,
    }


def _repack_zips() -> None:
    """重新打包 A/B 组实验材料 zip 文件，确保 zip 内 URL 与源文件一致。"""
    import zipfile

    releases = {
        "release/实验材料包-A组.zip": "release/实验材料包-A组",
        "release/实验材料包-B组.zip": "release/实验材料包-B组",
    }

    for zip_rel, src_rel in releases.items():
        zip_path = os.path.join(REPO_ROOT, zip_rel)
        src_dir = os.path.join(REPO_ROOT, src_rel)
        if not os.path.isdir(src_dir):
            print(f"[repack] skip, dir not found: {src_rel}")
            continue

        tmp_path = zip_path + ".tmp"
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(src_dir):
                for fn in files:
                    if fn == ".DS_Store":
                        continue
                    file_path = os.path.join(root, fn)
                    arcname = os.path.relpath(file_path, src_dir)
                    zf.write(file_path, arcname)

        os.replace(tmp_path, zip_path)
        print(f"[repack] {zip_rel}")

# ---- Auto tunnel + config sync ----

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUDFLARED_BIN = "/opt/homebrew/Cellar/cloudflared/2026.5.2/bin/cloudflared"
CONFIG_FILES = [
    "browser-extension/config.js",
    "browser-extension-assistant/config.js",
    "experiment/shared.js",
    "release/实验材料包-A组/browser-extension/config.js",
    "release/实验材料包-A组/experiment/shared.js",
    "release/实验材料包-B组/browser-extension-assistant/config.js",
    "release/实验材料包-B组/experiment/shared.js",
]
TUNNEL_PATTERN = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com")
CONFIG_TUNNEL_PATTERN = re.compile(r"https://[a-z0-9.-]+\.trycloudflare\.com")


def _find_tunnel_url(line: str) -> "Optional[str]":
    m = TUNNEL_PATTERN.search(line)
    return m.group(0) if m else None


def _update_config_files(new_url: str) -> "Optional[str]":
    """Replace old trycloudflare URLs with new_url in all config files."""
    old_url = None
    for rel in CONFIG_FILES:
        path = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        old_matches = CONFIG_TUNNEL_PATTERN.findall(text)
        if old_matches and not old_url:
            old_url = old_matches[0]
        if old_matches:
            new_text = CONFIG_TUNNEL_PATTERN.sub(new_url, text)
            open(path, "w", encoding="utf-8").write(new_text)
    return old_url


def start_tunnel(port: int) -> None:
    """Start cloudflared tunnel, wait for URL, update all configs."""
    if not os.path.isfile(CLOUDFLARED_BIN):
        print(f"[tunnel] cloudflared not found at {CLOUDFLARED_BIN}, skipping")
        return

    print(f"[tunnel] Starting Cloudflare Tunnel → http://127.0.0.1:{port} ...")
    proc = subprocess.Popen(
        [CLOUDFLARED_BIN, "--config", "/dev/null", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    import threading
    from queue import Queue, Empty

    line_queue: Queue = Queue()
    tunnel_url = None
    start = time.time()
    timeout = 60

    def _reader():
        """在后台线程逐行读取 proc.stdout，放入队列，避免 buffer 满阻塞。"""
        try:
            for line in proc.stdout:
                line_queue.put(line)
        except Exception:
            pass
        finally:
            line_queue.put(None)  # sentinel: 读取完毕

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        while True:
            try:
                line = line_queue.get(timeout=0.5)
            except Empty:
                if time.time() - start > timeout:
                    print(f"[tunnel] Timeout waiting for URL after {timeout}s")
                    break
                continue

            if line is None:  # sentinel: proc.stdout 已关闭
                break

            sys.stdout.write(line)
            sys.stdout.flush()

            if tunnel_url is None:
                found = _find_tunnel_url(line)
                if found:
                    tunnel_url = found
                    old_url = _update_config_files(tunnel_url)
                    if old_url and old_url != tunnel_url:
                        print(f"\n[tunnel] Config updated: {old_url} → {tunnel_url}")
                    else:
                        print(f"\n[tunnel] Tunnel URL: {tunnel_url}")
                    print(f"[tunnel] {len(CONFIG_FILES)} config files synced")
                    _repack_zips()
                    # URL 已获取，后续输出由后台 reader 自行丢弃（不做 print）
                    break
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[tunnel] Error: {e}")

    if tunnel_url is None:
        print("[tunnel] Failed to obtain tunnel URL — plugins may not connect from remote")
    else:
        print(f"[tunnel] Ready: {tunnel_url}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", config.PORT))
    start_tunnel(port)
    uvicorn.run(app, host=config.HOST, port=port, log_level="info")

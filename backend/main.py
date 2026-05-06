"""
信息核查插件后端服务
Entry point: creates app, wires dependencies, starts server.
"""

import os
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
    from openai import OpenAI
    llm_client = OpenAI(
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


BUILD_MARKER = "core-evidence-refilter-746ef4d"


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
            "consistency_check": "/api/v1/check-consistency"
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
        "git_commit": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
        "git_branch": os.getenv("RAILWAY_GIT_BRANCH", ""),
        "git_repo": os.getenv("RAILWAY_GIT_REPO_NAME", ""),
        "service": os.getenv("RAILWAY_SERVICE_NAME", ""),
        "environment": os.getenv("RAILWAY_ENVIRONMENT_NAME", ""),
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", config.PORT))
    uvicorn.run(app, host=config.HOST, port=port, log_level="info")

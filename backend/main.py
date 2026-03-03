"""
事实核查插件后端服务
基于博查AI Web Search + GLM-4.5-Flash的事实核查服务
面向中国普通网民的浏览器插件后端API
"""

import os
import json
import re
import time
import logging
from typing import Dict, Any, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 环境配置
class Config:
    # 博查AI配置
    BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "sk-7adb75302d134cb8a0452dabb3eb43c3")
    BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"

    # GLM配置
    ZAI_API_KEY = os.getenv("ZAI_API_KEY", "ca21a4e960624dd08c6d58d7e668573f.ySQNPyZQYLMxPLzG")
    ZAI_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

    # 服务配置
    HOST = "0.0.0.0"
    PORT = 8000

    # CORS配置
    ALLOWED_ORIGINS = [
        "chrome-extension://*",
        "http://localhost:*",
        "https://localhost:*"
    ]

config = Config()

# 请求/响应模型
class FactCheckRequest(BaseModel):
    claim: str = Field(..., description="待核查的文本内容", min_length=1, max_length=500)

class FactCheckResponse(BaseModel):
    verdict: str = Field(..., description="核查结论：属实 / 不实 / 信息不足，无法判断")
    evidence_quote: str = Field(..., description="证据引用原文")
    source_url: str = Field(..., description="证据来源URL")
    search_keywords: str = Field(..., description="搜索关键词")
    uncertainty_note: str = Field(..., description="不确定性说明")
    reasoning: str = Field(..., description="推理过程说明")

# 搜索结果模型
class SearchResult(BaseModel):
    name: str
    url: str
    summary: str
    date_published: str

# 创建FastAPI应用
app = FastAPI(
    title="事实核查插件后端服务",
    description="基于博查AI + GLM-4.5-Flash的事实核查API",
    version="1.0.0",
    docs_url=None,  # 生产环境关闭文档
    redoc_url=None
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 初始化GLM客户端
try:
    from zai import ZhipuAiClient
    zhipu_client = ZhipuAiClient(
        api_key=config.ZAI_API_KEY,
        base_url=config.ZAI_BASE_URL
    )
    logger.info("GLM-4.5-Flash客户端初始化成功")
except ImportError:
    logger.error("未安装zai-sdk，请运行: pip install zai-sdk")
    zhipu_client = None
except Exception as e:
    logger.error(f"GLM客户端初始化失败: {e}")
    zhipu_client = None


async def search_with_bocha(claim: str) -> List[SearchResult]:
    """调用博查AI Web Search API检索证据"""

    headers = {
        "Authorization": config.BOCHA_API_KEY,
        "Content-Type": "application/json"
    }

    data = {
        "query": claim,
        "summary": True,
        "freshness": "noLimit",
        "count": 10  # 测试是否支持10个结果
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"调用博查API搜索: {claim}")
            response = await client.post(config.BOCHA_ENDPOINT, headers=headers, json=data)
            response.raise_for_status()

            result = response.json()
            logger.info(f"博查API完整响应: {result}")

            # 正确解析嵌套的数据结构
            data = result.get("data", {})
            web_pages = data.get("webPages", {}).get("value", [])

            if not web_pages:
                logger.warning("博查API未返回搜索结果")
                logger.warning(f"响应结构: {list(result.keys())}")
                return []

            # 处理搜索结果，过滤低质量来源
            search_results = []
            for page in web_pages:
                search_result = SearchResult(
                    name=page.get("name", ""),
                    url=page.get("url", ""),
                    summary=page.get("summary", "") or page.get("snippet", ""),
                    date_published=page.get("datePublished", "")
                )
                search_results.append(search_result)

            logger.info(f"博查API返回 {len(search_results)} 个有效搜索结果")
            return search_results

    except httpx.HTTPStatusError as e:
        logger.error(f"博查API请求失败: {e.response.status_code} - {e.response.text}")
        return []
    except Exception as e:
        logger.error(f"博查API调用异常: {e}")
        return []

def extract_structured_info_from_reasoning(reasoning_text: str) -> Dict[str, Any]:
    """从GLM的自然语言分析中提取结构化信息"""

    # 默认结构
    result = {
        "verdict": "信息不足，无法判断",
        "evidence_quote": "无",
        "source_url": "",
        "search_keywords": "",
        "uncertainty_note": "无",
        "reasoning": reasoning_text[:500] + "..." if len(reasoning_text) > 500 else reasoning_text
    }

    if not reasoning_text:
        return result

    try:
        # 1. 提取verdict（结论判断）- 适应新的Prompt结构
        verdict_patterns = [
            r'结论判断[：:]\s*(.+?)[。,;\n]',
            r'结论[：:]\s*(.+?)[。,;\n]',
            r'判定[：:]\s*(.+?)[。,;\n]',
            r'1[\.、]\s*.*?结论.*?[：:]\s*(.+?)[。,;\n]',
            r'(属实|不实|信息不足[，,]无法判断)'
        ]

        for pattern in verdict_patterns:
            match = re.search(pattern, reasoning_text, re.IGNORECASE)
            if match:
                verdict = match.group(1).strip()
                if "属实" in verdict:
                    result["verdict"] = "属实"
                elif "不实" in verdict:
                    result["verdict"] = "不实"
                elif "信息不足" in verdict:
                    result["verdict"] = "信息不足，无法判断"
                break

        # 2. 提取evidence_quote（关键证据）- 适应新的Prompt结构
        quote_patterns = [
            r'关键证据[：:]\s*([^。\n]+)',
            r'2[\.、]\s*.*?关键证据.*?[：:]\s*([^。\n]+)',
            r'证据[：:]\s*([^。\n]{10,100})',  # 限制长度
            r'引用[：:]\s*([^。\n]+)',
            r'根据.*?[：:]\s*([^。\n]+)'
        ]

        for pattern in quote_patterns:
            match = re.search(pattern, reasoning_text, re.IGNORECASE)
            if match and len(match.group(1).strip()) > 5:
                quote = match.group(1).strip()
                # 去掉引号
                quote = quote.strip('"\'""')
                result["evidence_quote"] = quote[:50]  # 限制长度
                break

        # 3. 提取source_url（证据来源）- 适应新的Prompt结构
        url_patterns = [
            r'证据来源[：:]\s*(https?://[^\s\),\n]+)',
            r'3[\.、]\s*.*?证据来源.*?[：:]\s*(https?://[^\s\),\n]+)',
            r'URL[：:]\s*(https?://[^\s\),\n]+)',
            r'链接[：:]\s*(https?://[^\s\),\n]+)',
            r'(https?://[^\s\),\n]+)'  # 通用匹配
        ]

        for pattern in url_patterns:
            match = re.search(pattern, reasoning_text, re.IGNORECASE)
            if match:
                result["source_url"] = match.group(1).strip()
                break

        # 4. 提取uncertainty_note（不确定性）- 适应新的Prompt结构
        uncertainty_patterns = [
            r'不确定性[：:]\s*([^。\n]+)',
            r'5[\.、]\s*.*?不确定性.*?[：:]\s*([^。\n]+)',
            r'信息缺口[：:]\s*([^。\n]+)',
            r'需要注意[：:]\s*([^。\n]+)',
            r'不确定[：:]\s*([^。\n]+)'
        ]

        for pattern in uncertainty_patterns:
            match = re.search(pattern, reasoning_text, re.IGNORECASE)
            if match:
                uncertainty = match.group(1).strip()
                if uncertainty and uncertainty.lower() != "无" and uncertainty.lower() != "none":
                    result["uncertainty_note"] = uncertainty
                break

        # 5. 智能分析不确定性指示词
        if result["uncertainty_note"] == "无":
            uncertainty_indicators = [
                r'但是[，,]?\s*([^。\n]{5,50})',
                r'然而[，,]?\s*([^。\n]{5,50})',
                r'需要.*?([^。\n]{5,50})',
                r'缺乏.*?([^。\n]{5,50})',
                r'可能[，,]?\s*([^。\n]{5,50})',
                r'不足[^。\n]*?([^。\n]{5,50})'
            ]

            for pattern in uncertainty_indicators:
                match = re.search(pattern, reasoning_text)
                if match:
                    result["uncertainty_note"] = match.group(1).strip()
                    break

        # 6. 提取搜索关键词（推理生成）
        keyword_patterns = [
            r'关键词[：:]\s*([^。\n]+)',
            r'搜索.*?[：:]\s*([^。\n]+)',
            r'检索.*?[：:]\s*([^。\n]+)'
        ]

        for pattern in keyword_patterns:
            match = re.search(pattern, reasoning_text, re.IGNORECASE)
            if match:
                result["search_keywords"] = match.group(1).strip()
                break

        logger.info(f"从自然语言分析中提取的结构化信息: {result}")
        return result

    except Exception as e:
        logger.error(f"从自然语言分析中提取结构化信息失败: {e}")
        return result

def format_evidence_list(evidence: List[SearchResult]) -> str:
    """格式化证据列表为指定格式"""
    evidence_text = ""
    for i, item in enumerate(evidence, 1):
        evidence_text += f"""- [{item.name}]({item.url})
  摘要：{item.summary}
  发布时间：{item.date_published}
"""
    return evidence_text

def build_glm_prompt(claim: str, evidence_list: List[SearchResult]) -> str:
    """构造GLM-4.5-Flash推理Prompt"""

    evidence_text = format_evidence_list(evidence_list)

    prompt = f"""你是一名专业的事实核查助手，请帮助我分析以下说法的可信度。

【待核查说法】
{claim}

【检索到的证据】
{evidence_text}

【分析任务】
请基于上述证据进行客观分析，并给出你的推理过程。请按以下结构进行分析：

1. **结论判断**：这个说法是属实、不实，还是信息不足无法判断？
2. **关键证据**：从证据中引用最重要的一句话
3. **证据来源**：提供最有力证据的URL链接
4. **分析过程**：详细说明你是如何根据证据得出结论的
5. **不确定性**：是否存在信息缺口或需要注意的地方？

【分析要求】
- 严格基于提供的证据，不要编造信息
- 引用的证据必须忠实原文
- 推理要清晰、客观、有逻辑
- 重点展示分析过程，让读者能够理解你的判断依据
- 如果证据不足或矛盾，请明确指出

请开始你的分析："""

    return prompt

async def call_glm_api(prompt: str) -> Dict[str, Any]:
    """调用GLM-4.5-Flash API进行推理"""

    if not zhipu_client:
        return {
            "verdict": "信息不足，无法判断",
            "evidence_quote": "无",
            "source_url": "",
            "search_keywords": "",
            "uncertainty_note": "模型初始化失败，请稍后重试",
            "reasoning": "GLM-4.5-Flash客户端初始化失败"
        }

    try:
        logger.info("调用GLM-4.5-Flash进行推理...")

        response = zhipu_client.chat.completions.create(
            model="glm-4.5-flash",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000,  # 增加token数量避免被截断
            stream=False
        )

        message = response.choices[0].message
        result_text = message.content

        # 优先使用reasoning_content，如果content为空的话
        if not result_text or result_text.strip() == '':
            if hasattr(message, 'reasoning_content') and message.reasoning_content:
                result_text = message.reasoning_content
                logger.info("使用reasoning_content作为主要响应内容")

        logger.info(f"GLM原始响应长度: {len(result_text) if result_text else 0}")
        logger.info(f"GLM原始响应: {result_text[:500] if result_text else '空响应'}...")

        # 检查响应的其他字段
        if hasattr(response.choices[0], 'finish_reason'):
            logger.info(f"GLM完成原因: {response.choices[0].finish_reason}")

        # 尝试解析JSON
        try:
            result = json.loads(result_text)
            logger.info("GLM响应解析成功")
            return result
        except json.JSONDecodeError:
            # 尝试用正则提取JSON
            json_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', result_text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    logger.info("通过正则提取JSON成功")
                    return result
                except json.JSONDecodeError:
                    pass

            # 如果JSON解析失败，使用自然语言提取
            logger.info("JSON解析失败，尝试从自然语言推理中提取结构化信息")
            structured_result = extract_structured_info_from_reasoning(result_text)
            return structured_result

    except Exception as e:
        logger.error(f"GLM API调用失败: {e}")
        return {
            "verdict": "信息不足，无法判断",
            "evidence_quote": "无",
            "source_url": "",
            "search_keywords": "",
            "uncertainty_note": "模型调用失败，请稍后重试",
            "reasoning": f"API调用异常: {str(e)}"
        }

@app.post("/api/v1/check", response_model=FactCheckResponse)
async def fact_check(request: FactCheckRequest):
    """事实核查主接口"""
    start_time = time.time()

    try:
        logger.info(f"开始核查: {request.claim}")

        # 步骤1: 调用博查AI搜索
        search_results = await search_with_bocha(request.claim)

        # 步骤2: 如果没有有效结果，直接返回信息不足
        if not search_results:
            logger.warning("未找到有效搜索结果")
            return FactCheckResponse(
                verdict="信息不足，无法判断",
                evidence_quote="无",
                source_url="",
                search_keywords=request.claim,
                uncertainty_note="未找到权威信息源",
                reasoning="博查AI未返回相关搜索结果，无法进行事实核查"
            )

        # 步骤3: 构造GLM推理Prompt
        prompt = build_glm_prompt(request.claim, search_results)

        # 步骤4: 调用GLM进行推理
        reasoning_result = await call_glm_api(prompt)

        # 步骤5: 返回结果
        logger.info(f"核查完成，耗时: {(time.time() - start_time)*1000:.1f}ms")

        return FactCheckResponse(
            verdict=reasoning_result.get("verdict", "信息不足，无法判断"),
            evidence_quote=reasoning_result.get("evidence_quote", "无"),
            source_url=reasoning_result.get("source_url", ""),
            search_keywords=reasoning_result.get("search_keywords", request.claim),
            uncertainty_note=reasoning_result.get("uncertainty_note", "无"),
            reasoning=reasoning_result.get("reasoning", "推理过程未提供")
        )

    except Exception as e:
        logger.error(f"事实核查异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="事实核查服务异常")

@app.get("/")
async def root():
    """服务状态检查"""
    return {
        "service": "事实核查插件后端",
        "version": "1.0.0",
        "status": "running",
        "features": ["博查AI搜索", "GLM-4.5-Flash推理"]
    }

@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level="info"
    )
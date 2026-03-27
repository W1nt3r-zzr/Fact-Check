"""
信息核查插件后端服务
基于博查AI Web Search + GLM-5的信息核查服务
面向中国普通网民的浏览器插件后端API

支持功能：
- 深度思考模式（Deep Thinking）
- 流式输出（Streaming）
- 流式工具调用（Streaming Tool Call）
- 链接活性检测
- 一致性评分
"""

import os
import json
import re
import time
import logging
import asyncio
from typing import Dict, Any, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 导入自定义服务模块
from services.link_validator import LinkValidator, LinkValidationResult
from services.consistency_scorer import ConsistencyScorer, ConsistencyScore
from services.evidence_chain_generator import EvidenceChainGenerator, EvidenceChain

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

    # GLM-5配置
    ZAI_API_KEY = os.getenv("ZAI_API_KEY", "ca21a4e960624dd08c6d58d7e668573f.ySQNPyZQYLMxPLzG")
    ZAI_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
    GLM_MODEL = "glm-5"  # 更新为GLM-5模型

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
    enable_thinking: bool = Field(True, description="是否启用深度思考模式")
    stream: bool = Field(False, description="是否启用流式输出")
    enable_link_validation: bool = Field(False, description="是否启用链接活性检测")
    enable_consistency_check: bool = Field(False, description="是否启用一致性评分")
    enable_evidence_chain: bool = Field(False, description="是否启用证据链生成")

class FactCheckResponse(BaseModel):
    verdict: str = Field(..., description="核查结论：属实 / 不实 / 信息不足，无法判断")
    evidence_quote: str = Field(..., description="证据引用原文")
    source_url: str = Field(..., description="证据来源URL")
    search_keywords: str = Field(..., description="搜索关键词")
    uncertainty_note: str = Field(..., description="不确定性说明")
    reasoning: str = Field(..., description="推理过程说明")
    confidence: Optional[float] = Field(None, description="置信度（0-100）")

    # 新增：验证信息和思考过程
    thinking_process: Optional[str] = Field(None, description="深度思考过程（如果启用）")
    link_validation: Optional[Dict[str, Any]] = Field(None, description="链接活性检测结果")
    consistency_score: Optional[Dict[str, Any]] = Field(None, description="一致性评分结果")
    evidence_chain: Optional[Dict[str, Any]] = Field(None, description="证据链数据（如果启用）")

# 证据链请求/响应模型
class EvidenceChainRequest(BaseModel):
    claim: str = Field(..., description="待核查的说法", min_length=1, max_length=500)
    enable_link_validation: bool = Field(False, description="是否验证链接活性")
    top_k: int = Field(5, description="返回Top K个证据", ge=1, le=20)

# 搜索结果模型
class SearchResult(BaseModel):
    name: str
    url: str
    summary: str
    date_published: str

# 创建FastAPI应用
app = FastAPI(
    title="信息核查插件后端服务",
    description="基于夸克搜索 + GLM-5的信息核查API，支持深度思考模式与流式输出",
    version="2.0.0",
    docs_url=None,  # 生产环境关闭文档
    redoc_url=None
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源（支持content script从任意网页请求）
    allow_credentials=False,  # 允许所有来源时必须设为False
    allow_methods=["*"],
    allow_headers=["*"]
)

# 初始化服务组件
link_validator = LinkValidator(timeout=10.0)
consistency_scorer = ConsistencyScorer()

# 初始化GLM客户端
try:
    from zai import ZhipuAiClient
    zhipu_client = ZhipuAiClient(
        api_key=config.ZAI_API_KEY,
        base_url=config.ZAI_BASE_URL
    )
    logger.info("GLM-5客户端初始化成功（支持深度思考模式与流式输出）")
except ImportError:
    logger.error("未安装zai-sdk，请运行: pip install zai-sdk")
    zhipu_client = None
except Exception as e:
    logger.error(f"GLM客户端初始化失败: {e}")
    zhipu_client = None

# 初始化证据链生成器（在GLM客户端初始化之后，以便传入客户端用于立场检测）
evidence_chain_generator = EvidenceChainGenerator(glm_client=zhipu_client)


async def search_with_zhipu(claim: str) -> List[SearchResult]:
    """
    使用智谱AI的Web Search API检索证据
    API端点: https://open.bigmodel.cn/api/paas/v4/web_search
    """

    if not zhipu_client:
        logger.error("智谱客户端未初始化")
        return []

    try:
        logger.info(f"使用智谱AI Web Search API搜索: {claim}")

        # 调用智谱AI的Web Search API
        url = f"{config.ZAI_BASE_URL}/web_search"
        headers = {
            "Authorization": f"Bearer {config.ZAI_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "search_query": claim,
            "search_engine": "search_pro_quark",  # 使用夸克搜索引擎
            "top_k": 50  # 返回前50个结果
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

            result = response.json()
            logger.info(f"智谱AI Web Search API响应: {result}")

            # 解析搜索结果
            search_results = []

            # 智谱AI Web Search API返回格式（夸克引擎）
            if "search_result" in result:
                for item in result["search_result"]:
                    search_result = SearchResult(
                        name=item.get("title", ""),
                        url=item.get("link", ""),
                        summary=item.get("content", "") or item.get("description", "") or item.get("snippet", ""),
                        date_published=item.get("publish_date", "") or item.get("date", "")
                    )
                    search_results.append(search_result)
            elif "web_pages" in result:
                for item in result["web_pages"]:
                    search_result = SearchResult(
                        name=item.get("title", ""),
                        url=item.get("link", ""),
                        summary=item.get("content", "") or item.get("description", ""),
                        date_published=item.get("date", "")
                    )
                    search_results.append(search_result)
            elif "items" in result:
                for item in result["items"]:
                    search_result = SearchResult(
                        name=item.get("title", ""),
                        url=item.get("link", ""),
                        summary=item.get("snippet", "") or item.get("description", ""),
                        date_published=item.get("date", "")
                    )
                    search_results.append(search_result)

            logger.info(f"智谱AI Web Search API返回 {len(search_results)} 个结果")
            return search_results

    except httpx.HTTPStatusError as e:
        logger.error(f"智谱AI Web Search API请求失败: {e.response.status_code} - {e.response.text}")
        return []
    except Exception as e:
        logger.error(f"智谱AI Web Search API调用异常: {e}")
        import traceback
        traceback.print_exc()
        return []

def extract_structured_info_from_reasoning(reasoning_text: str) -> Dict[str, Any]:
    """从GLM的自然语言分析中提取结构化信息（支持Markdown格式）"""

    # 默认结构 - verdict现在完全由证据链模块生成，这里不做提取
    result = {
        "verdict": "详见下方证据链分析",  # 固定默认值，不尝试从推理中提取
        "evidence_quote": "无",
        "source_url": "",
        "search_keywords": "",
        "uncertainty_note": "无",
        "reasoning": reasoning_text[:4000] + "...\n\n[内容过长，已截断。完整推理请参考证据分析]" if len(reasoning_text) > 4000 else reasoning_text
    }

    if not reasoning_text:
        return result

    try:
        # 不再提取verdict - 结论完全由证据链模块生成
        # 推理过程专注于证据分析，不包含结论判断

        # 提取evidence_quote（关键证据）- 支持Markdown格式
        # 首先尝试找到"关键引用"部分

        # 2. 提取evidence_quote（关键证据）- 支持Markdown格式
        # 首先尝试找到"### 2. 关键证据"部分
        evidence_section = re.search(
            r'###\s*2[\.、]\s*.*?关键证据.*?\n+(.+?)(?=###\s*\d+|不确定性|$)',
            reasoning_text,
            re.IGNORECASE | re.DOTALL
        )

        if evidence_section:
            evidence_text = evidence_section.group(1).strip()
            # 清理Markdown格式
            evidence_text = re.sub(r'\*\*', '', evidence_text)  # 去除加粗
            evidence_text = re.sub(r'["""]', '"', evidence_text)  # 统一引号
            evidence_text = re.sub(r'\n+', ' ', evidence_text)  # 合并多行
            evidence_text = evidence_text.strip()

            if len(evidence_text) > 10:
                result["evidence_quote"] = evidence_text[:200]  # 限制长度
        else:
            # 降级：使用旧的正则匹配
            quote_patterns = [
                r'关键证据[：:]\s*([^。\n]{10,100})',
                r'证据[：:]\s*([^。\n]{10,100})',
                r'引用[：:]\s*([^。\n]+)',
                r'根据.*?[：:]\s*([^。\n]+)'
            ]
            for pattern in quote_patterns:
                match = re.search(pattern, reasoning_text, re.IGNORECASE)
                if match and len(match.group(1).strip()) > 5:
                    quote = match.group(1).strip()
                    quote = quote.strip('"\'""')
                    result["evidence_quote"] = quote[:50]
                    break

        # 3. 提取source_url（证据来源）- 支持Markdown格式
        source_section = re.search(
            r'###\s*3[\.、]\s*.*?证据来源.*?\n+(.+?)(?=###\s*\d+|分析过程|$)',
            reasoning_text,
            re.IGNORECASE | re.DOTALL
        )

        if source_section:
            source_text = source_section.group(1).strip()
            # 提取URL
            url_match = re.search(r'(https?://[^\s\)]+)', source_text)
            if url_match:
                result["source_url"] = url_match.group(1)
        else:
            # 降级：在整个文本中查找URL
            url_patterns = [
                r'证据来源[：:]\s*(https?://[^\s\),\n]+)',
                r'URL[：:]\s*(https?://[^\s\),\n]+)',
                r'链接[：:]\s*(https?://[^\s\),\n]+)',
                r'(https?://[^\s\),\n]+)'
            ]
            for pattern in url_patterns:
                match = re.search(pattern, reasoning_text, re.IGNORECASE)
                if match:
                    result["source_url"] = match.group(1).strip()
                    break

        # 4. 提取uncertainty_note（不确定性）- 支持Markdown格式
        uncertainty_section = re.search(
            r'###\s*5[\.、]\s*.*?不确定.*?\n+(.+?)(?=###\s*\d+|$)',
            reasoning_text,
            re.IGNORECASE | re.DOTALL
        )

        if uncertainty_section:
            uncertainty_text = uncertainty_section.group(1).strip()
            # 清理格式
            uncertainty_text = re.sub(r'\*\*', '', uncertainty_text)
            uncertainty_text = re.sub(r'\n+', ' ', uncertainty_text)
            uncertainty_text = uncertainty_text.strip()

            if len(uncertainty_text) > 5:
                result["uncertainty_note"] = uncertainty_text[:300]
        else:
            # 降级：使用旧的正则匹配
            uncertainty_patterns = [
                r'不确定性[：:]\s*([^。\n]+)',
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

        # 5. 智能分析不确定性指示词（如果未找到）
        if result["uncertainty_note"] == "无":
            uncertainty_indicators = [
                r'但是[，,]?\s*([^。\n]{5,100})',
                r'然而[，,]?\s*([^。\n]{5,100})',
                r'需要.*?([^。\n]{5,100})',
                r'缺乏.*?([^。\n]{5,100})',
                r'可能[，,]?\s*([^。\n]{5,100})',
                r'注意.*?([^。\n]{5,100})'
            ]
            for pattern in uncertainty_indicators:
                match = re.search(pattern, reasoning_text)
                if match:
                    result["uncertainty_note"] = match.group(1).strip()
                    break

        logger.info(f"从自然语言分析中提取的结构化信息: {result}")
        return result

    except Exception as e:
        logger.error(f"从自然语言分析中提取结构化信息失败: {e}")
        return result

def format_evidence_list(evidence: List[SearchResult]) -> str:
    """格式化证据列表为指定格式"""
    evidence_text = ""
    for item in evidence:
        evidence_text += f"""- [{item.name}]({item.url})
  摘要：{item.summary}
  发布时间：{item.date_published}
"""
    return evidence_text

def build_glm_prompt(claim: str, evidence_list: List[SearchResult]) -> str:
    """构造GLM-5推理Prompt（带实时日期上下文）"""

    evidence_text = format_evidence_list(evidence_list)

    # 获取当前日期
    from datetime import datetime
    current_date = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""你是一名专业的信息核查助手，具有联网搜索能力，请帮助我分析以下说法的可信度。

【重要提示】
- **当前日期**：{current_date}
- **证据来源**：以下证据是通过**实时联网搜索**获得的最新信息
- **时效性**：请以搜索结果的发布时间为准，不要怀疑日期的真实性
- **分析原则**：搜索结果中的日期是真实的当前时间信息，请以此为准进行分析

【待核查说法】
{claim}

【检索到的实时证据】
{evidence_text}

【分析任务】
请基于上述**实时联网搜索**获得的证据进行客观分析，重点展示证据分析和推理过程。

**⚠️ 格式要求（必须严格遵守）**

请严格按照以下格式输出每个证据的立场分析：

```
### 1. 证据立场分析

*   **证据 [1] [证据标题](证据URL)**
    *   **立场**：**支持**（请选择：支持/反对/中性，三者选一）
    *   **分析**：简要说明该证据为何持此立场（基于来源权威性、时效性等）

*   **证据 [2] [证据标题](证据URL)**
    *   **立场**：**支持**
    *   **分析**：简要说明...

（以此类推，逐一分析所有证据）
```

**格式说明**：
- 每个证据必须单独列出，使用`*   **证据 [序号] [标题](URL)**`格式
- 立场必须是以下三个词之一：**支持**、**反对**、**中性**（不要使用"强支持"、"部分支持"等其他表述）
- 序号从1开始，依次递增
- 每个证据必须包含标题和URL（URL必须用Markdown链接格式）

请按以下结构进行分析：

1. **证据立场分析**：逐一分析各个证据对该说法的立场
   - **必须使用上述指定格式**，格式不正确会导致系统无法提取立场信息
   - 明确指出每个证据是"支持"、"反对"还是"中性"（三者选一）
   - 说明证据的可信度（基于来源权威性、时效性等）

2. **关键引用**：从证据中引用最重要的句子
   - 使用Markdown链接格式：[证据标题](URL)
   - 引用能体现证据立场的关键内容

3. **证据关系分析**：说明不同证据之间的关系
   - 支持性证据之间是否相互印证
   - 反对性证据的反对理由是什么
   - 证据之间是否存在矛盾

4. **不确定性与局限**：指出信息缺口和需要注意的地方
   - 证据数量是否充足
   - 时效性问题
   - 信息来源的局限性

【重要约束】
- **严格禁止**在分析中给出任何形式的最终结论或判定
- **不要说**"综上所述..."、"因此..."、"判断为..."等总结性语句
- **不要使用**"属实"、"不实"、"部分属实"等结论性词汇
- 专注于**分析证据本身**，而非给出结论
- 结论由专门的证据链统计模块基于证据立场分布自动生成
- **必须严格遵守上述格式要求**，否则立场提取会失败

请开始你的分析："""

    return prompt

async def call_glm_api(
    prompt: str,
    enable_thinking: bool = True,
    stream: bool = False
) -> Dict[str, Any]:
    """
    调用GLM-5 API进行推理

    Args:
        prompt: 推理提示词
        enable_thinking: 是否启用深度思考模式
        stream: 是否启用流式输出

    Returns:
        Dict[str, Any]: 推理结果
    """

    if not zhipu_client:
        return {
            "verdict": "信息不足，无法判断",
            "evidence_quote": "无",
            "source_url": "",
            "search_keywords": "",
            "uncertainty_note": "模型初始化失败，请稍后重试",
            "reasoning": "GLM-5客户端初始化失败",
            "thinking_process": None
        }

    try:
        logger.info(f"调用GLM-5进行推理（思考模式: {enable_thinking}, 流式: {stream}）...")

        # 构建请求参数
        request_params = {
            "model": config.GLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 8000,  # 增加到8000以确保完整输出推理过程
            "stream": stream,
        }

        # 注意：GLM-5可能默认支持深度思考，无需特殊参数
        if enable_thinking:
            logger.info("深度思考模式已启用（GLM-5原生支持）")

        response = zhipu_client.chat.completions.create(**request_params)

        # 处理流式响应
        if stream:
            return await _handle_streaming_response(response)

        # 处理非流式响应
        message = response.choices[0].message
        result_text = message.content

        # 提取思考过程
        thinking_process = None
        if enable_thinking and hasattr(message, 'reasoning_content') and message.reasoning_content:
            thinking_process = message.reasoning_content
            logger.info(f"提取到思考过程，长度: {len(thinking_process)}")

        # 如果content为空，尝试使用reasoning_content
        if not result_text or result_text.strip() == '':
            if thinking_process:
                result_text = thinking_process
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
            if thinking_process:
                result["thinking_process"] = thinking_process
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
            if thinking_process:
                structured_result["thinking_process"] = thinking_process
            return structured_result

    except Exception as e:
        logger.error(f"GLM API调用失败: {e}")
        return {
            "verdict": "信息不足，无法判断",
            "evidence_quote": "无",
            "source_url": "",
            "search_keywords": "",
            "uncertainty_note": "模型调用失败，请稍后重试",
            "reasoning": f"API调用异常: {str(e)}",
            "thinking_process": None
        }


async def _handle_streaming_response(response) -> Dict[str, Any]:
    """
    处理流式响应（暂不实现，返回完整响应）

    Args:
        response: 流式响应对象

    Returns:
        Dict[str, Any]: 解析后的结果
    """
    # TODO: 实现真正的流式响应处理
    # 目前先收集完整响应再处理
    logger.info("流式响应处理（暂不完整实现）")
    return {"error": "流式响应暂未实现"}


# 流式响应的完整实现示例（供未来参考）
async def call_glm_api_streaming(prompt: str, enable_thinking: bool = True):
    """
    GLM-5流式API调用示例（保留供未来实现）

    Usage:
        async for chunk in call_glm_api_streaming(prompt):
            print(chunk)
    """
    if not zhipu_client:
        yield {"error": "模型未初始化"}
        return

    try:
        request_params = {
            "model": config.GLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 3000,
            "stream": True,
        }

        # 注意：GLM-5可能默认支持深度思考，无需特殊参数
        if enable_thinking:
            logger.info("深度思考模式已启用（GLM-5原生支持）")

        response = zhipu_client.chat.completions.create(**request_params)

        full_content = ""
        thinking_content = ""

        for chunk in response:
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta

                # 提取内容
                if hasattr(delta, 'content') and delta.content:
                    full_content += delta.content
                    yield {
                        "type": "content",
                        "content": delta.content,
                        "finished": False
                    }

                # 提取思考过程
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    thinking_content += delta.reasoning_content
                    yield {
                        "type": "thinking",
                        "content": delta.reasoning_content,
                        "finished": False
                    }

        # 最终结果
        yield {
            "type": "done",
            "content": full_content,
            "thinking": thinking_content,
            "finished": True
        }

    except Exception as e:
        logger.error(f"流式API调用失败: {e}")
        yield {"type": "error", "content": str(e)}

@app.post("/api/v1/check/stream")
async def fact_check_stream(request: FactCheckRequest):
    """
    流式核查接口（返回Server-Sent Events）

    优势：实时显示AI思考过程，提升用户体验
    """
    from fastapi.responses import StreamingResponse

    logger.info(f"开始流式核查: {request.claim}")

    async def generate():
        try:
            # 步骤1: 搜索证据
            yield f"event: progress\ndata: {{\"stage\": \"searching\", \"message\": \"正在联网搜索证据...\"}}\n\n"
            search_results = await search_with_zhipu(request.claim)

            if not search_results:
                yield f"event: error\ndata: {{\"message\": \"未找到相关搜索结果\"}}\n\n"
                return

            yield f"event: progress\ndata: {{\"stage\": \"found\", \"message\": \"找到 {len(search_results)} 个相关证据，开始AI分析...\"}}\n\n"

            # 步骤2: 构造Prompt
            prompt = build_glm_prompt(request.claim, search_results)

            # 步骤3: 流式调用GLM-5
            request_params = {
                "model": config.GLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 6000,  # 流式模式可以稍大
                "stream": True,
            }

            if request.enable_thinking:
                logger.info("深度思考模式已启用（GLM-5原生支持）")

            response = zhipu_client.chat.completions.create(**request_params)

            full_content = ""
            thinking_content = ""

            # 流式输出
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta

                    # 思考过程
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        thinking_content += delta.reasoning_content
                        # 发送思考片段
                        yield f"event: thinking\ndata: {{\"content\": {json.dumps(delta.reasoning_content)}, \"finished\": false}}\n\n"

                    # 正式内容
                    elif hasattr(delta, 'content') and delta.content:
                        full_content += delta.content
                        # 发送内容片段
                        yield f"event: content\ndata: {{\"content\": {json.dumps(delta.content)}, \"finished\": false}}\n\n"

            # 完成
            yield f"event: progress\ndata: {{\"stage\": \"processing\", \"message\": \"正在生成证据链...\"}}\n\n"

            # 步骤4: 生成证据链
            if request.enable_evidence_chain:
                search_results_dicts = [
                    {
                        "title": result.name,
                        "url": result.url,
                        "summary": result.summary,
                        "date_published": result.date_published
                    }
                    for result in search_results
                ]

                evidence_chain = await evidence_chain_generator.generate_evidence_chain(
                    claim=request.claim,
                    search_results=search_results_dicts,
                    enable_link_validation=False,
                    top_k=10,
                    reasoning_text=full_content
                )

                # 返回完整结果
                result_data = {
                    "verdict": evidence_chain.verdict,
                    "confidence": evidence_chain.confidence,
                    "reasoning": full_content,
                    "evidence_chain": {
                        "supporting_evidence": evidence_chain.supporting_evidence,
                        "opposing_evidence": evidence_chain.opposing_evidence,
                        "neutral_evidence": evidence_chain.neutral_evidence,
                        "total_evidence": evidence_chain.total_evidence,
                        "ai_summary": evidence_chain.ai_summary
                    }
                }

                yield f"event: done\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"
            else:
                # 没有证据链，只返回基本结果
                result_data = {
                    "verdict": "信息不足，无法判断",
                    "reasoning": full_content
                }
                yield f"event: done\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"流式核查失败: {e}", exc_info=True)
            yield f"event: error\ndata: {{\"message\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/v1/check", response_model=FactCheckResponse)
async def fact_check(request: FactCheckRequest):
    """
    信息核查主接口（支持GLM-5深度思考模式）

    新功能：
    - 深度思考模式（enable_thinking）
    - 链接活性检测（enable_link_validation）
    - 一致性评分（enable_consistency_check）
    """
    start_time = time.time()

    try:
        logger.info(f"开始核查: {request.claim}")
        logger.info(f"配置 - 思考模式: {request.enable_thinking}, 链接验证: {request.enable_link_validation}, 一致性检查: {request.enable_consistency_check}")

        # 步骤1: 使用智谱AI联网搜索
        search_results = await search_with_zhipu(request.claim)

        # 步骤2: 如果没有有效结果，直接返回信息不足
        if not search_results:
            logger.warning("未找到有效搜索结果")
            return FactCheckResponse(
                verdict="信息不足，无法判断",
                evidence_quote="无",
                source_url="",
                search_keywords=request.claim,
                uncertainty_note="未找到权威信息源",
                reasoning="博查AI未返回相关搜索结果，无法进行信息核查",
                thinking_process=None,
                link_validation=None,
                consistency_score=None
            )

        # 步骤3: 链接活性检测（可选）
        link_validation_result = None
        if request.enable_link_validation:
            logger.info("开始链接活性检测...")
            urls = [result.url for result in search_results[:5]]  # 验证前5个链接
            validation_results = await link_validator.validate_multiple_links(urls, concurrent_limit=3)
            validation_report = link_validator.generate_validation_report(validation_results)
            link_validation_result = {
                "report": validation_report,
                "details": [
                    {
                        "url": r.url,
                        "accessible": r.is_accessible,
                        "status_code": r.status_code,
                        "response_time_ms": r.response_time_ms,
                        "error": r.error_message
                    }
                    for r in validation_results
                ]
            }
            logger.info(f"链接验证完成: {validation_report['accessible_links']}/{validation_report['total_links']} 个链接可访问")

        # 步骤4: 构造GLM推理Prompt
        prompt = build_glm_prompt(request.claim, search_results)

        # 步骤5: 调用GLM-5进行推理（支持深度思考模式）
        reasoning_result = await call_glm_api(
            prompt,
            enable_thinking=request.enable_thinking,
            stream=request.stream
        )

        # 步骤6: 一致性评分（可选）
        consistency_result = None
        if request.enable_consistency_check and reasoning_result.get("reasoning"):
            logger.info("开始一致性评分...")

            # 获取源网页内容（简化版：使用搜索结果的summary）
            source_content = " ".join([result.summary for result in search_results[:3]])

            # 计算一致性
            consistency_score = consistency_scorer.calculate_consistency(
                reasoning_result["reasoning"],
                source_content
            )
            consistency_report = consistency_scorer.generate_consistency_report(consistency_score)
            consistency_result = consistency_report
            logger.info(f"一致性评分完成: {consistency_score.overall_score}/100")

        # 步骤7: 证据链生成（可选）
        evidence_chain_result = None
        confidence_value = None

        if request.enable_evidence_chain:
            logger.info("开始生成证据链...")

            # 将搜索结果转换为字典格式
            search_results_dicts = [
                {
                    "title": result.name,
                    "url": result.url,
                    "summary": result.summary,
                    "date_published": result.date_published
                }
                for result in search_results
            ]

            # 生成证据链（传入推理文本用于提取证据立场）
            reasoning_text = reasoning_result.get("reasoning", "")
            evidence_chain = await evidence_chain_generator.generate_evidence_chain(
                claim=request.claim,
                search_results=search_results_dicts,
                enable_link_validation=False,  # 已在前面处理过
                top_k=10,
                reasoning_text=reasoning_text  # 传入推理文本用于提取证据立场
            )

            # 转换为字典格式
            evidence_chain_result = {
                "supporting_evidence": evidence_chain.supporting_evidence,
                "opposing_evidence": evidence_chain.opposing_evidence,
                "neutral_evidence": evidence_chain.neutral_evidence,
                "key_findings": evidence_chain.key_findings,
                "total_evidence": evidence_chain.total_evidence,
                "authoritative_sources": evidence_chain.authoritative_sources,
                "average_score": evidence_chain.average_score,
                "ai_summary": evidence_chain.ai_summary  # 添加AI归纳总结
            }

            confidence_value = evidence_chain.confidence
            logger.info(f"证据链生成完成: {evidence_chain.total_evidence} 个证据, 置信度: {confidence_value}%")

        # 步骤8: 返回结果
        elapsed_time = (time.time() - start_time) * 1000
        logger.info(f"核查完成，耗时: {elapsed_time:.1f}ms")

        # 如果启用了证据链，使用证据链的结论和置信度（更准确）
        if request.enable_evidence_chain and evidence_chain:
            final_verdict = evidence_chain.verdict
            final_confidence = evidence_chain.confidence
            logger.info(f"使用证据链结论: {final_verdict}, 置信度: {final_confidence}%")
        else:
            final_verdict = reasoning_result.get("verdict", "信息不足，无法判断")
            final_confidence = confidence_value

        return FactCheckResponse(
            verdict=final_verdict,
            evidence_quote=reasoning_result.get("evidence_quote", "无"),
            source_url=reasoning_result.get("source_url", ""),
            search_keywords=reasoning_result.get("search_keywords", request.claim),
            uncertainty_note=reasoning_result.get("uncertainty_note", "无"),
            reasoning=reasoning_result.get("reasoning", "推理过程未提供"),
            confidence=final_confidence,
            thinking_process=reasoning_result.get("thinking_process"),
            link_validation=link_validation_result,
            consistency_score=consistency_result,
            evidence_chain=evidence_chain_result
        )

    except Exception as e:
        logger.error(f"信息核查异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="信息核查服务异常")

@app.get("/")
async def root():
    """服务状态检查"""
    return {
        "service": "信息核查插件后端（GLM-5增强版）",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "智谱AI搜索",
            "GLM-5推理（支持深度思考模式）",
            "链接活性检测",
            "一致性评分",
            "证据链生成",
            "流式输出（实验性）"
        ],
        "endpoints": {
            "fact_check": "/api/v1/check",
            "evidence_chain": "/api/v1/evidence-chain",
            "health": "/health",
            "link_validate": "/api/v1/validate-links",
            "consistency_check": "/api/v1/check-consistency"
        }
    }


@app.post("/api/v1/validate-links")
async def validate_links(urls: List[str]):
    """
    链接活性检测独立API

    Args:
        urls: 待验证的URL列表

    Returns:
        Dict: 验证结果
    """
    try:
        results = await link_validator.validate_multiple_links(urls)
        report = link_validator.generate_validation_report(results)
        return {
            "report": report,
            "details": [
                {
                    "url": r.url,
                    "accessible": r.is_accessible,
                    "status_code": r.status_code,
                    "response_time_ms": r.response_time_ms,
                    "error": r.error_message
                }
                for r in results
            ]
        }
    except Exception as e:
        logger.error(f"链接验证异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/check-consistency")
async def check_consistency(ai_text: str, source_text: str):
    """
    一致性评分独立API

    Args:
        ai_text: AI生成的文本
        source_text: 源文本

    Returns:
        Dict: 一致性评分结果
    """
    try:
        score = consistency_scorer.calculate_consistency(ai_text, source_text)
        report = consistency_scorer.generate_consistency_report(score)
        return {
            "score": {
                "overall": score.overall_score,
                "semantic": score.semantic_similarity,
                "factual": score.factual_consistency,
                "completeness": score.completeness_score
            },
            "report": report
        }
    except Exception as e:
        logger.error(f"一致性评分异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/evidence-chain")
async def generate_evidence_chain(request: EvidenceChainRequest):
    """
    证据链生成API（为前端提供结构化证据链数据）

    功能：
    - 证据排序和分类（支持/反对/中性）
    - 证据高亮和标签
    - 统计信息和分析
    - 可选的链接验证

    Args:
        request: 证据链生成请求

    Returns:
        Dict: 结构化的证据链数据
    """
    try:
        logger.info(f"开始生成证据链: {request.claim}")
        logger.info(f"配置 - 链接验证: {request.enable_link_validation}, Top K: {request.top_k}")

        # 步骤1: 使用智谱AI联网搜索
        search_results = await search_with_zhipu(request.claim)

        # 步骤2: 如果没有有效结果，返回空证据链
        if not search_results:
            logger.warning("未找到有效搜索结果")
            return {
                "claim": request.claim,
                "verdict": "信息不足，无法判断",
                "confidence": 0.0,
                "supporting_evidence": [],
                "opposing_evidence": [],
                "neutral_evidence": [],
                "reasoning_summary": "未找到相关搜索结果",
                "key_findings": [],
                "uncertainty_note": "未找到权威信息源",
                "total_evidence": 0,
                "authoritative_sources": 0,
                "average_score": 0.0,
                "generated_at": None,
                "processing_time_ms": 0.0
            }

        # 步骤3: 将搜索结果转换为字典格式
        search_results_dicts = [
            {
                "title": result.name,
                "url": result.url,
                "summary": result.summary,
                "date_published": result.date_published
            }
            for result in search_results
        ]

        # 步骤4: 生成证据链
        evidence_chain = await evidence_chain_generator.generate_evidence_chain(
            claim=request.claim,
            search_results=search_results_dicts,
            enable_link_validation=request.enable_link_validation,
            top_k=request.top_k
        )

        # 步骤5: 转换为字典返回
        result = {
            "claim": evidence_chain.claim,
            "verdict": evidence_chain.verdict,
            "confidence": evidence_chain.confidence,
            "supporting_evidence": evidence_chain.supporting_evidence,
            "opposing_evidence": evidence_chain.opposing_evidence,
            "neutral_evidence": evidence_chain.neutral_evidence,
            "reasoning_summary": evidence_chain.reasoning_summary,
            "key_findings": evidence_chain.key_findings,
            "uncertainty_note": evidence_chain.uncertainty_note,
            "total_evidence": evidence_chain.total_evidence,
            "authoritative_sources": evidence_chain.authoritative_sources,
            "average_score": evidence_chain.average_score,
            "generated_at": evidence_chain.generated_at,
            "processing_time_ms": evidence_chain.processing_time_ms
        }

        logger.info(f"证据链生成完成: {evidence_chain.total_evidence} 个证据")
        return result

    except Exception as e:
        logger.error(f"证据链生成异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"证据链生成失败: {str(e)}")


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
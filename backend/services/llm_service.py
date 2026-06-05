"""
LLM API interaction: prompt building, API calls, response parsing.
"""
import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, List

from config import config, logger
from models import SearchResult


def sanitize_model_preamble(text: str) -> str:
    """Remove assistant-style opening chatter from model analysis output."""
    if not text:
        return text

    cleaned = text.replace('\r\n', '\n').replace('\r', '\n').lstrip()
    preamble_patterns = [
        r'^好的[，,]\s*作为[^。\n]{0,80}(?:助手|专家)[，,]\s*以下是[^。\n]{0,120}(?:分析|报告)[。\n]*\s*',
        r'^好的[，,]\s*以下是[^。\n]{0,120}(?:分析|报告)[。\n]*\s*',
        r'^作为[^。\n]{0,80}(?:助手|专家)[，,]\s*以下是[^。\n]{0,120}(?:分析|报告)[。\n]*\s*',
        r'^以下是[^。\n]{0,120}(?:可信度分析|分析报告)[。\n]*\s*',
    ]

    changed = True
    while changed:
        changed = False
        for pattern in preamble_patterns:
            next_cleaned = re.sub(pattern, '', cleaned, count=1, flags=re.IGNORECASE)
            if next_cleaned != cleaned:
                cleaned = next_cleaned.lstrip()
                changed = True
                break

    return cleaned


def extract_structured_info_from_reasoning(reasoning_text: str) -> Dict[str, Any]:
    """从LLM的自然语言分析中提取结构化信息"""
    reasoning_text = sanitize_model_preamble(reasoning_text)

    result = {
        "verdict": "详见下方证据链分析",
        "evidence_quote": "无",
        "source_url": "",
        "search_keywords": "",
        "uncertainty_note": "无",
        "reasoning": reasoning_text[:4000] + "...\n\n[内容过长，已截断。完整推理请参考证据分析]" if len(reasoning_text) > 4000 else reasoning_text
    }

    if not reasoning_text:
        return result

    try:
        # 提取evidence_quote（关键证据）
        evidence_section = re.search(
            r'###\s*2[\.、]\s*.*?关键证据.*?\n+(.+?)(?=###\s*\d+|不确定性|$)',
            reasoning_text,
            re.IGNORECASE | re.DOTALL
        )

        if evidence_section:
            evidence_text = evidence_section.group(1).strip()
            evidence_text = re.sub(r'\*\*', '', evidence_text)
            evidence_text = re.sub(r'["""]', '"', evidence_text)
            evidence_text = re.sub(r'\n+', ' ', evidence_text)
            evidence_text = evidence_text.strip()

            if len(evidence_text) > 10:
                result["evidence_quote"] = evidence_text[:200]
        else:
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

        # 提取source_url（证据来源）
        source_section = re.search(
            r'###\s*3[\.、]\s*.*?证据来源.*?\n+(.+?)(?=###\s*\d+|分析过程|$)',
            reasoning_text,
            re.IGNORECASE | re.DOTALL
        )

        if source_section:
            source_text = source_section.group(1).strip()
            url_match = re.search(r'(https?://[^\s\)]+)', source_text)
            if url_match:
                result["source_url"] = url_match.group(1)
        else:
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

        # 提取uncertainty_note（不确定性）
        uncertainty_section = re.search(
            r'###\s*5[\.、]\s*.*?不确定.*?\n+(.+?)(?=###\s*\d+|$)',
            reasoning_text,
            re.IGNORECASE | re.DOTALL
        )

        if uncertainty_section:
            uncertainty_text = uncertainty_section.group(1).strip()
            uncertainty_text = re.sub(r'\*\*', '', uncertainty_text)
            uncertainty_text = re.sub(r'\n+', ' ', uncertainty_text)
            uncertainty_text = uncertainty_text.strip()

            if len(uncertainty_text) > 5:
                result["uncertainty_note"] = uncertainty_text[:300]
        else:
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

        # 智能分析不确定性指示词
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
    """格式化证据列表"""
    evidence_text = ""
    for item in evidence:
        source = item.source or '媒体报道'
        evidence_text += f"""- [{item.name}]({item.url})
  来源：{source}
  摘要：{item.summary}
  发布时间：{item.date_published}
"""
    return evidence_text


def build_llm_prompt(claim: str, evidence_list: List[SearchResult]) -> str:
    """构造LLM推理Prompt（v0.5.2 精简优化版）"""

    evidence_text = format_evidence_list(evidence_list)
    evidence_count = len(evidence_list)
    current_date = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""你是专业信息核查助手，分析以下说法的可信度。

【当前日期】{current_date}

【待核查说法】
{claim}

【实时证据】
本次仅分析以下 {evidence_count} 条核心证据。输出中涉及证据整体关系时，必须写“所有{evidence_count}条核心证据”，不得写“所有证据”或其他数量。

{evidence_text}

【输出要求】

### 1. 证据立场分析（严格遵守以下格式，每条证据单独一行）
对每条证据，必须使用以下精确格式（注意**立场**后面的冒号和加粗标记）：

**证据 [序号] [标题](URL)** - 来源：**[发布媒体/机构名称]** - **立场**：**支持** - 分析：[该证据如何支持/反对/中立]
**证据 [序号] [标题](URL)** - 来源：**[发布媒体/机构名称]** - **立场**：**反对** - 分析：[原因]
**证据 [序号] [标题](URL)** - 来源：**[发布媒体/机构名称]** - **立场**：**中性** - 分析：[原因]

立场判断规则：
- 支持：证据内容直接或间接证实该说法的核心内容
- 反对：证据内容直接反驳或否定该说法的核心内容
- 中性：证据提供背景信息，无法直接判断支持或反对

来源直接使用证据列表中已标注的"来源"字段，无需自行推测。

### 2. 关键引用
使用 [标题](URL) 格式引用关键内容。

### 3. 证据关系分析
说明证据间的印证、矛盾或对立关系。需要区分“多个网站发布”与“多个独立信源”：如果多条证据标题、措辞、事实细节高度相似，可能是同一原始报道的转载或改写，不能直接视为多方交叉核实。

### 4. 不确定性与局限
指出证据数量、时效性、来源局限、转载/洗稿导致的表面多源问题等。

### 5. 归纳总结（必须包含）

先输出开头摘要：2-3个完整句子，80-150字，写成连续段落，不要用项目符号，也不要输出“开头段落”字样。
直接给出核查结论和核心事实判断，不要复述证据数量和立场统计。
必须涵盖：
1. 明确结论：该说法是否属实？是否存在夸大、误导或不实？
2. 核心事实：证据揭示了什么关键真相？
3. 重要限定：是否有需要特别说明的上下文或前提？

示例（仅供格式参考）：
"关于"A股万亿科技巨头诞生"这一说法，经核查存在夸大。该公司股价确实创新高达到1.2万亿市值，但"首个万亿科技巨头"的表述不准确，此前已有其他科技公司达到万亿规模。"

然后输出展开分析，使用项目符号，但不要输出“展开分析”字样：
- **核心事实提取**：从证据中提炼3-5个关键信息点（不要复述证据数量）
- **深度洞察**：信息背后的趋势、因果关系或深层含义；不同证据揭示的不同侧面
- **与说法的精确对比**：说法中哪些表述准确？哪些存在偏差？最关键的反驳点是什么？

【约束】
- ✅ 第1节必须逐一分析所有证据，严格按照指定格式，立场只能从"支持""反对""中性"中三选一
- ✅ 第1-4节专注分析证据本身，不给出最终结论
- ✅ 第5节开头段落必须2-3句、80-150字，不要超过3句
- ✅ 第5节开头段落必须是自然语言摘要，不要出现"核心事实提取""洞察分析"等分节标题
- ✅ 展开分析中的每个项目符号必须单独占一行，禁止把两个项目符号写在同一行
- ✅ 直接从“### 1. 证据立场分析”开始输出，不要输出“好的”“作为专业信息核查助手”“以下是”等寒暄或角色自述
- ⚠️ 格式严格性说明：系统通过正则匹配 `**立场**：**支持/反对/中性**` 提取立场，格式偏差会导致立场提取失败
- ⚠️ 禁止在输出中纠结来源名称，不确定就填"媒体报道"，直接给出结论，不要展示推理过程

开始分析："""

    return prompt


def build_assistant_llm_prompt(claim: str, evidence_list: List[SearchResult]) -> str:
    """构造普通助手式回复 Prompt，用于实验 B 组呈现。"""

    evidence_text = format_evidence_list(evidence_list)
    evidence_count = len(evidence_list)
    current_date = datetime.now().strftime("%Y年%m月%d日")

    return f"""今天是{current_date}。以下是一条用户信息及相关检索材料，请判断其可信度。

用户信息：
{claim}

相关材料（{evidence_count}条）：
{evidence_text}

请用自然对话语气直接回复用户，不要使用任何Markdown格式标记。"""

async def call_llm_api(
    prompt: str,
    zhipu_client,
    enable_thinking: bool = True,
    stream: bool = False
) -> Dict[str, Any]:
    """调用LLM API进行推理"""

    if not zhipu_client:
        return {
            "verdict": "信息不足，无法判断",
            "evidence_quote": "无",
            "source_url": "",
            "search_keywords": "",
            "uncertainty_note": "模型初始化失败，请稍后重试",
            "reasoning": "LLM客户端初始化失败",
            "thinking_process": None
        }

    try:
        logger.info(f"调用LLM进行推理（思考模式: {enable_thinking}, 流式: {stream}）...")

        request_params = {
            "model": config.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 8000,
            "stream": stream,
        }

        if enable_thinking:
            logger.info("深度思考模式已启用")

        response = await zhipu_client.chat.completions.create(**request_params)

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

        result_text = sanitize_model_preamble(result_text)
        logger.info(f"LLM原始响应长度: {len(result_text) if result_text else 0}")

        if hasattr(response.choices[0], 'finish_reason'):
            logger.info(f"LLM完成原因: {response.choices[0].finish_reason}")

        # 尝试解析JSON
        try:
            result = json.loads(result_text)
            logger.info("LLM响应解析成功")
            if thinking_process:
                result["thinking_process"] = thinking_process
            return result
        except json.JSONDecodeError:
            json_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', result_text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    logger.info("通过正则提取JSON成功")
                    return result
                except json.JSONDecodeError:
                    pass

            # 自然语言提取
            logger.info("JSON解析失败，尝试从自然语言推理中提取结构化信息")
            structured_result = extract_structured_info_from_reasoning(result_text)
            if thinking_process:
                structured_result["thinking_process"] = thinking_process
            return structured_result

    except Exception as e:
        logger.error(f"LLM API调用失败: {e}")
        return {
            "verdict": "信息不足，无法判断",
            "evidence_quote": "无",
            "source_url": "",
            "search_keywords": "",
            "uncertainty_note": "模型调用失败，请稍后重试",
            "reasoning": f"API调用异常: {str(e)}",
            "thinking_process": None
        }

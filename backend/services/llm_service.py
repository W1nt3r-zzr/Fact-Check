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
    """构造LLM推理Prompt (v0.6 强制完整输出版)"""

    evidence_text = format_evidence_list(evidence_list)
    evidence_count = len(evidence_list)
    current_date = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""⚠️ 【最高优先级指令 — 先读这一条】你必须输出完整的5节结构化分析，总字数至少2500字（约1700中文字符）。禁止输出简短摘要代替完整分析。即使你认为问题简单、证据清晰，也必须逐条分析每条证据、完整撰写所有5节。输出不完整将被系统拒绝并要求重新生成。

你是专业信息核查助手。分析以下说法的可信度，输出完整结构化报告。

【当前日期】{current_date}

【待核查说法】
{claim}

【实时证据】
本次仅分析以下 {evidence_count} 条核心证据。输出中涉及证据整体关系时，必须写"所有{evidence_count}条核心证据"，不得写"所有证据"或其他数量。

{evidence_text}

【输出要求 — 必须完整输出以下所有 5 节，缺一不可】

### 1. 证据立场分析（必须逐条分析全部 {evidence_count} 条，不得跳过或合并）
格式要求——每条证据一行，精确使用以下格式：
**证据 [序号] [标题](URL)** - 来源：**[发布媒体/机构名称]** - **立场**：**支持** - 分析：[说明该证据如何支持/反对看法，至少1个完整句子]
**证据 [序号] [标题](URL)** - 来源：**[发布媒体/机构名称]** - **立场**：**反对** - 分析：[说明该证据如何反对看法，至少1个完整句子]
**证据 [序号] [标题](URL)** - 来源：**[发布媒体/机构名称]** - **立场**：**中性** - 分析：[说明为什么是中性，至少1个完整句子]

立场判断规则：
- 支持：证据内容直接或间接证实该说法的核心内容
- 反对：证据内容直接反驳或否定该说法
- 中性：证据提供背景信息，无法直接判断支持或反对
- 来源直接使用证据列表中已标注的"来源"字段，无需自行推测。
- ⚠️ 每条证据的分析部分至少20字，不能只写"支持该说法"就结束。

### 2. 关键引用（至少3-5条实质性引用）
从证据中提取关键原文表述，使用 [标题](URL) 格式标注来源。每条引用注明其支撑的论点。不能只列标题不写引用内容。

### 3. 证据关系分析（至少150字）
- 证据间是否存在相互印证、矛盾或补充关系？
- 区分"多个网站发布"与"多个独立信源"：标题/措辞高度相似的可能是同一报道的转载，不能当作多方交叉核实。
- 是否存在关键信息缺口？

### 4. 不确定性与局限（至少100字）
- 证据数量是否充足？时效性如何？
- 信源存在转载/洗稿导致的表面多源问题吗？
- 是否存在无法验证的争议点？
- 是否有需要更多信息才能确认的方面？

### 5. 归纳总结

先输出开头摘要（2-3个完整句子，80-150字），直接给出核查结论和核心事实判断。示例格式：
"关于[主题]，经核查[结论概述]。核心事实是[关键发现]，但需注意[重要限定]。综上，该说法**[结论]**。"

然后输出展开分析（每个项目符号单独一行，至少3组）：
- **核心事实提取**：从证据中提炼3-5个关键信息点（禁止复述证据数量）
- **深度洞察**：信息背后的趋势、因果关系或深层含义；不同证据揭示的不同侧面
- **与说法的精确对比**：说法中哪些表述准确？哪些存在偏差？最关键的反驳点是什么？

【硬性约束 — 违反任何一条都将导致输出被拒绝】
1. 必须从"### 1. 证据立场分析"开始，不要任何寒暄或角色自述。
2. 第1节必须逐条分析全部 {evidence_count} 条证据，不允许跳过、合并或笼统概括。
3. 第1-4节只分析证据，不给出最终结论。结论只在第5节给出。
4. 总输出不少于2500字（约1700中文字符）。按 {evidence_count} 条证据×每条至少60字 + 第2-4节各至少100字 + 第5节至少300字计算，最低要求很容易达到。
5. 第5节开头段落末尾必须用加粗给出最终结论，四选一：
   - 综上，该说法**属实**。
   - 综上，该说法**不实**。
   - 综上，该说法**部分属实，存在争议**。
   - 综上，该说法**部分不实，存在争议**。
6. 禁止输出"新版实验材料核查摘要"、简短总结或任何非结构化内容。
7. 立场格式必须是 `**立场**：**支持/反对/中性**`，系统用正则提取，格式偏差会导致失败。
8. 展开分析中每个 `- **xxx**：` 项目符号独占一行。

开始完整分析："""

    return prompt


def build_assistant_llm_prompt(claim: str, evidence_list: List[SearchResult]) -> str:
    """构造普通助手式回复 Prompt，用于实验 B 组呈现。"""

    evidence_text = format_evidence_list(evidence_list)
    evidence_count = len(evidence_list)
    current_date = datetime.now().strftime("%Y年%m月%d日")

    return f"""今天是{current_date}。请对以下信息进行可信度核查。

【待核查信息】
{claim}

【检索材料（{evidence_count}条）】
{evidence_text}

【回复要求】
请用客观、中立的第三方核查语气撰写回复，直接给出分析结论，不要使用Markdown格式标记。

严格禁止以下表述方式：
- 禁止出现"你提供的""从你提供的XX来看""你提到的""根据你给出的"等指向用户的话语
- 禁止出现"作为AI助手""作为信息核查助手"等角色自述
- 禁止出现"好的""收到""明白了"等对话开场白
- 禁止出现"希望对你有所帮助""如有其他问题欢迎继续提问"等客服式结束语

请直接开始回复："""

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

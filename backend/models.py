"""
Pydantic request/response models.
"""
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field


class FactCheckRequest(BaseModel):
    claim: str = Field(..., description="待核查的文本内容", min_length=1, max_length=500)
    enable_thinking: bool = Field(True, description="是否启用深度思考模式")
    stream: bool = Field(False, description="是否启用流式输出")
    enable_link_validation: bool = Field(False, description="是否启用链接活性检测")
    enable_consistency_check: bool = Field(False, description="是否启用一致性评分")
    enable_evidence_chain: bool = Field(False, description="是否启用证据链生成")
    response_mode: Literal["structured", "assistant"] = Field(
        "structured",
        description="结果呈现模式：structured 用于结构化插件，assistant 用于普通助手式回复"
    )
    news_id: Optional[int] = Field(None, description="新闻编号（用于预计算缓存匹配）")


class FactCheckResponse(BaseModel):
    verdict: str = Field(..., description="核查结论：属实 / 不实 / 信息不足，无法判断")
    evidence_quote: str = Field(..., description="证据引用原文")
    source_url: str = Field(..., description="证据来源URL")
    search_keywords: str = Field(..., description="搜索关键词")
    uncertainty_note: str = Field(..., description="不确定性说明")
    reasoning: str = Field(..., description="推理过程说明")
    assistant_reply: Optional[str] = Field(None, description="普通助手式回复（如果启用）")
    thinking_process: Optional[str] = Field(None, description="深度思考过程（如果启用）")
    link_validation: Optional[Dict[str, Any]] = Field(None, description="链接活性检测结果")
    consistency_score: Optional[Dict[str, Any]] = Field(None, description="一致性评分结果")
    evidence_chain: Optional[Dict[str, Any]] = Field(None, description="证据链数据（如果启用）")


class EvidenceChainRequest(BaseModel):
    claim: str = Field(..., description="待核查的说法", min_length=1, max_length=500)
    enable_link_validation: bool = Field(False, description="是否验证链接活性")
    top_k: int = Field(5, description="返回Top K个证据", ge=1, le=20)


class SearchResult(BaseModel):
    name: str
    url: str
    summary: str
    date_published: str
    source: str = ""  # 媒体来源名称（从URL域名提取）

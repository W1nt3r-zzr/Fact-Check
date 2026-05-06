"""
Evidence chain generation route.
"""
import logging

from fastapi import APIRouter, HTTPException

from config import logger
from models import EvidenceChainRequest
from services.search import search_with_zhipu

router = APIRouter()

_evidence_chain_generator = None


def init_dependencies(evidence_chain_generator):
    global _evidence_chain_generator
    _evidence_chain_generator = evidence_chain_generator


@router.post("/api/v1/evidence-chain")
async def generate_evidence_chain(request: EvidenceChainRequest):
    """证据链生成API"""
    try:
        logger.info(f"开始生成证据链: {request.claim}")
        logger.info(f"配置 - 链接验证: {request.enable_link_validation}, Top K: {request.top_k}")

        search_results = await search_with_zhipu(request.claim)

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

        search_results_dicts = [
            {
                "title": result.name,
                "url": result.url,
                "summary": result.summary,
                "date_published": result.date_published
            }
            for result in search_results
        ]

        evidence_chain = await _evidence_chain_generator.generate_evidence_chain(
            claim=request.claim,
            search_results=search_results_dicts,
            enable_link_validation=request.enable_link_validation,
            top_k=request.top_k,
            total_search_results=len(search_results)
        )

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

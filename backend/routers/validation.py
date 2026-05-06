"""
Link validation and consistency scoring routes.
"""
import logging
from typing import List

from fastapi import APIRouter, HTTPException

from config import logger

router = APIRouter()

_link_validator = None
_consistency_scorer = None


def init_dependencies(link_validator, consistency_scorer):
    global _link_validator, _consistency_scorer
    _link_validator = link_validator
    _consistency_scorer = consistency_scorer


@router.post("/api/v1/validate-links")
async def validate_links(urls: List[str]):
    """链接活性检测独立API"""
    try:
        results = await _link_validator.validate_multiple_links(urls)
        report = _link_validator.generate_validation_report(results)
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


@router.post("/api/v1/check-consistency")
async def check_consistency(ai_text: str, source_text: str):
    """一致性评分独立API"""
    try:
        score = _consistency_scorer.calculate_consistency(ai_text, source_text)
        report = _consistency_scorer.generate_consistency_report(score)
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

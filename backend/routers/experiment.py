"""
Experiment data collection routes.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter()


class ExperimentDecisionRequest(BaseModel):
    participant_id: str = Field(min_length=1)
    trial: int = Field(ge=1)
    news_id: int = Field(ge=1)
    condition: Literal["plugin_structured", "plugin_assistant"]
    decision: Literal["accept", "reject"]
    timestamp: str


def _decision_log_path() -> Path:
    configured = os.getenv("EXPERIMENT_DECISION_LOG")
    if configured:
      return Path(configured)
    return Path(__file__).resolve().parents[1] / "data" / "experiment_decisions.jsonl"


@router.post("/api/v1/experiment/decision")
async def record_experiment_decision(payload: ExperimentDecisionRequest):
    path = _decision_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    record = payload.model_dump()
    record["received_at"] = datetime.now(timezone.utc).isoformat()

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {"ok": True}

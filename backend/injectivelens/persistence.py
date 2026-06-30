from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "injectivelens_state.json"


class JsonStateStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("INJECTIVELENS_STATE_FILE") or DEFAULT_STATE_PATH)

    @classmethod
    def from_env(cls) -> "JsonStateStore":
        return cls()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"latestAssessment": None, "proofRecords": {}, "assessmentHistory": []}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"latestAssessment": None, "proofRecords": {}, "assessmentHistory": []}
        return {
            "latestAssessment": data.get("latestAssessment"),
            "proofRecords": data.get("proofRecords") or {},
            "assessmentHistory": data.get("assessmentHistory") or [],
        }

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "latestAssessment": state.get("latestAssessment"),
                "proofRecords": state.get("proofRecords") or {},
                "assessmentHistory": state.get("assessmentHistory") or [],
            },
            indent=2,
            sort_keys=True,
        )
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(payload)
        tmp_path.replace(self.path)

    def get_latest_assessment(self) -> dict[str, Any] | None:
        latest = self.load().get("latestAssessment")
        return latest if isinstance(latest, dict) else None

    def save_latest_assessment(self, assessment: dict[str, Any]) -> None:
        state = self.load()
        state["latestAssessment"] = assessment
        self.save(state)

    def get_proof_records(self) -> dict[str, dict[str, Any]]:
        records = self.load().get("proofRecords") or {}
        return {str(key): value for key, value in records.items() if isinstance(value, dict)}

    def get_assessment_history(self) -> list[dict[str, Any]]:
        history = self.load().get("assessmentHistory") or []
        return [item for item in history if isinstance(item, dict)]

    def save_assessment_history_record(self, assessment: dict[str, Any]) -> None:
        assessment_id = str(assessment.get("assessmentId") or "")
        if not assessment_id:
            return
        state = self.load()
        history = [item for item in state.get("assessmentHistory") or [] if isinstance(item, dict)]
        history = [item for item in history if item.get("assessmentId") != assessment_id]
        history.insert(0, assessment)
        state["assessmentHistory"] = history[:25]
        self.save(state)

    def save_proof_record(self, proof: dict[str, Any]) -> None:
        assessment_hash = str(proof.get("assessmentHash") or proof.get("recordedAssessmentHash") or "")
        if not assessment_hash:
            return
        state = self.load()
        records = state.get("proofRecords") or {}
        records[assessment_hash] = proof
        state["proofRecords"] = records
        self.save(state)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return


STATE_STORE = JsonStateStore.from_env()


def reset_state_store(path: str | Path | None = None) -> JsonStateStore:
    global STATE_STORE
    STATE_STORE = JsonStateStore(path)
    return STATE_STORE

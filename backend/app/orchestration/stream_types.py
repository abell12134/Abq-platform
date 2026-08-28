from __future__ import annotations

from dataclasses import dataclass

from app.models.analysis import AnalysisStep


@dataclass(frozen=True)
class PhaseMarker:
    phase: str
    label: str


StreamItem = AnalysisStep | PhaseMarker

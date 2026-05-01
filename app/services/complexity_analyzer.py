"""
Service layer: rule-based STL complexity detection.

Uses a four-metric voting heuristic to classify model complexity into:
  simple | mid_complex | complex

Each metric independently casts a vote (0 = simple, 1 = mid, 2 = complex).
The sum of votes determines the final label. This multi-signal approach is
more robust than any single threshold and produces a clear audit trail for
future ML training.

Metrics & calibration (verified against 9 reference meshes):
  surface_to_volume_ratio  SVR >= 8   -> vote rises (scale-robust: SVR of a
                                         10mm cube = 6, sphere-like >> 8)
  volume_efficiency        eff <= 0.6 -> vote rises (sphere=0.52, torus=0.14)
  triangle_count           >= 5k/20k  -> vote rises
  triangle_density         tris/bb_cc >= 50/500 -> vote rises (scale-normalised)

Thresholds:
  total == 0       -> simple
  1 <= total <= 3  -> mid_complex
  total >= 4       -> complex
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import trimesh

from app.core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Complexity(str, Enum):
    SIMPLE      = "simple"
    MID_COMPLEX = "mid_complex"
    COMPLEX     = "complex"


# ---------------------------------------------------------------------------
# Calibrated thresholds
# ---------------------------------------------------------------------------

# Surface-to-volume ratio  (cm2 / cc) — raised to 8.0 for scale-robustness
# A 10x10x10mm solid cube has SVR ≈ 6.0; anything above 8.0 has real surface detail.
_SVR_MID_THRESHOLD:     float = 8.0
_SVR_COMPLEX_THRESHOLD: float = 18.0

# Volume efficiency: fraction of bounding box occupied by the part
_EFF_SIMPLE_MIN: float = 0.6   # >= 0.6  -> fills box well (box, cylinder)
_EFF_MID_MIN:    float = 0.3   # 0.3–0.6 -> partial fill  (sphere ≈ 0.52)

# Absolute triangle count
_TRI_SIMPLE_MAX: int = 5_000
_TRI_MID_MAX:    int = 20_000

# Triangle density: triangles per cm3 of bounding box (scale-normalised)
_DEN_SIMPLE_MAX: float = 50.0
_DEN_MID_MAX:    float = 500.0

# Edge-case guard: micro-part with significant detail -> always complex
_TINY_VOLUME_CC: float = 1.0
_TINY_TRI_MIN:   int   = 500


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComplexityMetrics:
    """Raw computed metrics — logged as a structured record for ML training."""
    surface_to_volume_ratio: float
    bounding_box_volume_cc:  float
    volume_efficiency:       float
    triangle_count:          int
    triangle_density:        float   # tris / bounding_box_volume_cc


@dataclass(frozen=True, slots=True)
class ComplexityResult:
    complexity: Complexity
    metrics:    ComplexityMetrics
    votes:      dict    # {"svr": int, "efficiency": int, "triangles": int, "density": int}
    reason:     str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_metrics(
    mesh:             trimesh.Trimesh,
    volume_cc:        float,
    surface_area_cm2: float,
) -> ComplexityMetrics:
    dx, dy, dz = [float(v) for v in mesh.extents]
    bb_vol_cc  = (dx * dy * dz) / 1_000.0

    svr         = surface_area_cm2 / volume_cc   if volume_cc  > 0 else 999.0
    vol_eff     = volume_cc        / bb_vol_cc   if bb_vol_cc  > 0 else 0.0
    tris        = int(len(mesh.faces))
    tri_density = tris             / bb_vol_cc   if bb_vol_cc  > 0 else 0.0

    return ComplexityMetrics(
        surface_to_volume_ratio=round(svr,         4),
        bounding_box_volume_cc= round(bb_vol_cc,   4),
        volume_efficiency=      round(vol_eff,     4),
        triangle_count=         tris,
        triangle_density=       round(tri_density, 4),
    )


def _vote_svr(svr: float) -> int:
    if svr < _SVR_MID_THRESHOLD:     return 0
    if svr < _SVR_COMPLEX_THRESHOLD: return 1
    return 2


def _vote_efficiency(eff: float) -> int:
    if eff > _EFF_SIMPLE_MIN: return 0
    if eff > _EFF_MID_MIN:    return 1
    return 2


def _vote_triangles(tris: int) -> int:
    if tris < _TRI_SIMPLE_MAX: return 0
    if tris < _TRI_MID_MAX:    return 1
    return 2


def _vote_density(density: float) -> int:
    if density < _DEN_SIMPLE_MAX: return 0
    if density < _DEN_MID_MAX:    return 1
    return 2


def _label_from_total(total: int) -> tuple[Complexity, str]:
    if total == 0:
        return (
            Complexity.SIMPLE,
            "All metrics indicate simple geometry: solid fill, low surface detail, low triangle count.",
        )
    if total <= 3:
        return (
            Complexity.MID_COMPLEX,
            "Mixed signals: moderate curvature, partial bounding-box fill, or elevated triangle count.",
        )
    return (
        Complexity.COMPLEX,
        "Multiple complexity signals: high surface-to-volume ratio, low fill efficiency, or very high triangle density.",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyse_complexity(
    mesh:             trimesh.Trimesh,
    volume_cc:        float,
    surface_area_cm2: float,
) -> ComplexityResult:
    """
    Classify STL print complexity using a four-metric voting heuristic.

    Args:
        mesh:             Raw trimesh object (from stl_processor).
        volume_cc:        Part volume in cm3.
        surface_area_cm2: Surface area in cm2.

    Returns:
        ComplexityResult with Complexity label, raw metrics, per-metric
        votes (0/1/2), and a human-readable reason. All fields are logged
        in a structured format suitable for ML training data collection.
    """
    metrics = _compute_metrics(mesh, volume_cc, surface_area_cm2)

    # Edge case: micro-part + meaningful surface detail -> always complex
    if volume_cc < _TINY_VOLUME_CC and metrics.triangle_count >= _TINY_TRI_MIN:
        logger.info(
            "Complexity | EDGE_CASE=tiny_vol_high_detail "
            "result=complex vol=%.4f tris=%d "
            "SVR=%.4f eff=%.4f bb_vol=%.4f td=%.2f",
            volume_cc, metrics.triangle_count,
            metrics.surface_to_volume_ratio,
            metrics.volume_efficiency,
            metrics.bounding_box_volume_cc,
            metrics.triangle_density,
        )
        return ComplexityResult(
            complexity=Complexity.COMPLEX,
            metrics=metrics,
            votes={"svr": -1, "efficiency": -1, "triangles": -1, "density": -1},
            reason=(
                f"Edge case: volume {volume_cc:.4f} cc is below the micro-part threshold "
                f"({_TINY_VOLUME_CC} cc) with {metrics.triangle_count} triangles — "
                f"classified as complex regardless of other metrics."
            ),
        )

    # Normal voting path
    v_svr = _vote_svr(metrics.surface_to_volume_ratio)
    v_eff = _vote_efficiency(metrics.volume_efficiency)
    v_tri = _vote_triangles(metrics.triangle_count)
    v_den = _vote_density(metrics.triangle_density)
    total = v_svr + v_eff + v_tri + v_den

    label, reason = _label_from_total(total)

    # Structured ML training log — one line, machine-parseable
    logger.info(
        "Complexity | result=%s vote_total=%d "
        "votes={svr:%d eff:%d tri:%d den:%d} "
        "SVR=%.4f eff=%.4f tris=%d td=%.2f vol=%.4f bb_vol=%.4f",
        label.value, total,
        v_svr, v_eff, v_tri, v_den,
        metrics.surface_to_volume_ratio,
        metrics.volume_efficiency,
        metrics.triangle_count,
        metrics.triangle_density,
        volume_cc,
        metrics.bounding_box_volume_cc,
    )

    return ComplexityResult(
        complexity=label,
        metrics=metrics,
        votes={"svr": v_svr, "efficiency": v_eff, "triangles": v_tri, "density": v_den},
        reason=reason,
    )

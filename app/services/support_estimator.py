"""
Service layer: slicer-free support material volume estimation.

Algorithm
---------
FDM printers need support structures under faces that point more than 45 degrees
downward from the vertical (build plate normal = +Z).  We detect these faces
using the dot product between each face normal and the +Z axis:

    Z-component of normal < -cos(45deg)  =  < -0.7071

This is fully vectorised with NumPy — no Python-level face loop — so it
handles meshes with hundreds of thousands of triangles in milliseconds.

Estimation formula
------------------
    support_height_factor = z_dimension_mm / 20   (average column height proxy)
    support_volume_cc     = overhang_area_cm2 * support_height_factor

Clamped to 50% of part volume to prevent unrealistic estimates on extreme geometry.

The 45-degree self-supporting angle is the industry-standard FDM heuristic,
consistent with Cura, PrusaSlicer, and Simplify3D defaults.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh

from app.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OVERHANG_ANGLE_DEG: float = 45.0
# Any face whose normal Z-component is below this threshold needs support.
# cos(180 - 45) = -cos(45) = -0.7071
_Z_THRESHOLD: float = -math.cos(math.radians(_OVERHANG_ANGLE_DEG))   # -0.7071

_MM2_TO_CM2: float = 1.0 / 100.0   # mm2 -> cm2
_HEIGHT_DIVISOR: float = 20.0       # per specification
_MAX_SUPPORT_RATIO: float = 0.50    # clamp: support <= 50% of part volume


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupportEstimate:
    """Estimated support material requirements for the default print orientation."""

    overhang_face_count:   int    # faces classified as overhangs
    overhang_area_mm2:     float  # raw overhang area in mm2
    overhang_area_cm2:     float  # same, in cm2
    support_height_factor: float  # z_mm / 20
    support_volume_cc:     float  # estimated support volume after clamping
    support_ratio_percent: float  # (support_volume_cc / model_volume_cc) * 100
    has_overhangs:         bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def estimate_support(
    mesh:      trimesh.Trimesh,
    z_dim_mm:  float,
    volume_cc: float,
) -> SupportEstimate:
    """
    Estimate support material volume for an STL mesh.

    Fully vectorised with NumPy — no Python-level face loop.

    Args:
        mesh:      Watertight trimesh.Trimesh from stl_processor.
        z_dim_mm:  Bounding box Z extent in mm (build height).
        volume_cc: Part volume in cm3.

    Returns:
        SupportEstimate dataclass.
    """
    # ── 1. Vectorised overhang detection ─────────────────────────────────────
    # mesh.face_normals : (N, 3) unit vectors, pre-computed by trimesh
    # mesh.area_faces   : (N,)   per-face area in mm2
    z_components: np.ndarray  = mesh.face_normals[:, 2]         # (N,)
    overhang_mask: np.ndarray = z_components < _Z_THRESHOLD     # (N,) bool

    overhang_face_count = int(overhang_mask.sum())
    overhang_area_mm2   = float(mesh.area_faces[overhang_mask].sum())
    overhang_area_cm2   = overhang_area_mm2 * _MM2_TO_CM2

    # ── 2. Zero support when no overhangs detected ───────────────────────────
    if overhang_face_count == 0 or overhang_area_mm2 == 0.0:
        logger.info(
            "SupportEstimate | has_overhangs=False vol=%.4f cc z=%.2f mm",
            volume_cc, z_dim_mm,
        )
        return SupportEstimate(
            overhang_face_count=0,
            overhang_area_mm2=0.0,
            overhang_area_cm2=0.0,
            support_height_factor=0.0,
            support_volume_cc=0.0,
            support_ratio_percent=0.0,
            has_overhangs=False,
        )

    # ── 3. Apply formula ──────────────────────────────────────────────────────
    support_height_factor = z_dim_mm / _HEIGHT_DIVISOR
    raw_support_cc        = overhang_area_cm2 * support_height_factor

    # ── 4. Clamp to 50% of model volume ──────────────────────────────────────
    max_support_cc    = volume_cc * _MAX_SUPPORT_RATIO
    support_volume_cc = min(raw_support_cc, max_support_cc)
    was_clamped       = raw_support_cc > max_support_cc

    support_ratio_pct = (support_volume_cc / volume_cc * 100) if volume_cc > 0 else 0.0

    # ── 5. Structured ML training log ────────────────────────────────────────
    logger.info(
        "SupportEstimate | has_overhangs=True "
        "overhang_faces=%d overhang_area_mm2=%.4f overhang_area_cm2=%.4f "
        "height_factor=%.4f raw_support_cc=%.4f clamped=%s "
        "support_volume_cc=%.4f support_ratio=%.2f%% "
        "model_vol=%.4f z_mm=%.2f",
        overhang_face_count, overhang_area_mm2, overhang_area_cm2,
        support_height_factor, raw_support_cc, was_clamped,
        support_volume_cc, support_ratio_pct,
        volume_cc, z_dim_mm,
    )

    return SupportEstimate(
        overhang_face_count=overhang_face_count,
        overhang_area_mm2=round(overhang_area_mm2, 4),
        overhang_area_cm2=round(overhang_area_cm2, 4),
        support_height_factor=round(support_height_factor, 4),
        support_volume_cc=round(support_volume_cc, 4),
        support_ratio_percent=round(support_ratio_pct, 2),
        has_overhangs=True,
    )

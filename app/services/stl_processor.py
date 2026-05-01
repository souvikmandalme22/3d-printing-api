"""Service layer: STL geometry extraction using trimesh."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import trimesh
import trimesh.base

from app.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Unit-conversion constants
# ---------------------------------------------------------------------------

_MM3_TO_CM3: float = 1 / 1_000     # 1 cm³  = 1 000 mm³
_MM2_TO_CM2: float = 1 / 100       # 1 cm²  = 100  mm²


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DimensionsMM:
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class GeometryResult:
    """All geometry data extracted from a valid, watertight STL mesh."""

    filename:        str
    dimensions_mm:   DimensionsMM
    volume_cc:       float          # cubic centimetres
    surface_area_cm2: float
    triangle_count:  int
    mesh:            trimesh.Trimesh  # raw mesh – passed to complexity analyser


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class InvalidSTLError(ValueError):
    """Raised when the file cannot be parsed as a valid STL mesh."""


class NonWatertightMeshError(ValueError):
    """Raised when the mesh is valid but not a closed (watertight) solid."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_mesh(path: Path) -> trimesh.Trimesh:
    """
    Load an STL file from *path* and return a single Trimesh.

    Handles both plain Trimesh objects and multi-body Scene objects by
    concatenating all geometries.  Raises InvalidSTLError on empty or
    unloadable files.
    """
    try:
        loaded = trimesh.load_mesh(str(path))
    except Exception as exc:
        raise InvalidSTLError(f"trimesh could not parse the file: {exc}") from exc

    # trimesh returns a Scene when the file contains multiple bodies
    if isinstance(loaded, trimesh.Scene):
        try:
            loaded = loaded.dump(concatenate=True)
        except Exception as exc:
            raise InvalidSTLError(f"Failed to merge multi-body STL scene: {exc}") from exc

    if not isinstance(loaded, trimesh.Trimesh):
        raise InvalidSTLError("File did not produce a usable mesh object.")

    # An empty mesh (zero faces) means the data was garbage even if parseable
    if loaded.is_empty or len(loaded.faces) == 0:
        raise InvalidSTLError("STL file contains no geometry (zero faces).")

    return loaded


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_stl(file_path: Path, original_filename: str) -> GeometryResult:
    """
    Load, validate, and extract geometry from an STL file.

    Args:
        file_path:         Absolute path to the saved STL file on disk.
        original_filename: Client-supplied filename (used in the response).

    Returns:
        GeometryResult with bounding-box dimensions, volume, surface area,
        triangle count, and the raw trimesh object (for complexity analysis).

    Raises:
        InvalidSTLError:        File is corrupt / unreadable / empty.
        NonWatertightMeshError: Mesh has holes or is an open surface.
    """
    logger.info("Processing STL | file='%s'", file_path)

    mesh = _load_mesh(file_path)

    if not mesh.is_watertight:
        logger.warning("Non-watertight mesh | file='%s'", file_path)
        raise NonWatertightMeshError(
            "The mesh is not watertight (it has holes or open edges). "
            "Volume cannot be calculated reliably."
        )

    dx, dy, dz = mesh.extents.tolist()
    volume_cc        = _round(float(mesh.volume) * _MM3_TO_CM3)
    surface_area_cm2 = _round(float(mesh.area)   * _MM2_TO_CM2)
    triangle_count   = int(len(mesh.faces))

    logger.info(
        "Geometry extracted | file='%s' dims=(%.2f, %.2f, %.2f) mm "
        "vol=%.4f cc area=%.4f cm² tris=%d",
        original_filename, dx, dy, dz, volume_cc, surface_area_cm2, triangle_count,
    )

    return GeometryResult(
        filename=original_filename,
        dimensions_mm=DimensionsMM(x=_round(dx), y=_round(dy), z=_round(dz)),
        volume_cc=volume_cc,
        surface_area_cm2=surface_area_cm2,
        triangle_count=triangle_count,
        mesh=mesh,
    )

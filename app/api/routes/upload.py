from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.logger import get_logger
from app.services.complexity_analyzer import ComplexityResult, analyse_complexity
from app.services.file_handler import (
    FileTooLargeError,
    InvalidFileTypeError,
    validate_and_save,
)
from app.services.pricing_engine import (
    InvalidMachineTypeError,
    InvalidMaterialError,
    PriceResult,
    TierUnavailableError,
    calculate_price,
)
from app.services.stl_processor import (
    GeometryResult,
    InvalidSTLError,
    NonWatertightMeshError,
    process_stl,
)
from app.services.support_estimator import SupportEstimate, estimate_support

router = APIRouter(tags=["Upload"])
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DimensionsSchema(BaseModel):
    x: float
    y: float
    z: float


class ComplexityMetricsSchema(BaseModel):
    surface_to_volume_ratio: float
    bounding_box_volume_cc:  float
    volume_efficiency:       float
    triangle_count:          int
    triangle_density:        float


class SupportSchema(BaseModel):
    has_overhangs:         bool
    overhang_face_count:   int
    overhang_area_mm2:     float
    overhang_area_cm2:     float
    support_height_factor: float
    support_volume_cc:     float
    support_ratio_percent: float


class PricingSchema(BaseModel):
    volume_cc:             float
    support_volume_cc:     float
    total_material_cc:     float
    rate_per_cc_min:       float
    rate_per_cc_max:       float
    rate_per_cc:           float
    material_cost:         float
    complexity_multiplier: float
    machine_factor:        float
    support_penalty:       float
    support_ratio_percent: float
    final_price:           float


class UploadSuccessResponse(BaseModel):
    # Geometry
    filename:          str
    dimensions_mm:     DimensionsSchema
    volume_cc:         float
    surface_area_cm2:  float
    triangle_count:    int
    # Auto-detected complexity
    complexity:         str
    complexity_reason:  str
    complexity_metrics: ComplexityMetricsSchema
    # Support estimation
    support:            SupportSchema
    # Pricing
    material:           str
    machine_type:       str
    pricing:            PricingSchema


class UploadErrorResponse(BaseModel):
    error: str


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

_DESCRIPTION = """
Upload a `.stl` file and receive the full analysis pipeline:

1. **Geometry** — dimensions, volume, surface area, triangle count
2. **Auto-detected complexity** — simple / mid_complex / complex (no manual input)
3. **Support estimation** — overhang detection, estimated support volume & ratio
4. **Price estimate** — based on material and machine type

**Form fields:**
| Field | Type | Options |
|---|---|---|
| `file` | `.stl` binary | — |
| `material` | string | `PLA`, `ABS`, `PETG`, `TPU`, `NYLON_PA12`, `CARBON_FIBRE`, `PEEK_PEKK`, `ABS_RESIN`, `TOUGH_RESIN`, `CASTABLE_RESIN`, `MJF_NYLON_PA12`, `ALUMINIUM_AlSi10Mg`, `STAINLESS_STEEL_316L`, `TITANIUM_Ti6Al4V`, `TOOL_STEEL_INCONEL` |
| `machine_type` | string | `desktop` / `mid_industry` / `production` |

Complexity is auto-detected. Support penalty applied automatically from support estimator.
"""


@router.post(
    "/upload-stl",
    response_model=UploadSuccessResponse,
    responses={
        400: {"model": UploadErrorResponse, "description": "File or input validation error"},
        422: {"model": UploadErrorResponse, "description": "Unprocessable STL or unavailable tier"},
        500: {"model": UploadErrorResponse, "description": "Server error"},
    },
    summary="Upload STL → geometry + complexity + support + price",
    description=_DESCRIPTION,
)
async def upload_stl(
    file:         UploadFile = File(..., description="STL file to upload"),
    material:     str        = Form(..., description="Material key, e.g. PLA, ABS, PETG"),
    machine_type: str        = Form(..., description="desktop | mid_industry | production"),
) -> JSONResponse:

    # ── 1. Validate & persist ────────────────────────────────────────────────
    try:
        saved = await validate_and_save(file)
    except InvalidFileTypeError as exc:
        logger.warning("Rejected upload — invalid type: %s", exc)
        return JSONResponse(status_code=400, content={"error": "Invalid file type"})
    except FileTooLargeError as exc:
        logger.warning("Rejected upload — file too large: %s", exc)
        return JSONResponse(status_code=400, content={"error": "File too large"})
    except Exception as exc:
        logger.error("Upload I/O error: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Upload failed"})

    # ── 2. Extract geometry ──────────────────────────────────────────────────
    try:
        geometry: GeometryResult = process_stl(
            file_path=saved.saved_path,
            original_filename=saved.original_filename,
        )
    except NonWatertightMeshError:
        return JSONResponse(status_code=422, content={"error": "Mesh is not watertight"})
    except InvalidSTLError:
        return JSONResponse(status_code=422, content={"error": "Invalid STL file"})
    except Exception as exc:
        logger.error("STL processing failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "STL processing failed"})

    # ── 3. Auto-detect complexity ────────────────────────────────────────────
    try:
        complexity_result: ComplexityResult = analyse_complexity(
            mesh=geometry.mesh,
            volume_cc=geometry.volume_cc,
            surface_area_cm2=geometry.surface_area_cm2,
        )
    except Exception as exc:
        logger.error("Complexity analysis failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Complexity analysis failed"})

    # ── 4. Estimate support material ─────────────────────────────────────────
    try:
        support: SupportEstimate = estimate_support(
            mesh=geometry.mesh,
            z_dim_mm=geometry.dimensions_mm.z,
            volume_cc=geometry.volume_cc,
        )
    except Exception as exc:
        logger.error("Support estimation failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Support estimation failed"})

    # ── 5. Calculate price ───────────────────────────────────────────────────
    try:
        pricing: PriceResult = calculate_price(
            volume_cc=geometry.volume_cc,
            support_volume_cc=support.support_volume_cc,
            material=material,
            complexity=complexity_result.complexity.value,
            machine_type=machine_type,
            support_ratio_percent=support.support_ratio_percent,
        )
    except (InvalidMaterialError, InvalidMachineTypeError) as exc:
        logger.warning("Invalid pricing input: %s", exc)
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except TierUnavailableError as exc:
        logger.warning("Tier unavailable: %s", exc)
        return JSONResponse(status_code=422, content={"error": str(exc)})
    except Exception as exc:
        logger.error("Pricing engine failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Pricing calculation failed"})

    # ── 6. Return unified response ───────────────────────────────────────────
    cm = complexity_result.metrics
    return JSONResponse(
        status_code=200,
        content={
            # Geometry
            "filename":         geometry.filename,
            "dimensions_mm":    {
                "x": geometry.dimensions_mm.x,
                "y": geometry.dimensions_mm.y,
                "z": geometry.dimensions_mm.z,
            },
            "volume_cc":        geometry.volume_cc,
            "surface_area_cm2": geometry.surface_area_cm2,
            "triangle_count":   geometry.triangle_count,
            # Complexity
            "complexity":        complexity_result.complexity.value,
            "complexity_reason": complexity_result.reason,
            "complexity_metrics": {
                "surface_to_volume_ratio": cm.surface_to_volume_ratio,
                "bounding_box_volume_cc":  cm.bounding_box_volume_cc,
                "volume_efficiency":       cm.volume_efficiency,
                "triangle_count":          cm.triangle_count,
                "triangle_density":        cm.triangle_density,
            },
            # Support estimation
            "support": {
                "has_overhangs":         support.has_overhangs,
                "overhang_face_count":   support.overhang_face_count,
                "overhang_area_mm2":     support.overhang_area_mm2,
                "overhang_area_cm2":     support.overhang_area_cm2,
                "support_height_factor": support.support_height_factor,
                "support_volume_cc":     support.support_volume_cc,
                "support_ratio_percent": support.support_ratio_percent,
            },
            # Pricing
            "material":     pricing.material,
            "machine_type": pricing.machine_type,
            "pricing": {
                "volume_cc":             pricing.volume_cc,
                "support_volume_cc":     pricing.support_volume_cc,
                "total_material_cc":     pricing.total_material_cc,
                "rate_per_cc_min":       pricing.rate_per_cc_min,
                "rate_per_cc_max":       pricing.rate_per_cc_max,
                "rate_per_cc":           pricing.rate_per_cc,
                "material_cost":         pricing.material_cost,
                "complexity_multiplier": pricing.complexity_multiplier,
                "machine_factor":        pricing.machine_factor,
                "support_penalty":       pricing.support_penalty,
                "support_ratio_percent": pricing.support_ratio_percent,
                "final_price":           pricing.final_price,
            },
        },
    )

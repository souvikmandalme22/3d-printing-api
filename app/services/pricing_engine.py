"""
Pricing engine for India 3D Printing services.

Rate table sourced from: INDIA 3D PRINTING – COMPLEXITY-BASED PRICING RANGES
Units: ₹ per cm³ (cc)

Tiers:
  - desktop      → Desktop machines
  - mid_industry → Mid-Industry machines
  - production   → Production / Industrial machines

Complexity levels:
  - simple      → Basic shapes, no overhangs, thick walls
  - mid_complex → Logos/text, some overhangs, moderate details
  - complex     → Organic shapes, internal channels, thin walls <1mm, interlocking parts

Price range is [min_rate, max_rate]; mid-point is used for estimation.
'–' in the source chart means that tier is NOT available for that material.

Multipliers applied on top of material cost:
  complexity: simple 1.0× | mid_complex 1.15× | complex 1.30×
  machine:    desktop 1.0× | mid_industry 1.2× | production 1.5×
  support penalty: ratio>30% +10% | ratio>60% +20%
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Multipliers
COMPLEXITY_MULTIPLIER: dict[str, float] = {
    "simple":     1.00,
    "mid_complex": 1.15,
    "complex":    1.30,
}

MACHINE_FACTOR: dict[str, float] = {
    "desktop":      1.0,
    "mid_industry": 1.2,
    "production":   1.5,
}

# Support penalty thresholds
_SUPPORT_PENALTY_HIGH_THRESHOLD: float  = 60.0   # % → +20 %
_SUPPORT_PENALTY_LOW_THRESHOLD:  float  = 30.0   # % → +10 %
_SUPPORT_PENALTY_HIGH:           float  = 0.20
_SUPPORT_PENALTY_LOW:            float  = 0.10

# ---------------------------------------------------------------------------
# Rate table  (₹ / cm³)
# Format: [min, max] — None means the tier is unavailable for that combination
# ---------------------------------------------------------------------------
#
# Key hierarchy:  PRICING_TABLE[material][complexity][machine_type]
#

_R = Optional[list[int]]   # rate pair alias for readability

PRICING_TABLE: dict[str, dict[str, dict[str, _R]]] = {
    # ── FDM Plastics ──────────────────────────────────────────────────────────
    "PLA": {
        "simple": {
            "desktop":      [3,   6],
            "mid_industry": [10,  18],
            "production":   [55,  90],
        },
        "mid_complex": {
            "desktop":      [6,   12],
            "mid_industry": [18,  30],
            "production":   [90,  150],
        },
        "complex": {
            "desktop":      [12,  22],
            "mid_industry": [30,  55],
            "production":   [150, 250],
        },
    },
    "ABS": {
        "simple": {
            "desktop":      [4,   8],
            "mid_industry": [12,  22],
            "production":   [60,  100],
        },
        "mid_complex": {
            "desktop":      [8,   16],
            "mid_industry": [22,  38],
            "production":   [100, 170],
        },
        "complex": {
            "desktop":      [16,  28],
            "mid_industry": [38,  65],
            "production":   [170, 280],
        },
    },
    "PETG": {
        "simple": {
            "desktop":      [5,   9],
            "mid_industry": [12,  22],
            "production":   [60,  100],
        },
        "mid_complex": {
            "desktop":      [9,   16],
            "mid_industry": [22,  38],
            "production":   [100, 170],
        },
        "complex": {
            "desktop":      [16,  28],
            "mid_industry": [38,  65],
            "production":   [170, 280],
        },
    },
    "TPU": {
        "simple": {
            "desktop":      [6,   12],
            "mid_industry": [15,  28],
            "production":   [70,  120],
        },
        "mid_complex": {
            "desktop":      [12,  22],
            "mid_industry": [28,  48],
            "production":   [120, 200],
        },
        "complex": {
            "desktop":      [22,  38],
            "mid_industry": [48,  80],
            "production":   [200, 340],
        },
    },
    "NYLON_PA12": {
        "simple": {
            "desktop":      [8,   18],
            "mid_industry": [32,  45],
            "production":   [80,  140],
        },
        "mid_complex": {
            "desktop":      [18,  30],
            "mid_industry": [45,  70],
            "production":   [140, 230],
        },
        "complex": {
            "desktop":      [30,  50],
            "mid_industry": [70,  110],
            "production":   [230, 380],
        },
    },
    # ── FDM Composites ────────────────────────────────────────────────────────
    "CARBON_FIBRE": {
        "simple": {
            "desktop":      [20,  50],
            "mid_industry": [60,  110],
            "production":   [150, 280],
        },
        "mid_complex": {
            "desktop":      [50,  90],
            "mid_industry": [110, 180],
            "production":   [280, 450],
        },
        "complex": {
            "desktop":      [90,  160],
            "mid_industry": [180, 300],
            "production":   [450, 750],
        },
    },
    # ── High-Performance FDM ─────────────────────────────────────────────────
    "PEEK_PEKK": {
        "simple": {
            "desktop":      [80,  150],
            "mid_industry": [200, 350],
            "production":   [450, 800],
        },
        "mid_complex": {
            "desktop":      [150, 260],
            "mid_industry": [350, 600],
            "production":   [800, 1400],
        },
        "complex": {
            "desktop":      [260, 420],
            "mid_industry": [600, 1000],
            "production":   [1400, 2500],
        },
    },
    # ── Resins (SLA / DLP) ────────────────────────────────────────────────────
    "ABS_RESIN": {
        "simple": {
            "desktop":      [25,  40],
            "mid_industry": [35,  60],
            "production":   [90,  160],
        },
        "mid_complex": {
            "desktop":      [40,  70],
            "mid_industry": [60,  100],
            "production":   [160, 270],
        },
        "complex": {
            "desktop":      [70,  120],
            "mid_industry": [100, 170],
            "production":   [270, 450],
        },
    },
    "TOUGH_RESIN": {
        "simple": {
            "desktop":      [40,  70],
            "mid_industry": [60,  95],
            "production":   [120, 210],
        },
        "mid_complex": {
            "desktop":      [70,  120],
            "mid_industry": [95,  160],
            "production":   [210, 360],
        },
        "complex": {
            "desktop":      [120, 200],
            "mid_industry": [160, 280],
            "production":   [360, 600],
        },
    },
    "CASTABLE_RESIN": {
        "simple": {
            "desktop":      [60,  110],
            "mid_industry": [90,  150],
            "production":   [200, 380],
        },
        "mid_complex": {
            "desktop":      [110, 180],
            "mid_industry": [150, 260],
            "production":   [380, 650],
        },
        "complex": {
            "desktop":      [180, 300],
            "mid_industry": [260, 440],
            "production":   [650, 1100],
        },
    },
    # ── HP Multi Jet Fusion ───────────────────────────────────────────────────
    "MJF_NYLON_PA12": {
        "simple": {
            "desktop":      None,           # not available on desktop
            "mid_industry": [32,  45],
            "production":   [80,  130],
        },
        "mid_complex": {
            "desktop":      None,
            "mid_industry": [45,  72],
            "production":   [130, 210],
        },
        "complex": {
            "desktop":      None,
            "mid_industry": [72,  120],
            "production":   [210, 350],
        },
    },
    # ── Metal – DMLS / SLM / EBM ─────────────────────────────────────────────
    "ALUMINIUM_AlSi10Mg": {
        "simple": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [200, 400],
        },
        "mid_complex": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [400, 700],
        },
        "complex": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [700, 1200],
        },
    },
    "STAINLESS_STEEL_316L": {
        "simple": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [250, 500],
        },
        "mid_complex": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [500, 850],
        },
        "complex": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [850, 1500],
        },
    },
    "TITANIUM_Ti6Al4V": {
        "simple": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [400, 800],
        },
        "mid_complex": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [800, 1400],
        },
        "complex": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [1400, 2500],
        },
    },
    "TOOL_STEEL_INCONEL": {
        "simple": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [600, 1200],
        },
        "mid_complex": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [1200, 2000],
        },
        "complex": {
            "desktop":      None,
            "mid_industry": None,
            "production":   [2000, 3500],
        },
    },
}

# ---------------------------------------------------------------------------
# Valid enum sets (derived from the table — single source of truth)
# ---------------------------------------------------------------------------

VALID_MATERIALS:     frozenset[str] = frozenset(PRICING_TABLE.keys())
VALID_COMPLEXITIES:  frozenset[str] = frozenset({"simple", "mid_complex", "complex"})
VALID_MACHINE_TYPES: frozenset[str] = frozenset({"desktop", "mid_industry", "production"})


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PriceResult:
    # Inputs (normalised)
    material:     str
    complexity:   str
    machine_type: str
    # Volume breakdown
    volume_cc:               float   # part volume from STL processor
    support_volume_cc:       float   # estimated support material
    total_material_cc:       float   # volume_cc + support_volume_cc
    # Rate
    rate_per_cc_min:         float   # lower bound from rate table
    rate_per_cc_max:         float   # upper bound from rate table
    rate_per_cc:             float   # mid-point: (min + max) / 2
    # Cost components (logged separately for auditability)
    material_cost:           float   # total_material_cc * rate_per_cc
    complexity_multiplier:   float   # 1.0 / 1.15 / 1.30
    machine_factor:          float   # 1.0 / 1.2 / 1.5
    support_penalty:         float   # 0.0 / 0.10 / 0.20
    support_ratio_percent:   float   # (support_vol / part_vol) * 100
    # Final
    final_price:             float   # after all multipliers and penalty


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class InvalidMaterialError(ValueError):
    """Raised when the requested material is not in the rate table."""


class InvalidComplexityError(ValueError):
    """Raised when the complexity level is unrecognised."""


class InvalidMachineTypeError(ValueError):
    """Raised when the machine type is unrecognised."""


class TierUnavailableError(ValueError):
    """Raised when the rate-table entry is explicitly None (tier not offered)."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise_material(raw: str) -> str:
    """
    Case-insensitive lookup against PRICING_TABLE keys.
    Returns the *canonical* key (preserving original casing, e.g. TITANIUM_Ti6Al4V).
    Raises InvalidMaterialError if not found.
    """
    stripped = raw.strip()
    # Build a map from upper-cased key -> canonical key (table is tiny)
    lookup = {k.upper(): k for k in VALID_MATERIALS}
    canonical = lookup.get(stripped.upper())
    if canonical is None:
        available = ", ".join(sorted(VALID_MATERIALS))
        raise InvalidMaterialError(
            f"Material '{raw}' is not supported. Available: {available}"
        )
    return canonical


def _normalise_complexity(raw: str) -> str:
    """Lower-case and strip; accept 'mid' as alias for 'mid_complex'."""
    normalised = raw.strip().lower()
    if normalised == "mid":
        normalised = "mid_complex"
    if normalised not in VALID_COMPLEXITIES:
        raise InvalidComplexityError(
            f"Complexity '{raw}' is invalid. Choose: simple, mid_complex (or 'mid'), complex"
        )
    return normalised


def _normalise_machine_type(raw: str) -> str:
    """Lower-case and strip the input; raise if not recognised."""
    normalised = raw.strip().lower()
    if normalised not in VALID_MACHINE_TYPES:
        raise InvalidMachineTypeError(
            f"Machine type '{raw}' is invalid. Choose: desktop, mid_industry, production"
        )
    return normalised


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _support_penalty(support_ratio_percent: float) -> float:
    """Return the support penalty fraction based on support_ratio_percent."""
    if support_ratio_percent > _SUPPORT_PENALTY_HIGH_THRESHOLD:
        return _SUPPORT_PENALTY_HIGH
    if support_ratio_percent > _SUPPORT_PENALTY_LOW_THRESHOLD:
        return _SUPPORT_PENALTY_LOW
    return 0.0


def calculate_price(
    volume_cc:            float,
    support_volume_cc:    float,
    material:             str,
    complexity:           str,
    machine_type:         str,
    support_ratio_percent: float = 0.0,
) -> PriceResult:
    """
    Calculate a fully-costed print price with support material and multipliers.

    Formula
    -------
    total_material_cc = volume_cc + support_volume_cc
    material_cost     = total_material_cc × rate_per_cc
    final_price       = material_cost × complexity_multiplier × machine_factor × (1 + penalty)

    Args:
        volume_cc:             Part volume in cm³.
        support_volume_cc:     Estimated support material in cm³ (from support_estimator).
        material:              Material key e.g. "PLA", "ABS", "PEEK_PEKK".
        complexity:            "simple" | "mid_complex" | "mid" | "complex".
        machine_type:          "desktop" | "mid_industry" | "production".
        support_ratio_percent: (support_vol / part_vol) × 100 from support_estimator.

    Returns:
        PriceResult with full cost breakdown.

    Raises:
        InvalidMaterialError, InvalidComplexityError, InvalidMachineTypeError,
        TierUnavailableError, ValueError (negative / zero volumes)
    """
    # ── Input validation ──────────────────────────────────────────────────────
    if volume_cc <= 0:
        raise ValueError(f"volume_cc must be positive, got {volume_cc}")
    if support_volume_cc < 0:
        raise ValueError(f"support_volume_cc must be >= 0, got {support_volume_cc}")
    if support_ratio_percent < 0:
        raise ValueError(f"support_ratio_percent must be >= 0, got {support_ratio_percent}")

    # ── Normalise string inputs ───────────────────────────────────────────────
    mat  = _normalise_material(material)
    comp = _normalise_complexity(complexity)
    mach = _normalise_machine_type(machine_type)

    # ── Rate table lookup ─────────────────────────────────────────────────────
    rate_pair: _R = PRICING_TABLE[mat][comp][mach]
    if rate_pair is None:
        raise TierUnavailableError(
            f"The combination {mat} / {comp} / {mach} is not available "
            f"(this tier is not offered for this material). "
            f"Try a different machine_type."
        )

    rate_min, rate_max = float(rate_pair[0]), float(rate_pair[1])
    rate_per_cc        = (rate_min + rate_max) / 2.0

    # ── Volume and material cost ──────────────────────────────────────────────
    total_material_cc = _round(volume_cc + support_volume_cc)
    material_cost     = _round(total_material_cc * rate_per_cc)

    # ── Multipliers ───────────────────────────────────────────────────────────
    comp_mult    = COMPLEXITY_MULTIPLIER[comp]
    mach_factor  = MACHINE_FACTOR[mach]
    supp_penalty = _support_penalty(support_ratio_percent)

    # ── Final price (applied in order: complexity → machine → support penalty) ─
    price = material_cost * comp_mult * mach_factor * (1.0 + supp_penalty)
    final_price = _round(price)

    # ── Component log for auditability and future ML training ─────────────────
    logger.info(
        "PriceCalc | material=%s complexity=%s machine=%s | "
        "vol=%.4f supp=%.4f total=%.4f cc | "
        "rate=₹%.2f/cc material_cost=₹%.4f | "
        "complexity_mult=%.2f machine_factor=%.2f support_penalty=%.2f support_ratio=%.2f%% | "
        "final=₹%.4f",
        mat, comp, mach,
        volume_cc, support_volume_cc, total_material_cc,
        rate_per_cc, material_cost,
        comp_mult, mach_factor, supp_penalty, support_ratio_percent,
        final_price,
    )

    return PriceResult(
        material=mat,
        complexity=comp,
        machine_type=mach,
        volume_cc=_round(volume_cc),
        support_volume_cc=_round(support_volume_cc),
        total_material_cc=total_material_cc,
        rate_per_cc_min=rate_min,
        rate_per_cc_max=rate_max,
        rate_per_cc=_round(rate_per_cc),
        material_cost=material_cost,
        complexity_multiplier=comp_mult,
        machine_factor=mach_factor,
        support_penalty=supp_penalty,
        support_ratio_percent=_round(support_ratio_percent),
        final_price=final_price,
    )

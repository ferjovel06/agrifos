"""Bibliographic evaluation only; never emits executable applications.

Native quantities are kg of received solids and L of biol concentrate.
The mineral targets are screening constraints, not toxicity thresholds.
"""
from dataclasses import dataclass
from itertools import combinations
import math

from app.schemas.fertilization import (
    FertilizerScenarioRead, OrganicCandidateDoseRead, OrganicScenarioRead,
)

MODEL_VERSION = "organic-reference-screen-1.0.0"
PROFILE_VERSION = "bocashi-biol-pulp-reference-2026-10-06"
NUTRIENTS = ("N", "P2O5", "K2O")


@dataclass(frozen=True)
class OrganicSource:
    key: str
    name: str
    unit: str
    concentration: tuple[float, float, float]


def _dry(n: float, p: float, k: float, humidity: float):
    dry = 1 - humidity / 100
    return (n / 100 * dry, p / 100 * 2.291 * dry, k / 100 * 1.205 * dry)


SOURCES = (
    OrganicSource("bocashi", "Bocashi", "kg", _dry(1.31, 1.04, .97, 41)),
    OrganicSource("biol", "Biol", "L", (
        584.60 / 1e6, 201.80 * 2.291 / 1e6, 1983.33 * 1.205 / 1e6,
    )),
    OrganicSource("coffee_pulp_compost", "Compost de pulpa de café", "kg",
                  _dry(2.99, .19, 2.52, 58)),
)
SOURCE_URLS = [
    "https://publicaciones.cenicafe.org/index.php/libros_manuales/article/download/3239/3274",
    "https://cafecacao.edicionescervantes.com/index.php/cafecacao/article/download/278/279/550?inline=1",
]


def organic_fingerprint_context() -> dict:
    return {
        "model": MODEL_VERSION, "profile": PROFILE_VERSION,
        "biol_reference_volume_l_ha": 100,
        "policy": "total_N_P_K_bounded_by_mineral_targets",
        "profiles": [
            {"key": s.key, "unit": s.unit, "concentration": s.concentration}
            for s in SOURCES
        ],
    }


def _reference_quantities(target: tuple[float, float, float]):
    """Fix illustrative biol <=100 L, then examine vertices for two solids.

    Bound every total nutrient by its screening target, including zero targets.
    Maximize the sum of normalized nutrient coverages; no field optimization.
    """
    bocashi, biol, compost = SOURCES
    volume = min(100.0, *(t / c for t, c in zip(target, biol.concentration)))
    remaining = [max(0.0, t - volume * c)
                 for t, c in zip(target, biol.concentration)]
    boundaries = [
        (bocashi.concentration[j], compost.concentration[j], remaining[j])
        for j in range(3)
    ] + [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    feasible = [(0.0, 0.0)]
    for (a, b, c), (d, e, f) in combinations(boundaries, 2):
        determinant = a * e - b * d
        if abs(determinant) < 1e-14:
            continue
        x, y = (c * e - b * f) / determinant, (a * f - c * d) / determinant
        if x < -1e-8 or y < -1e-8:
            continue
        x, y = max(0.0, x), max(0.0, y)
        if all(x * a + y * b <= cap + 1e-8
               for a, b, cap in boundaries[:3]):
            feasible.append((x, y))
    def score(pair):
        x, y = pair
        return sum((x * bocashi.concentration[j] + y * compost.concentration[j]) / t
                   for j, t in enumerate(target) if t > 0)
    x, y = max(feasible, key=score)
    # Reference quantities are rounded down to avoid exceeding screening caps.
    return tuple(math.floor(q * 100) / 100 for q in (x, volume, y))


def build_organic_scenario(requirements: dict[str, float], *,
                           hectares_per_manzana: float,
                           plants_per_hectare: int) -> FertilizerScenarioRead:
    target = tuple(requirements[n] for n in NUTRIENTS)
    if any(not math.isfinite(v) or v < 0 for v in target):
        raise ValueError("Organic screening targets must be finite and nonnegative.")
    if not math.isfinite(hectares_per_manzana) or hectares_per_manzana <= 0 or plants_per_hectare <= 0:
        raise ValueError("Invalid area conversion or plant density.")
    quantities = _reference_quantities(target)
    candidates = []
    total = dict.fromkeys(NUTRIENTS, 0.0)
    for source, quantity in zip(SOURCES, quantities):
        contributions = {n: quantity * c for n, c in zip(NUTRIENTS, source.concentration)}
        for n, value in contributions.items():
            total[n] += value
        candidates.append(OrganicCandidateDoseRead(
            product_key=source.key, product=source.name, unit=source.unit,
            quantity_ha=quantity,
            quantity_manzana=round(quantity * hectares_per_manzana, 2),
            quantity_plant=round(quantity * 1000 / plants_per_hectare, 2),
            plant_unit="mL" if source.unit == "L" else "g",
            concentration_kg_per_unit=dict(zip(NUTRIENTS, source.concentration)),
            nutrient_contributions_kg_ha={n: round(v, 4) for n, v in contributions.items()},
        ))
    shortfall = {n: max(0.0, requirements[n] - total[n]) for n in NUTRIENTS}
    surplus = {n: max(0.0, total[n] - requirements[n]) for n in NUTRIENTS}
    partial = any(v > .02 for v in shortfall.values())
    return FertilizerScenarioRead(
        name="Orgánico", selection_method=MODEL_VERSION,
        is_mathematically_valid=False, products=[], application_schedule=[],
        organic=OrganicScenarioRead(
            state="partial" if partial else "reference_only",
            model_version=MODEL_VERSION, profile_version=PROFILE_VERSION,
            candidates=candidates,
            total_contributions_kg_ha={n: round(v, 4) for n, v in total.items()},
            reference_shortfall_kg_ha={n: round(v, 4) for n, v in shortfall.items()},
            reference_surplus_kg_ha={n: round(v, 4) for n, v in surplus.items()},
            reason_codes=["unverified_lots", "unknown_nutrient_availability"]
                         + (["incomplete_reference_balance"] if partial else []),
            sources=SOURCE_URLS,
            notices=[
                "Evaluación bibliográfica; cantidades de referencia, no dosis para aplicar.",
                "Biol: volumen ilustrativo hasta 100 L/ha de concentrado; no es una dosis validada.",
                "Los objetivos minerales limitan este cálculo; no son umbrales de toxicidad.",
                "Faltan análisis de lotes, disponibilidad de nutrientes, vía y calendario aprobados.",
                "Compost: aproximación con pulpa descompuesta; verificar madurez y humedad.",
            ],
        ),
    )

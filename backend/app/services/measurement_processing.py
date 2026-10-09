"""Batch-only, non-destructive processing of repeated physical measurements.

Communication integrity, repeatability, and analytical accuracy are independent.
No device ranges, stability thresholds, unit conversions, or accuracy are inferred.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from math import isfinite, sqrt
from statistics import fmean, median, pstdev
from typing import Literal, Sequence

ALGORITHM_VERSION = "same-point-centered-2"
_NUTRIENTS = {"N", "NO3-N", "NO3", "P", "P2O5", "K", "K2O", "nitrogen", "phosphorus", "potassium"}
_UNITS = {**{name: {"mg/kg", "mg/L", "ppm", "%"} for name in _NUTRIENTS},
          "humidity": {"%"}, "temperature": {"degC"}, "ph": {"pH"},
          "ec": {"dS/m", "mS/cm", "uS/cm"}}


@dataclass(frozen=True)
class MeasurementSample:
    measurement_id: str
    session_id: str
    device_id: str
    parcel_id: str
    point_id: str | None
    analyte: str
    value: float | None
    unit: str
    acquired_at: datetime
    received_at: datetime
    protocol_version: str = ""
    reading_status: str = "valid"
    declared_range: tuple[float, float] | None = None
    device_model: str | None = None
    depth_cm: float | None = None
    acquisition_profile_id: str | None = None
    soil_type: str | None = None


@dataclass(frozen=True)
class ProcessingConfig:
    window: int = 5
    method: Literal["none", "mean", "median"] = "median"
    # These limits must come from documented empirical/device evidence.
    mad_multiplier: float | None = None
    max_mad: float | None = None
    max_jump: float | None = None
    minimum_stabilization_seconds: float | None = None
    threshold_evidence: str | None = None

    def __post_init__(self):
        if self.window < 3 or self.window % 2 != 1:
            raise ValueError("window must be an odd integer >= 3")
        if self.method not in {"none", "mean", "median"}:
            raise ValueError("unknown filter")
        limits = (self.mad_multiplier, self.max_mad, self.max_jump,
                  self.minimum_stabilization_seconds)
        if any(v is not None and (not isfinite(v) or v < 0) for v in limits):
            raise ValueError("thresholds must be finite and non-negative")
        if any(v is not None for v in limits) and not self.threshold_evidence:
            raise ValueError("configured thresholds require documented evidence")


@dataclass(frozen=True)
class ProcessedSample:
    raw: MeasurementSample
    filtered: float | None
    algorithm_version: str
    transmission_state: str
    repeatability_state: str
    accuracy_state: str
    quality_state: str
    reason_codes: tuple[str, ...]
    group_median: float | None = None
    group_mad: float | None = None


def centered_filter(values: Sequence[float], *, window: int = 5,
                    method: str = "median") -> tuple[list[float], list[bool]]:
    """Preserve edges/short series; the boolean marks a complete applied window."""
    ProcessingConfig(window=window, method=method)
    if not all(isfinite(v) for v in values):
        raise ValueError("filter input must be finite")
    output, applied = list(values), [False] * len(values)
    radius = window // 2
    if method != "none":
        operation = median if method == "median" else fmean
        for i in range(radius, len(values) - radius):
            output[i] = operation(values[i - radius:i + radius + 1])
            applied[i] = True
    return output, applied


def is_compatible_unit(analyte: str, unit: str) -> bool:
    """Recognized quantity/unit combination, without equating nutrient species."""
    return analyte in _UNITS and unit in _UNITS[analyte]


def process_measurements(samples: Sequence[MeasurementSample],
                         config: ProcessingConfig = ProcessingConfig()) -> list[ProcessedSample]:
    """Process consecutive comparable runs, never across points or invalid gaps.

    Input order is acquisition order. A time reversal ends a run. Revisiting a
    point after another point does not silently join two measurement sequences.
    """
    ids = Counter((s.measurement_id, s.analyte) for s in samples)
    known_units = set().union(*_UNITS.values())
    reasons: list[list[str]] = [[] for _ in samples]
    invalid, eligible = [False] * len(samples), [True] * len(samples)
    for i, sample in enumerate(samples):
        codes = reasons[i]
        if sample.value is None:
            codes.append("MISSING_VALUE")
        elif not isfinite(sample.value):
            codes.append("NON_FINITE_VALUE")
        if sample.unit not in known_units:
            codes.append("UNKNOWN_UNIT")
        if sample.analyte not in _UNITS:
            codes.append("ANALYTE_UNIDENTIFIED")
            eligible[i] = False
        elif sample.unit in known_units and sample.unit not in _UNITS[sample.analyte]:
            codes.append("INCOMPATIBLE_UNIT")
        if sample.reading_status not in {"valid", "suspect"}:
            codes.append("TRANSMISSION_" + sample.reading_status.upper())
        elif sample.reading_status == "suspect":
            codes.append("TRANSMISSION_SUSPECT")
        if sample.acquired_at.tzinfo is None or sample.received_at.tzinfo is None:
            codes.append("TIMESTAMP_WITHOUT_TIMEZONE")
        elif sample.received_at < sample.acquired_at:
            codes.append("TIMESTAMP_ORDER_INCONSISTENT")
        if sample.declared_range is not None:
            low, high = sample.declared_range
            if not isfinite(low) or not isfinite(high) or low > high:
                codes.append("INVALID_DECLARED_RANGE")
            elif sample.value is not None and isfinite(sample.value) and not low <= sample.value <= high:
                codes.append("OUTSIDE_DECLARED_RANGE")
        if ids[(sample.measurement_id, sample.analyte)] > 1:
            codes.append("DUPLICATE_MEASUREMENT_ID")
        if not all((sample.session_id, sample.device_id, sample.parcel_id, sample.point_id)):
            codes.append("PHYSICAL_CONTEXT_INCOMPLETE")
            eligible[i] = False
        invalid[i] = any(c not in {"ANALYTE_UNIDENTIFIED", "TRANSMISSION_SUSPECT",
                                  "TIMESTAMP_ORDER_INCONSISTENT", "PHYSICAL_CONTEXT_INCOMPLETE"}
                         for c in codes)
        eligible[i] = eligible[i] and not invalid[i]
    filtered = [s.value if s.value is not None and isfinite(s.value) else None for s in samples]
    medians, mads = [None] * len(samples), [None] * len(samples)
    runs: list[list[int]] = []
    last_by_variable: dict[tuple[str, str], int] = {}
    physical_context = None
    for i, sample in enumerate(samples):
        context = (sample.session_id, sample.device_id, sample.parcel_id, sample.point_id,
                   sample.protocol_version, sample.device_model, sample.depth_cm,
                   sample.acquisition_profile_id, sample.soil_type)
        if context != physical_context:
            last_by_variable.clear()
            physical_context = context
        variable = (sample.analyte, sample.unit)
        if not eligible[i]:
            # An incomplete frame/unknown quantity may have a different key from
            # the missing channel. End every run, rather than bridge the gap.
            last_by_variable.clear()
            continue
        run_index = last_by_variable.get(variable)
        previous = runs[run_index][-1] if run_index is not None else None
        if previous is None or sample.acquired_at <= samples[previous].acquired_at:
            if previous is not None:
                reasons[i].append("NON_INCREASING_TIMESTAMP")
            runs.append([])
            run_index = len(runs) - 1
            last_by_variable[variable] = run_index
        runs[run_index].append(i)
    for run in filter(None, runs):
        values = [float(samples[i].value) for i in run]
        middle = median(values)
        mad = median([abs(v - middle) for v in values])
        output, applied = centered_filter(values, window=config.window, method=config.method)
        for j, i in enumerate(run):
            filtered[i], medians[i], mads[i] = output[j], middle, mad
            if len(run) < config.window:
                reasons[i].append("INSUFFICIENT_REPETITIONS")
            elif config.method != "none" and not applied[j]:
                reasons[i].append("CENTERED_WINDOW_EDGE")
            if len(run) >= config.window and mad == 0:
                reasons[i].append("ZERO_MAD_DEVIATION" if values[j] != middle else "CONSTANT_REPETITIONS" if all(v == middle for v in values) else "ZERO_MAD")
            elif (len(run) >= config.window and config.mad_multiplier is not None
                  and abs(values[j] - middle) > config.mad_multiplier * mad):
                reasons[i].append("MAD_OUTLIER")
            if config.max_mad is not None and mad > config.max_mad:
                reasons[i].append("EXCESS_REPEATABILITY_DISPERSION")
            if j and config.max_jump is not None and abs(values[j] - values[j - 1]) > config.max_jump:
                reasons[i].append("ABRUPT_JUMP")
            if config.minimum_stabilization_seconds is None:
                reasons[i].append("STABILIZATION_NOT_ESTABLISHED")
            elif (samples[i].acquired_at - samples[run[0]].acquired_at).total_seconds() < config.minimum_stabilization_seconds:
                reasons[i].append("INSUFFICIENT_STABILIZATION")
    suspect = {"ANALYTE_UNIDENTIFIED", "TRANSMISSION_SUSPECT", "TIMESTAMP_ORDER_INCONSISTENT",
               "NON_INCREASING_TIMESTAMP", "MAD_OUTLIER", "ZERO_MAD_DEVIATION",
               "CONSTANT_REPETITIONS", "EXCESS_REPEATABILITY_DISPERSION", "ABRUPT_JUMP",
               "INSUFFICIENT_STABILIZATION"}
    transmission_failures = {"MISSING_VALUE", "NON_FINITE_VALUE", "TIMESTAMP_WITHOUT_TIMEZONE",
                             "DUPLICATE_MEASUREMENT_ID"}
    return [ProcessedSample(
        raw=s, filtered=filtered[i], algorithm_version=ALGORITHM_VERSION,
        transmission_state="invalid" if any(c.startswith("TRANSMISSION_") and c != "TRANSMISSION_SUSPECT" or c in transmission_failures for c in reasons[i]) else "suspect" if "TRANSMISSION_SUSPECT" in reasons[i] else "valid",
        repeatability_state="suspect" if suspect.intersection(reasons[i]) else "not_established" if "INSUFFICIENT_REPETITIONS" in reasons[i] or medians[i] is None else "described",
        accuracy_state="uncalibrated",
        quality_state="invalid" if invalid[i] else "suspect" if suspect.intersection(reasons[i]) else "valid",
        reason_codes=tuple(reasons[i]), group_median=medians[i], group_mad=mads[i],
    ) for i, s in enumerate(samples)]


def series_metrics(values: Sequence[float], reference: Sequence[float] | None = None) -> dict:
    """Descriptive dispersion and, only when provided, error against a reference."""
    if not values or not all(isfinite(v) for v in values):
        raise ValueError("a non-empty finite series is required")
    middle = median(values)
    result = {"count": len(values), "median": middle,
              "mad": median([abs(v - middle) for v in values]),
              "population_stddev": pstdev(values)}
    if reference is not None:
        if len(reference) != len(values) or not all(isfinite(v) for v in reference):
            raise ValueError("reference must match the finite series")
        errors = [x - y for x, y in zip(values, reference)]
        result.update(mae=fmean(abs(e) for e in errors),
                      rmse=sqrt(fmean(e * e for e in errors)), bias=fmean(errors))
    return result

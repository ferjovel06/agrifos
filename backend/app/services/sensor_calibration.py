"""Small, interpretable, grouped calibration tools; no production coefficients.

Profiles remain candidates until independent, comparable *real* reference data
improve both MAE and RMSE. Repeated readings are averaged per physical sample,
not treated as independent observations. These checks are necessary, not proof
of laboratory accuracy or an uncertainty model.
"""
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from hashlib import sha256
from json import dumps
from math import fsum, isfinite, sqrt
from statistics import fmean
from typing import Mapping, Sequence

from app.services.measurement_processing import is_compatible_unit

CALIBRATION_ALGORITHM = "grouped-linear-qr-1"


class CalibrationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CalibrationPair:
    sample_group_id: str
    analyte: str
    sensor_value: float
    reference_value: float
    unit: str
    reference_method: str
    reference_basis: str
    comparability_evidence: str
    predictors: tuple[tuple[str, float], ...] = ()
    predictor_units: tuple[tuple[str, str], ...] = ()
    device_id: str | None = None
    parcel_id: str | None = None
    soil_type: str | None = None
    synthetic: bool = False
    sensor_model: str | None = None
    protocol_version: str | None = None
    acquisition_profile_id: str | None = None
    depth_cm: float | None = None


@dataclass(frozen=True)
class CalibrationScope:
    device_ids: tuple[str, ...]
    parcel_ids: tuple[str, ...] = ()
    soil_types: tuple[str, ...] = ()
    measurement_contexts: tuple[tuple[str, str, str], ...] = ()
    depth_range: tuple[float, float] | None = None


@dataclass(frozen=True)
class ErrorMetrics:
    count: int
    mae: float
    rmse: float
    bias: float
    r2: float | None
    residuals: tuple[float, ...]


@dataclass(frozen=True)
class CalibrationProfile:
    profile_id: str
    version: int
    state: str
    analyte: str
    unit: str
    model_kind: str
    predictor_names: tuple[str, ...]
    predictor_units: tuple[tuple[str, str], ...]
    coefficients: tuple[float, ...]
    feature_ranges: tuple[tuple[str, float, float], ...]
    scope: CalibrationScope
    train_group_ids: tuple[str, ...]
    holdout_group_ids: tuple[str, ...]
    dataset_fingerprint: str
    reference_method: str
    reference_basis: str
    training_evidence: str
    trained_at: datetime
    synthetic: bool
    algorithm_version: str = CALIBRATION_ALGORITHM
    validation_evidence: str | None = None
    calibrated_metrics: ErrorMetrics | None = None
    baseline_metrics: ErrorMetrics | None = None


@dataclass(frozen=True)
class CalibrationEstimate:
    value: float
    profile_id: str
    profile_version: int
    algorithm_version: str
    accuracy_state: str = "calibrated"
    uncertainty: None = None


def error_metrics(predictions: Sequence[float], references: Sequence[float]) -> ErrorMetrics:
    if not predictions or len(predictions) != len(references) or not all(isfinite(v) for v in (*predictions, *references)):
        raise CalibrationError("INVALID_METRIC_INPUT")
    residuals = tuple(x - y for x, y in zip(predictions, references))
    sse = fsum(e * e for e in residuals)
    middle = fmean(references)
    total = fsum((v - middle) ** 2 for v in references)
    return ErrorMetrics(len(residuals), fmean(abs(e) for e in residuals),
                        sqrt(sse / len(residuals)), fmean(residuals),
                        1 - sse / total if total > 0 else None, residuals)


def _check_scope(scope: CalibrationScope, device_id: str | None,
                 parcel_id: str | None, soil_type: str | None,
                 sensor_model: str | None = None, protocol_version: str | None = None,
                 acquisition_profile_id: str | None = None, depth_cm: float | None = None):
    if not scope.device_ids or device_id not in scope.device_ids:
        raise CalibrationError("DEVICE_OUTSIDE_SCOPE")
    if scope.parcel_ids and parcel_id not in scope.parcel_ids:
        raise CalibrationError("PARCEL_OUTSIDE_SCOPE")
    if scope.soil_types and soil_type not in scope.soil_types:
        raise CalibrationError("SOIL_OUTSIDE_SCOPE")
    if scope.measurement_contexts and (sensor_model, protocol_version, acquisition_profile_id) not in scope.measurement_contexts:
        raise CalibrationError("ACQUISITION_CONTEXT_OUTSIDE_SCOPE")
    if scope.depth_range is not None:
        low, high = scope.depth_range
        if not isfinite(low) or not isfinite(high) or low > high:
            raise CalibrationError("INVALID_DEPTH_SCOPE")
        if depth_cm is None or not isfinite(depth_cm) or not low <= depth_cm <= high:
            raise CalibrationError("DEPTH_OUTSIDE_SCOPE")


def _fingerprint(pairs: Sequence[CalibrationPair]) -> str:
    records = sorted((asdict(p) for p in pairs), key=lambda p: dumps(p, sort_keys=True))
    return sha256(dumps(records, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _groups(pairs: Sequence[CalibrationPair], analyte: str, unit: str,
            predictor_names: tuple[str, ...], scope: CalibrationScope) -> list[CalibrationPair]:
    if not is_compatible_unit(analyte, unit):
        raise CalibrationError("INCOMPATIBLE_ANALYTE_OR_UNIT")
    grouped: dict[str, list[CalibrationPair]] = {}
    for p in pairs:
        if p.analyte != analyte or p.unit != unit:
            raise CalibrationError("INCOMPATIBLE_ANALYTE_OR_UNIT")
        if not all((p.sample_group_id, p.reference_method, p.reference_basis, p.comparability_evidence)):
            raise CalibrationError("REFERENCE_COMPARABILITY_NOT_DOCUMENTED")
        _check_scope(scope, p.device_id, p.parcel_id, p.soil_type,
                     p.sensor_model, p.protocol_version, p.acquisition_profile_id, p.depth_cm)
        features, units = dict(p.predictors), dict(p.predictor_units)
        if len(features) != len(p.predictors) or len(units) != len(p.predictor_units):
            raise CalibrationError("DUPLICATE_PREDICTOR")
        if any(n not in features or n not in units or not units[n] for n in predictor_names):
            raise CalibrationError("MISSING_PREDICTOR")
        if not all(isfinite(v) for v in (p.sensor_value, p.reference_value, *(features[n] for n in predictor_names))):
            raise CalibrationError("NON_FINITE_CALIBRATION_DATA")
        grouped.setdefault(p.sample_group_id, []).append(p)
    result = []
    for group_id in sorted(grouped):
        members = grouped[group_id]
        base = members[0]
        if any((p.reference_method, p.reference_basis, p.device_id, p.parcel_id,
                p.soil_type, dict(p.predictor_units), p.sensor_model, p.protocol_version,
                p.acquisition_profile_id, p.depth_cm) !=
               (base.reference_method, base.reference_basis, base.device_id,
                base.parcel_id, base.soil_type, dict(base.predictor_units), base.sensor_model,
                base.protocol_version, base.acquisition_profile_id, base.depth_cm) for p in members):
            raise CalibrationError("PHYSICAL_GROUP_CONTEXT_MISMATCH")
        result.append(replace(base, sensor_value=fmean(p.sensor_value for p in members),
                              reference_value=fmean(p.reference_value for p in members),
                              predictors=tuple((n, fmean(dict(p.predictors)[n] for p in members)) for n in predictor_names),
                              synthetic=any(p.synthetic for p in members)))
    if not result:
        raise CalibrationError("INSUFFICIENT_INDEPENDENT_GROUPS")
    if any((p.reference_method, p.reference_basis, dict(p.predictor_units)) !=
           (result[0].reference_method, result[0].reference_basis, dict(result[0].predictor_units)) for p in result):
        raise CalibrationError("REFERENCE_METHOD_OR_UNITS_MISMATCH")
    return result


def _features(pair: CalibrationPair, names: tuple[str, ...]) -> list[float]:
    values = dict(pair.predictors)
    return [pair.sensor_value, *(values[n] for n in names)]


def _least_squares(rows: list[list[float]], targets: list[float]) -> tuple[float, ...]:
    """Centered/scaled modified Gram-Schmidt QR with reorthogonalization.

    Avoid normal equations (which square the condition number). Numerical rank
    tolerance is relative to normalized columns; near collinearity is rejected.
    """
    n, width = len(rows), len(rows[0])
    centers = [fmean(row[j] for row in rows) for j in range(width)]
    scales = [sqrt(fsum((row[j] - centers[j]) ** 2 for row in rows)) for j in range(width)]
    if any(scale == 0 for scale in scales):
        raise CalibrationError("COLLINEAR_PREDICTORS")
    columns = [[1.0] * n] + [[(row[j] - centers[j]) / scales[j] for row in rows] for j in range(width)]
    q, r = [], [[0.0] * (width + 1) for _ in range(width + 1)]
    for j, column in enumerate(columns):
        residual = column[:]
        for _ in range(2):
            for k, basis in enumerate(q):
                projection = fsum(a * b for a, b in zip(basis, residual))
                r[k][j] += projection
                residual = [a - projection * b for a, b in zip(residual, basis)]
        norm = sqrt(fsum(v * v for v in residual))
        if norm <= 1e-10:
            raise CalibrationError("COLLINEAR_PREDICTORS")
        r[j][j] = norm
        q.append([v / norm for v in residual])
    beta = [fsum(a * b for a, b in zip(column, targets)) for column in q]
    for i in reversed(range(len(beta))):
        beta[i] = (beta[i] - fsum(r[i][j] * beta[j] for j in range(i + 1, len(beta)))) / r[i][i]
    slopes = [beta[j + 1] / scales[j] for j in range(width)]
    coefficients = (beta[0] - fsum(a * b for a, b in zip(slopes, centers)), *slopes)
    if not all(isfinite(v) for v in coefficients):
        raise CalibrationError("NON_FINITE_MODEL")
    return coefficients


def train_candidate(pairs: Sequence[CalibrationPair], *, profile_id: str, version: int,
                    analyte: str, unit: str, scope: CalibrationScope,
                    holdout_group_ids: tuple[str, ...], training_evidence: str,
                    trained_at: datetime, predictor_names: tuple[str, ...] = (),
                    model_kind: str = "linear") -> CalibrationProfile:
    if not profile_id or version < 1 or not training_evidence or trained_at.tzinfo is None:
        raise CalibrationError("INVALID_MODEL_METADATA")
    if model_kind not in {"bias", "linear"} or len(set(predictor_names)) != len(predictor_names) or "sensor_value" in predictor_names:
        raise CalibrationError("INVALID_MODEL_SPECIFICATION")
    if model_kind == "bias" and predictor_names:
        raise CalibrationError("BIAS_MODEL_HAS_PREDICTORS")
    groups = _groups(pairs, analyte, unit, predictor_names, scope)
    holdout = set(holdout_group_ids)
    if len(holdout) != len(holdout_group_ids) or not holdout.issubset({p.sample_group_id for p in groups}):
        raise CalibrationError("INVALID_HOLDOUT_GROUPS")
    training = [p for p in groups if p.sample_group_id not in holdout]
    # At least one residual degree of freedom, and two independent holdout groups.
    parameter_count = 1 if model_kind == "bias" else len(predictor_names) + 2
    if len(training) <= parameter_count or len(holdout) < 2:
        raise CalibrationError("INSUFFICIENT_INDEPENDENT_GROUPS")
    rows = [_features(p, predictor_names) for p in training]
    coefficients = ((fmean(p.reference_value - p.sensor_value for p in training), 1.0)
                    if model_kind == "bias" else _least_squares(rows, [p.reference_value for p in training]))
    names = ("sensor_value", *predictor_names)
    ranges = tuple((name, min(row[j] for row in rows), max(row[j] for row in rows)) for j, name in enumerate(names))
    return CalibrationProfile(profile_id, version, "candidate", analyte, unit,
                              model_kind, predictor_names,
                              tuple((name, dict(groups[0].predictor_units)[name]) for name in predictor_names),
                              coefficients, ranges, scope,
                              tuple(p.sample_group_id for p in training), tuple(sorted(holdout)),
                              _fingerprint(pairs), groups[0].reference_method,
                              groups[0].reference_basis, training_evidence, trained_at,
                              any(p.synthetic for p in groups))


def _predict(profile: CalibrationProfile, features: Sequence[float]) -> float:
    if len(profile.coefficients) != len(features) + 1:
        raise CalibrationError("INVALID_MODEL_COEFFICIENTS")
    value = profile.coefficients[0] + fsum(a * b for a, b in zip(profile.coefficients[1:], features))
    if not isfinite(value):
        raise CalibrationError("NON_FINITE_ESTIMATE")
    return value


def validate_candidate(profile: CalibrationProfile, pairs: Sequence[CalibrationPair], *,
                       validation_evidence: str) -> CalibrationProfile:
    """Recompute held-out errors on stored pairs; never trust submitted metrics."""
    if profile.state != "candidate" or profile.algorithm_version != CALIBRATION_ALGORITHM:
        raise CalibrationError("INVALID_MODEL_STATE_OR_VERSION")
    if not validation_evidence:
        raise CalibrationError("VALIDATION_EVIDENCE_REQUIRED")
    if profile.synthetic or any(p.synthetic for p in pairs):
        raise CalibrationError("SYNTHETIC_PROFILE_CANNOT_BE_VALIDATED")
    groups = _groups(pairs, profile.analyte, profile.unit, profile.predictor_names, profile.scope)
    if _fingerprint(pairs) != profile.dataset_fingerprint:
        raise CalibrationError("CALIBRATION_DATA_CHANGED")
    if set(profile.train_group_ids).intersection(profile.holdout_group_ids):
        raise CalibrationError("VALIDATION_GROUP_LEAKAGE")
    rebuilt = train_candidate(pairs, profile_id=profile.profile_id, version=profile.version,
                              analyte=profile.analyte, unit=profile.unit, scope=profile.scope,
                              holdout_group_ids=profile.holdout_group_ids,
                              training_evidence=profile.training_evidence,
                              trained_at=profile.trained_at, predictor_names=profile.predictor_names,
                              model_kind=profile.model_kind)
    if any(getattr(profile, name) != getattr(rebuilt, name) for name in (
            "coefficients", "feature_ranges", "train_group_ids", "predictor_units",
            "reference_method", "reference_basis")):
        raise CalibrationError("MODEL_TRAINING_MISMATCH")
    held = [p for p in groups if p.sample_group_id in profile.holdout_group_ids]
    if len(held) < 2:
        raise CalibrationError("INSUFFICIENT_INDEPENDENT_GROUPS")
    predicted = [_predict(profile, _features(p, profile.predictor_names)) for p in held]
    references = [p.reference_value for p in held]
    calibrated, baseline = error_metrics(predicted, references), error_metrics([p.sensor_value for p in held], references)
    if calibrated.mae >= baseline.mae or calibrated.rmse >= baseline.rmse:
        raise CalibrationError("NO_INDEPENDENT_IMPROVEMENT")
    # No observed device/parcel/soil subgroup may worsen either error measure.
    for attribute in ("device_id", "parcel_id", "soil_type"):
        for label in {getattr(p, attribute) for p in held} - {None}:
            indices = [i for i, p in enumerate(held) if getattr(p, attribute) == label]
            corrected = error_metrics([predicted[i] for i in indices], [references[i] for i in indices])
            original = error_metrics([held[i].sensor_value for i in indices], [references[i] for i in indices])
            if corrected.mae > original.mae or corrected.rmse > original.rmse:
                raise CalibrationError("SUBGROUP_ERROR_WORSENED")
    return replace(profile, state="validated", validation_evidence=validation_evidence,
                   calibrated_metrics=calibrated, baseline_metrics=baseline)


def apply_profile(profile: CalibrationProfile, *, analyte: str, unit: str,
                  device_id: str, parcel_id: str | None, sensor_value: float,
                  predictors: Mapping[str, float] | None = None,
                  predictor_units: Mapping[str, str] | None = None,
                  soil_type: str | None = None,
                  expected_version: int | None = None,
                  sensor_model: str | None = None, protocol_version: str | None = None,
                  acquisition_profile_id: str | None = None,
                  depth_cm: float | None = None) -> CalibrationEstimate:
    if profile.state != "validated" or profile.synthetic:
        raise CalibrationError("MODEL_NOT_VALIDATED")
    if (profile.algorithm_version != CALIBRATION_ALGORITHM or
            expected_version is not None and profile.version != expected_version):
        raise CalibrationError("MODEL_VERSION_MISMATCH")
    if (analyte, unit) != (profile.analyte, profile.unit):
        raise CalibrationError("INCOMPATIBLE_ANALYTE_OR_UNIT")
    _check_scope(profile.scope, device_id, parcel_id, soil_type,
                 sensor_model, protocol_version, acquisition_profile_id, depth_cm)
    predictors, predictor_units = predictors or {}, predictor_units or {}
    if any(n not in predictors for n in profile.predictor_names):
        raise CalibrationError("MISSING_PREDICTOR")
    if any(predictor_units.get(n) != u for n, u in profile.predictor_units):
        raise CalibrationError("PREDICTOR_UNIT_MISMATCH")
    features = [sensor_value, *(predictors[n] for n in profile.predictor_names)]
    if not all(isfinite(v) for v in features):
        raise CalibrationError("NON_FINITE_CALIBRATION_DATA")
    if len(profile.feature_ranges) != len(features):
        raise CalibrationError("INVALID_MODEL_RANGES")
    if any(not low <= value <= high for value, (_, low, high) in zip(features, profile.feature_ranges)):
        raise CalibrationError("EXTRAPOLATION_NOT_ALLOWED")
    return CalibrationEstimate(_predict(profile, features), profile.profile_id,
                               profile.version, profile.algorithm_version)


def retire_profile(profile: CalibrationProfile) -> CalibrationProfile:
    return replace(profile, state="retired")


def profile_to_dict(profile: CalibrationProfile) -> dict:
    result = asdict(profile)
    result["trained_at"] = profile.trained_at.isoformat()
    return result


def profile_from_dict(data: Mapping) -> CalibrationProfile:
    """Decode trusted persisted server profiles, not client-supplied activation."""
    fields = dict(data)
    fields["trained_at"] = datetime.fromisoformat(fields["trained_at"])
    scope = fields["scope"]
    scope_fields = {key: tuple(value) for key, value in scope.items() if value is not None}
    if "measurement_contexts" in scope_fields:
        scope_fields["measurement_contexts"] = tuple(tuple(row) for row in scope_fields["measurement_contexts"])
    fields["scope"] = CalibrationScope(**scope_fields)
    for key in ("predictor_names", "coefficients", "train_group_ids", "holdout_group_ids"):
        fields[key] = tuple(fields[key])
    for key in ("predictor_units", "feature_ranges"):
        fields[key] = tuple(tuple(row) for row in fields[key])
    for key in ("calibrated_metrics", "baseline_metrics"):
        if fields.get(key) is not None:
            metrics = dict(fields[key])
            metrics["residuals"] = tuple(metrics["residuals"])
            fields[key] = ErrorMetrics(**metrics)
    return CalibrationProfile(**fields)

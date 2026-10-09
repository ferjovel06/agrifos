"""Deterministic synthetic comparison, never agricultural accuracy evidence."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.measurement_processing import (  # noqa: E402
    MeasurementSample, ProcessingConfig, process_measurements, series_metrics,
)


def run(repetitions=500):
    start = datetime(2026, 10, 9, tzinfo=timezone.utc)
    cases = {"same_point_spike": ([15.2, 15.4, 45, 15.5, 15.3], [15.4] * 5),
             "physical_spatial_step": ([10] * 5 + [100] * 5, [10] * 5 + [100] * 5)}
    result = {"evidence": "synthetic software benchmark; no real sensor or laboratory data", "cases": {}}
    for case, (values, reference) in cases.items():
        samples = [MeasurementSample(str(i), "session", "device", "parcel",
                                     "b" if case == "physical_spatial_step" and i >= 5 else "a",
                                     "N", value, "mg/kg", start + timedelta(seconds=i),
                                     start + timedelta(hours=1)) for i, value in enumerate(values)]
        result["cases"][case] = {}
        for method in ("none", "mean", "median"):
            config = ProcessingConfig(method=method)
            before = perf_counter()
            for _ in range(repetitions):
                processed = process_measurements(samples, config)
            duration = (perf_counter() - before) / repetitions
            output = [p.filtered for p in processed]
            result["cases"][case][method] = {"output": output,
                "metrics": series_metrics(output, reference), "mean_seconds_per_batch": duration}
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, allow_nan=False))

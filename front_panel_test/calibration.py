"""Offline DC output fit and first-pass resistor network calculations."""
import math


def fit_transfer(measurements):
    """Fit measured jack voltage against slider fraction (0.0 through 1.0)."""
    points = []
    for percent, volts in measurements:
        percent, volts = float(percent), float(volts)
        if not 0 <= percent <= 100 or not math.isfinite(volts):
            raise ValueError("measurement must have 0..100% and finite voltage")
        points.append((percent / 100.0, volts))
    if len({x for x, _ in points}) < 2:
        raise ValueError("enter at least two distinct preset measurements")
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    denom = sum((x - mean_x) ** 2 for x, _ in points)
    gain = sum((x - mean_x) * (y - mean_y) for x, y in points) / denom
    offset = mean_y - gain * mean_x
    residuals = [y - (offset + gain * x) for x, y in points]
    span = max(y for _, y in points) - min(y for _, y in points)
    max_error = max(abs(r) for r in residuals)
    polarity = "positive" if gain > 1e-9 else "negative" if gain < -1e-9 else "flat"
    return {
        "gain_v_per_100pct": gain,
        "offset_v": offset,
        "polarity": polarity,
        "max_linearity_error_v": max_error,
        "max_linearity_error_pct_span": 100.0 * max_error / span if span > 1e-12 else 0.0,
        "r_squared": 1.0 - sum(r * r for r in residuals) / sum((y - mean_y) ** 2 for _, y in points)
        if sum((y - mean_y) ** 2 for _, y in points) > 1e-12 else 1.0,
    }


def candidate_network(target_span_v=1.0, pwm_high_v=3.3, reference_v=10.0,
                      input_ohms=10_000.0, existing_feedback_ohms=39_000.0,
                      existing_feedback_cap_f=1e-9, reference_series_ohms=4_700.0):
    """Ideal first-pass values for a 0..target-span transfer; not PCB instructions."""
    if target_span_v <= 0 or pwm_high_v <= 0 or reference_v <= 0:
        raise ValueError("voltages must be positive")
    gain = target_span_v / pwm_high_v
    feedback = gain * input_ohms
    reference_total = feedback * reference_v / target_span_v
    return {
        "gain": gain,
        "feedback_ohms": feedback,
        "reference_total_ohms": reference_total,
        "reference_upper_ohms": reference_total - reference_series_ohms,
        "feedback_cap_f": existing_feedback_cap_f * feedback / existing_feedback_ohms,
        "existing_feedback_ohms": existing_feedback_ohms,
    }

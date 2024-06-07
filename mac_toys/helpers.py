

def interpolate_value_unbounded(
        value: float,
        left_min: float, left_max: float,
        right_min: float, right_max: float
) -> float:
    _left_span = left_max - left_min
    _right_span = right_max - right_min

    _scale_factor = float(_right_span) / float(_left_span)
    return right_min + (value-left_min)*_scale_factor


def interpolate_value_bounded(
        value: float,
        left_min: float, left_max: float,
        right_min: float, right_max: float
) -> float:
    return max(right_min, min(right_max, interpolate_value_unbounded(
        value, left_min, left_max, right_min, right_max
    )))

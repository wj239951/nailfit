"""肤色量化：sRGB → CIE Lab → ITA°。

ITA°（Individual Typology Angle）是皮肤科常用的肤色深浅指标，
比 VLM 的"看起来偏暖"可复现得多：

    ITA° = arctan((L* - 50) / b*) × 180 / π

分段（常用近似）：> 41 浅，10 ~ 41 中等，< 10 深。

前提：**必须先做白平衡**，否则同一只手在不同光线下能差十几度。
"""

from __future__ import annotations

import math

# D65 白点
WHITE = (0.95047, 1.0, 1.08883)


def _srgb_to_linear(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def srgb_to_xyz(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(v) for v in rgb)
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    return x, y, z


def _f(t: float) -> float:
    return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29


def srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    x, y, z = srgb_to_xyz(rgb)
    fx, fy, fz = _f(x / WHITE[0]), _f(y / WHITE[1]), _f(z / WHITE[2])
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ita_degrees(lab: tuple[float, float, float]) -> float:
    """b* 接近 0 时按极小值处理，避免除零。"""
    lightness, _, b = lab
    b = b if abs(b) > 1e-6 else 1e-6
    return math.degrees(math.atan2(lightness - 50.0, b))


def ita_band(ita: float) -> str:
    if ita > 41:
        return "light"
    if ita >= 10:
        return "mid"
    return "deep"


def warmth_from_lab(lab: tuple[float, float, float]) -> str:
    """冷暖倾向的粗略代理：黄（b*）相对红（a*）越高越暖。

    经验阈值，**必须用真实数据标定**，不要当成色卡测量结果。
    """
    _, a, b = lab
    score = b - a
    if score > 3:
        return "warm"
    if score < -1:
        return "cool"
    return "neutral"

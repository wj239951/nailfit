"""从 21 个 MediaPipe 手部关键点估算几何特征（启发式）。

关键点里**没有指甲游离缘**，所以当前甲长必须由外部传入（分割模型或用户选择），
这里只估算甲床比例与手型。

阈值需要用真实数据标定，不要当成精确测量。真实项目应换成
"指甲分割 mask + 甲床长宽比"，本文件的价值是让全链路先跑起来。
"""

from __future__ import annotations

import math

from .color import ita_band, ita_degrees, srgb_to_lab, warmth_from_lab
from .features import HandFeatures

Point = tuple[float, float]

# MediaPipe Hands 21 点索引（部分）
WRIST = 0
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
PINKY_MCP = 17


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _bed_ratio(landmarks: list[Point]) -> str:
    """中指远节 / 中指全长 —— 甲床比例的粗糙代理。"""
    distal = _dist(landmarks[MIDDLE_DIP], landmarks[MIDDLE_TIP])
    full = _dist(landmarks[MIDDLE_MCP], landmarks[MIDDLE_TIP])
    ratio = distal / full if full else 0.5
    if ratio < 0.45:
        return "short_wide"
    if ratio > 0.55:
        return "slender"
    return "standard"


def _hand_type(landmarks: list[Point]) -> str:
    """食指长度 / 掌宽 —— 手指纤细度的粗糙代理。"""
    finger = _dist(landmarks[INDEX_MCP], landmarks[INDEX_TIP])
    palm = _dist(landmarks[INDEX_MCP], landmarks[PINKY_MCP])
    ratio = finger / palm if palm else 1.0
    if ratio > 3.0:
        return "slim"
    if ratio < 2.4:
        return "fleshy"
    return "standard"


def features_from_landmarks(
    landmarks: list[Point],
    *,
    length: str = "short",
    skin_rgb: tuple[int, int, int] | None = None,
    scene: str = "commute",
    nail_shape: str = "oval",
) -> HandFeatures:
    """把关键点 + 可选肤色采样转成 HandFeatures。"""
    if len(landmarks) < 21:
        raise ValueError("需要 21 个 MediaPipe 手部关键点")

    payload: dict = {
        "nail_bed_ratio": _bed_ratio(landmarks),
        "hand_type": _hand_type(landmarks),
        "length": length,
        "scene": scene,
        "nail_shape": nail_shape,
    }

    if skin_rgb is not None:
        lab = srgb_to_lab(skin_rgb)
        ita = ita_degrees(lab)
        payload["ita_degrees"] = round(ita, 1)
        payload["ita_band"] = ita_band(ita)
        payload["warmth"] = warmth_from_lab(lab)

    return HandFeatures.from_dict(payload)

"""HandFeatures：手部特征的数据契约。

这一层是"输入侧"的唯一定义。视觉层（MediaPipe / 分割模型）负责把照片变成
这些字段；规则引擎只认这些字段，不关心照片。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from .data import load_taxonomy


class FeatureError(ValueError):
    """特征值非法。"""


@dataclass(frozen=True)
class HandFeatures:
    nail_bed_ratio: str = "standard"   # short_wide / standard / slender
    nail_shape: str = "oval"           # round / square / oval / almond / squoval
    length: str = "short"              # very_short / short / mid / long
    ita_band: str = "mid"              # light / mid / deep
    warmth: str = "neutral"            # cool / neutral / warm
    hand_type: str = "standard"        # slim / standard / fleshy
    scene: str = "commute"             # commute / date / wedding / festival / cool / y2k
    ita_degrees: float | None = None   # 原始 ITA°，用于展示与调试

    def validate(self) -> "HandFeatures":
        enums = load_taxonomy()["features"]
        for f in fields(self):
            if f.name == "ita_degrees":
                continue
            value = getattr(self, f.name)
            allowed = enums.get(f.name, [])
            if allowed and value not in allowed:
                raise FeatureError(f"{f.name}={value!r} 不在允许取值 {allowed} 中")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HandFeatures":
        if not isinstance(payload, dict):
            raise FeatureError("features 必须是字典")
        allowed = {f.name for f in fields(cls)}
        unknown = set(payload) - allowed
        if unknown:
            raise FeatureError(f"未知特征字段: {sorted(unknown)}")
        return cls(**payload).validate()

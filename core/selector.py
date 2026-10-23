"""三选一：排序 + 三档（稳妥/亮点/大胆）+ 多样性约束。

按分数直接取 top3 会得到三条同色系。这里强制：
- 三个结果色相间隔 >= min_hue_gap（圆形距离，处理 355°/25° 这种跨界）
- 三个结果 color_family 不重复
- 优先覆盖 safe / highlight / bold 三档
若候选不足，逐级放宽约束，保证永远返回 3 条（除非款式库本身不足）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .features import HandFeatures
from .rules import Rule, RuleEngine


@dataclass(frozen=True)
class Scored:
    style: dict
    score: float
    reasons: tuple[str, ...]
    rule_ids: tuple[str, ...] = ()


def _hue_gap(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def rank(engine: RuleEngine, styles: list[dict], features: HandFeatures) -> list[Scored]:
    matched = engine.match(features)
    scored = []
    for style in styles:
        score, reasons, rule_ids = engine.score(style, matched)
        scored.append(
            Scored(
                style=style,
                score=score,
                reasons=tuple(reasons),
                rule_ids=tuple(rule_ids),
            )
        )
    return sorted(scored, key=lambda x: (-x.score, x.style["id"]))


def pick_three(ranked: list[Scored], taxonomy: dict, features: HandFeatures) -> list[Scored]:
    tiers: dict[str, list[str]] = taxonomy.get("tiers", {})
    diversity: dict = taxonomy.get("diversity", {})
    min_gap = float(diversity.get("min_hue_gap", 0))
    forbid_same_family = bool(diversity.get("forbid_same_color_family", True))

    chosen: list[Scored] = []

    def acceptable(candidate: Scored) -> bool:
        for picked in chosen:
            if forbid_same_family and candidate.style.get("color_family") == picked.style.get("color_family"):
                return False
            if _hue_gap(float(candidate.style.get("hue", 0)), float(picked.style.get("hue", 0))) < min_gap:
                return False
        return True

    def taken(candidate: Scored) -> bool:
        return any(candidate.style["id"] == x.style["id"] for x in chosen)

    # 1) 每档取一个"场景命中"的最高分
    for tier_scenes in tiers.values():
        for candidate in ranked:
            if taken(candidate):
                continue
            if set(tier_scenes) & set(candidate.style.get("scene", [])) and acceptable(candidate):
                chosen.append(candidate)
                break

    # 2) 补足：仅受多样性约束
    for candidate in ranked:
        if len(chosen) >= 3:
            break
        if not taken(candidate) and acceptable(candidate):
            chosen.append(candidate)

    # 3) 仍不足：放宽色相间隔，但 color_family 必须不重复（校验层硬要求）
    for candidate in ranked:
        if len(chosen) >= 3:
            break
        if taken(candidate):
            continue
        if forbid_same_family and any(
            candidate.style.get("color_family") == picked.style.get("color_family")
            for picked in chosen
        ):
            continue
        chosen.append(candidate)

    return chosen[:3]

"""规则引擎：when / prefer / block。

设计要点：
- 规则是数据（data/rules.yaml），不是代码；
- 硬过滤（block + 甲长兼容）与加权打分分开，保证"不可行"永远不会出现在结果里；
- 每条命中规则都带 reason，供解释层直接引用，保证推荐可溯源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .data import load_rules, load_taxonomy
from .features import HandFeatures

# 特征字段名 → 款式字段名
FIELD_ALIASES = {"nail_shape": "shape"}


@dataclass(frozen=True)
class Rule:
    id: str
    weight: float
    reason: str
    when: dict[str, Any]
    prefer: dict[str, list[str]] = field(default_factory=dict)
    block: dict[str, list[str]] = field(default_factory=dict)

    def applies(self, features: HandFeatures) -> bool:
        values = features.to_dict()
        return all(values.get(k) == v for k, v in self.when.items())


def _style_values(style: dict, key: str) -> list[str]:
    raw = style.get(FIELD_ALIASES.get(key, key))
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(v) for v in raw]
    return [str(raw)]


def _matches(style: dict, constraints: dict[str, list[str]]) -> list[str]:
    """返回命中的字段名列表。"""
    return [k for k, allowed in constraints.items() if set(_style_values(style, k)) & set(allowed)]


def length_compatible(style: dict, features: HandFeatures, taxonomy: dict) -> bool:
    order: list[str] = taxonomy["length_order"]
    req = style.get("length_fit", "short")
    if req not in order or features.length not in order:
        return False
    if features.length == "very_short":
        # 极短甲仍可做"短甲友好"的款式，但不能做中/长甲款式
        return order.index(req) <= order.index("short")
    return order.index(features.length) >= order.index(req)


class RuleEngine:
    def __init__(self, taxonomy: dict | None = None, rules: dict | None = None):
        self.taxonomy = taxonomy or load_taxonomy()
        raw_rules = (rules or load_rules()).get("rules", [])
        self.rules: list[Rule] = [
            Rule(
                id=r["id"],
                weight=float(r.get("weight", 1.0)),
                reason=r.get("reason", ""),
                when=r.get("when", {}),
                prefer={k: list(v) for k, v in (r.get("prefer") or {}).items()},
                block={k: list(v) for k, v in (r.get("block") or {}).items()},
            )
            for r in raw_rules
        ]

    def match(self, features: HandFeatures) -> list[Rule]:
        return [r for r in self.rules if r.applies(features)]

    def filter_styles(
        self, styles: tuple[dict, ...] | list[dict], features: HandFeatures
    ) -> tuple[list[dict], list[dict]]:
        """返回 (可用款式, 被排除的款式及原因)。"""
        matched = self.match(features)
        kept: list[dict] = []
        avoided: list[dict] = []

        for style in styles:
            name = style.get("name", style.get("id"))

            if not length_compatible(style, features, self.taxonomy):
                avoided.append(
                    {
                        "style_id": style["id"],
                        "name": name,
                        "reason": f"该款式需要 {style.get('length_fit')} 甲长，与当前甲长不匹配",
                    }
                )
                continue

            hit_blocks: list[str] = []
            for rule in matched:
                if rule.block and _matches(style, rule.block):
                    hit_blocks.append(rule.reason)
            if hit_blocks:
                avoided.append(
                    {"style_id": style["id"], "name": name, "reason": "；".join(hit_blocks)}
                )
                continue

            kept.append(style)

        return kept, avoided

    def score(self, style: dict, matched: list[Rule]) -> tuple[float, list[str], list[str]]:
        """基础分 + 命中规则的加权贡献。

        返回 (原始分, 命中规则原因, 命中规则 id)，三者顺序与 matched 一致。
        """
        total = float(self.taxonomy["scoring"].get("base", 1.0))
        reasons: list[str] = []
        rule_ids: list[str] = []
        for rule in matched:
            if not rule.prefer:
                continue
            hits = _matches(style, rule.prefer)
            if hits:
                total += rule.weight * len(hits) / len(rule.prefer)
                rule_ids.append(rule.id)
                if rule.reason:
                    reasons.append(rule.reason)
        return total, reasons, rule_ids

    def max_score(self, matched: list[Rule]) -> float:
        """归一化用：base + 所有命中规则权重之和。"""
        return float(self.taxonomy["scoring"].get("base", 1.0)) + sum(r.weight for r in matched)


def normalize(score: float, max_score: float) -> float:
    if max_score <= 0:
        return 0.0
    return round(min(1.0, score / max_score), 3)

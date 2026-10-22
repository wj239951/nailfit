"""输出契约校验：模型可以"说错话"，但不能"编款式"。

校验项：
- 必须正好 3 条
- style_id 必须存在于款式库（防幻觉）
- style_id 不重复
- 三个 color_family 不重复（多样性）
- reason 非空且不过长
任何一项失败都抛 ContractError，由上层决定重试或降级。
"""

from __future__ import annotations

MAX_REASON_CHARS = 160


class ContractError(ValueError):
    """推荐结果不满足输出契约。"""


def validate_cards(cards: list[dict], style_ids: set[str], taxonomy: dict) -> None:
    if len(cards) != 3:
        raise ContractError(f"必须返回 3 条推荐，实际 {len(cards)} 条")

    seen: set[str] = set()
    families: set[str] = set()
    for card in cards:
        sid = card.get("style_id")
        if sid not in style_ids:
            raise ContractError(f"style_id={sid!r} 不在款式库中（疑似模型编造）")
        if sid in seen:
            raise ContractError(f"style_id 重复: {sid}")
        seen.add(sid)

        family = card.get("color_family")
        if family in families:
            raise ContractError(f"三条推荐的色系重复: {family}")
        families.add(family)

        reason = (card.get("reason") or "").strip()
        if not reason:
            raise ContractError(f"{sid} 缺少推荐理由")
        if len(reason) > MAX_REASON_CHARS:
            raise ContractError(f"{sid} 理由过长（{len(reason)} 字），前端展示会截断")

    if not taxonomy.get("diversity", {}).get("forbid_same_color_family", True):
        return

from __future__ import annotations

import pytest

from core.data import load_taxonomy
from core.validator import ContractError, validate_cards


def _card(style_id: str, family: str, reason: str = "适合你的甲型") -> dict:
    return {"style_id": style_id, "color_family": family, "reason": reason}


def test_valid_cards_pass() -> None:
    cards = [_card("a", "f1"), _card("b", "f2"), _card("c", "f3")]
    validate_cards(cards, {"a", "b", "c"}, load_taxonomy())


def test_unknown_style_id_rejected() -> None:
    cards = [_card("a", "f1"), _card("ghost", "f2"), _card("c", "f3")]
    with pytest.raises(ContractError, match="不在款式库"):
        validate_cards(cards, {"a", "b", "c"}, load_taxonomy())


def test_wrong_count_rejected() -> None:
    with pytest.raises(ContractError, match="3 条"):
        validate_cards([_card("a", "f1")], {"a"}, load_taxonomy())


def test_duplicate_color_family_rejected() -> None:
    cards = [_card("a", "f1"), _card("b", "f1"), _card("c", "f3")]
    with pytest.raises(ContractError, match="色系重复"):
        validate_cards(cards, {"a", "b", "c"}, load_taxonomy())


def test_empty_reason_rejected() -> None:
    cards = [_card("a", "f1"), _card("b", "f2", reason="  "), _card("c", "f3")]
    with pytest.raises(ContractError, match="缺少推荐理由"):
        validate_cards(cards, {"a", "b", "c"}, load_taxonomy())

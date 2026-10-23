from __future__ import annotations

import pytest

from scripts.manual import (
    FEATURE_FIELDS,
    ask_choice,
    build_parser,
    features_from_args,
    main,
)


def parse(argv: list[str]):
    return build_parser().parse_args(argv)


def test_defaults_when_non_interactive() -> None:
    features = features_from_args(parse(["--yes"]))
    values = features.to_dict()
    assert values["nail_bed_ratio"] == "standard"
    assert values["length"] == "short"
    assert values["scene"] == "commute"
    assert set(FEATURE_FIELDS) <= set(values)


def test_flags_override_defaults() -> None:
    features = features_from_args(
        parse(
            [
                "--bed",
                "short_wide",
                "--length",
                "short",
                "--ita",
                "light",
                "--warmth",
                "warm",
                "--hand",
                "fleshy",
                "--scene",
                "commute",
            ]
        )
    )
    values = features.to_dict()
    assert values["nail_bed_ratio"] == "short_wide"
    assert values["hand_type"] == "fleshy"


def test_scenario_fills_all_fields() -> None:
    features = features_from_args(parse(["--scenario", "deep_festival"]))
    values = features.to_dict()
    assert values["ita_band"] == "deep"
    assert values["scene"] == "festival"


def test_invalid_flag_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit):
        parse(["--bed", "eternal"])


def test_ask_choice_default(monkeypatch, capsys) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert ask_choice("length", ["very_short", "short", "mid", "long"], "short") == "short"


def test_ask_choice_by_index(monkeypatch, capsys) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "3")
    assert ask_choice("length", ["very_short", "short", "mid", "long"], "short") == "mid"


def test_main_json_output(capsys) -> None:
    code = main(["--yes", "--json"])
    output = capsys.readouterr().out
    assert code == 0
    assert '"recommendations"' in output
    assert '"features"' in output

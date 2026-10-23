"""M18 评测脚本：批量跑用例，量化「推荐得对不对」。

五个维度（都可复现、不依赖大模型）：
1. 契约 contract  —— 3 条推荐、id 存在、color_family 不重复、reason 非空且 <=160 字、tier 合法
2. 合理性 fit     —— 每条推荐的 tone / value / shape 与人工期望一致（硬约束）
3. 多样性 diversity—— 三档覆盖数、色相圆形间隔 >= min_hue_gap、色系不重复
4. 稳定性 stability—— 重复运行 top-1 一致率；单特征轻微抖动时 top-1 变化率
5. 降级率 degrade —— 可选 --llm：LLM 有效条数、降级率、平均耗时
6. 视觉层 vision  —— 可选 --vision：手照自动特征 vs 人工标注的检测率/准确率（M19）

用法：
    python eval/run.py                     # 跑 eval/cases.json，3 次重复
    python eval/run.py --llm --llm-cases 3 # 同时量解释层（DeepSeek，读 .env）
    python eval/run.py --vision            # 额外量手照视觉层（需要本地 mediapipe 模型）
    python eval/run.py --strict            # 合理性低于阈值返回非 0（CI 用）

输出：
    控制台逐用例结果 + 汇总指标；
    eval/reports/eval-<时间戳>.json（--no-report 关闭，--json 指定路径）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.data import load_styles, load_taxonomy  # noqa: E402
from core.features import HandFeatures  # noqa: E402
from core.pipeline import recommend  # noqa: E402
from core.selector import _hue_gap  # noqa: E402
from core.validator import MAX_REASON_CHARS  # noqa: E402

DEFAULT_CASES = ROOT / "eval" / "cases.json"
DEFAULT_REPORT_DIR = ROOT / "eval" / "reports"

# 抖动：按 taxonomy 顺序把单个特征往相邻档挪一档，看 top-1 会不会变
JITTER_FIELDS = (
    "length",
    "nail_shape",
    "nail_bed_ratio",
    "ita_band",
    "warmth",
    "hand_type",
)

# 视觉层（M19）：手照用例的自动特征与人工标注对比
VISION_SKIN_FIELDS = ("ita_band", "warmth")
VISION_GEOMETRY_FIELDS = ("hand_type", "nail_bed_ratio", "nail_shape", "length")
VISION_FIELDS = VISION_SKIN_FIELDS + VISION_GEOMETRY_FIELDS


def _log(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- #
# 用例与基础设施
# --------------------------------------------------------------------------- #


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    """读取并校验用例文件。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = raw.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"用例文件没有 cases：{path}")
    seen: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id or case_id in seen:
            raise ValueError(f"用例 id 缺失或重复：{case_id!r}")
        seen.add(case_id)
        HandFeatures.from_dict(case["features"])  # 非法取值直接抛 FeatureError
        expect = case.get("expect") or {}
        for key in ("tone", "value", "shape", "length_fit"):
            if key in expect and not isinstance(expect[key], list):
                raise ValueError(f"{case_id} 的 expect.{key} 必须是列表")
        source = case.get("source", "manual")
        if source not in {"manual", "hand_photo"}:
            raise ValueError(f"{case_id} 的 source 非法：{source!r}")
        if source == "hand_photo" and not case.get("image"):
            raise ValueError(f"{case_id} 是 hand_photo 用例但没有 image")
    return cases


def styles_index(styles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {style["id"]: style for style in styles}


def _as_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(result.get("recommendations") or [])


def _card_style(rec: dict[str, Any], style_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return style_map.get(str(rec.get("style_id", "")), {})


# --------------------------------------------------------------------------- #
# 1. 契约
# --------------------------------------------------------------------------- #


def check_contract(recs: list[dict[str, Any]], style_map: dict[str, dict[str, Any]], taxonomy: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if len(recs) != 3:
        issues.append(f"推荐条数不是 3：{len(recs)}")
    ids = [str(rec.get("style_id", "")) for rec in recs]
    if len(set(ids)) != len(ids):
        issues.append(f"style_id 重复：{ids}")
    for style_id in ids:
        if style_id not in style_map:
            issues.append(f"style_id 不存在：{style_id}")
    families = [str(rec.get("color_family", "")) for rec in recs]
    if len(set(families)) != len(families):
        issues.append(f"color_family 重复：{families}")
    # pipeline 会额外产出 "extra"（无档位场景命中）与 "fill"（同档位第二张），
    # 它们不是错误，而是候选/多样性约束下的降级标记。
    valid_tiers = set(taxonomy.get("tiers", {})) | {"extra", "fill"}
    for rec in recs:
        reason = rec.get("reason") or ""
        if not reason.strip():
            issues.append(f"{rec.get('style_id')} reason 为空")
        elif len(reason) > MAX_REASON_CHARS:
            issues.append(f"{rec.get('style_id')} reason 超长 {len(reason)}")
        if rec.get("tier") not in valid_tiers:
            issues.append(f"{rec.get('style_id')} tier 非法：{rec.get('tier')}")
    return issues


# --------------------------------------------------------------------------- #
# 2. 合理性
# --------------------------------------------------------------------------- #


def check_fit(
    rec: dict[str, Any],
    style: dict[str, Any],
    expect: dict[str, Any],
    features: HandFeatures,
) -> list[str]:
    """硬约束：tone / value / shape / 禁止项。

    档位语义：safe 卡是主推荐，必须严格符合期望；highlight / bold 是刻意的
    第二、三选择（要有一点跳脱），只受禁止项约束。期望里可用 strict_tiers 改默认值。
    场景算软指标（返回在 evaluate_case 里单算）。
    """
    issues: list[str] = []
    strict_tiers = set(expect.get("strict_tiers") or ["safe"])
    strict = rec.get("tier") in strict_tiers
    tone = style.get("tone")
    value = style.get("value")
    shape = style.get("shape") or []
    allowed_tones = expect.get("tone")
    allowed_values = expect.get("value")
    allowed_shapes = expect.get("shape")

    if strict:
        if allowed_tones and tone not in allowed_tones:
            issues.append(f"tone={tone} 不在期望 {allowed_tones}")
        if allowed_values and value not in allowed_values:
            issues.append(f"value={value} 不在期望 {allowed_values}")
        if expect.get("length_fit"):
            if style.get("length_fit") not in expect["length_fit"]:
                issues.append(f"length_fit={style.get('length_fit')} 不在期望")
        if allowed_shapes and not set(shape) & set(allowed_shapes):
            issues.append(f"shape={shape} 与期望 {allowed_shapes} 无交集")
    if style.get("color_family") in set(expect.get("forbid_families", [])):
        issues.append(f"color_family={style.get('color_family')} 在禁止项")
    if style.get("style") in set(expect.get("forbid_styles", [])):
        issues.append(f"style={style.get('style')} 在禁止项")
    return issues


def check_scene(style: dict[str, Any], features: HandFeatures) -> bool:
    scenes = style.get("scene") or []
    return not scenes or features.scene in scenes


# --------------------------------------------------------------------------- #
# 2.5 视觉层（M19）：手照自动特征 vs 人工标注
# --------------------------------------------------------------------------- #


def _default_vision_extract(image_path: Path) -> Any:
    """真实视觉层（延迟导入：评测主体不依赖 mediapipe / 模型）。"""
    from core import vision

    return vision.extract(image_path, auto_download=False, preview=False)


def check_vision(
    cases: list[dict[str, Any]],
    *,
    root: Path = ROOT,
    extract: Any = None,
) -> dict[str, Any]:
    """跑手照用例，量视觉层的检测率与特征准确率。

    只统计「视觉层实际给出的字段」：肤色任何质量都会给；手型/甲床/甲型/
    甲长只在质量达标时给，所以几何准确率的分母会小于肤色。
    """
    extractor = extract or _default_vision_extract
    per_case: list[dict[str, Any]] = []
    field_total: dict[str, int] = {field: 0 for field in VISION_FIELDS}
    field_hit: dict[str, int] = {field: 0 for field in VISION_FIELDS}
    detected = 0
    checked = 0
    for case in cases:
        if case.get("source") != "hand_photo":
            continue
        checked += 1
        entry: dict[str, Any] = {
            "id": case["id"],
            "name": case.get("name", ""),
            "image": case.get("image", ""),
            "expected": {field: case["features"].get(field) for field in VISION_FIELDS},
            "detected": False,
            "quality": "",
            "matches": {},
        }
        try:
            result = extractor(root / str(case.get("image", "")))
        except Exception as exc:  # noqa: BLE001 - 单张失败不中断评测
            entry["error"] = str(exc)
            per_case.append(entry)
            continue
        detected += 1
        entry["detected"] = True
        entry["quality"] = str(getattr(result, "quality", ""))
        auto = dict(getattr(result, "features", {}) or {})
        entry["auto"] = {field: auto.get(field) for field in VISION_FIELDS}
        for field in VISION_FIELDS:
            if field not in auto:
                continue
            hit = auto.get(field) == case["features"].get(field)
            entry["matches"][field] = hit
            field_total[field] += 1
            field_hit[field] += int(hit)
        per_case.append(entry)

    accuracy = {
        field: round(field_hit[field] / field_total[field], 3)
        for field in VISION_FIELDS
        if field_total[field]
    }
    return {
        "cases": checked,
        "detected": detected,
        "detection_rate": round(detected / checked, 3) if checked else 0.0,
        "accuracy": accuracy,
        "per_case": per_case,
    }


# --------------------------------------------------------------------------- #
# 3. 多样性
# --------------------------------------------------------------------------- #


def hue_spread(recs: list[dict[str, Any]], style_map: dict[str, dict[str, Any]]) -> float:
    """三张卡两两色相圆形间隔的最小值；无 hue 字段时返回 0。"""
    hues = []
    for rec in recs:
        style = _card_style(rec, style_map)
        if "hue" in style:
            hues.append(float(style["hue"]))
    if len(hues) < 2:
        return 0.0
    gaps = [_hue_gap(a, b) for i, a in enumerate(hues) for b in hues[i + 1 :]]
    return round(min(gaps), 2)


def tier_coverage(recs: list[dict[str, Any]]) -> int:
    return len({str(rec.get("tier", "")) for rec in recs})


# --------------------------------------------------------------------------- #
# 4. 稳定性
# --------------------------------------------------------------------------- #


def _top1(result: dict[str, Any]) -> str:
    recs = _as_records(result)
    return str(recs[0].get("style_id", "")) if recs else ""


def _jitter_feature(
    features: HandFeatures, field: str, taxonomy: dict[str, Any]
) -> HandFeatures | None:
    """把单个特征挪一档；到边界就反向挪；无法挪返回 None。"""
    options = list(taxonomy.get("features", {}).get(field) or [])
    current = getattr(features, field)
    if len(options) < 2 or current not in options:
        return None
    index = options.index(current)
    next_index = index + 1 if index + 1 < len(options) else index - 1
    payload = features.to_dict()
    payload[field] = options[next_index]
    return HandFeatures.from_dict(payload)


def jitter_change_rate(
    features: HandFeatures,
    taxonomy: dict[str, Any],
    styles: list[dict[str, Any]],
    baseline_top1: str,
) -> float:
    moved: list[int] = []
    for field in JITTER_FIELDS:
        variant = _jitter_feature(features, field, taxonomy)
        if variant is None:
            continue
        try:
            result = recommend(variant, use_llm=False, styles=styles)
        except Exception:  # 抖动后候选不足等异常视为变化
            moved.append(1)
            continue
        moved.append(0 if _top1(result) == baseline_top1 else 1)
    return round(sum(moved) / len(moved), 3) if moved else 0.0


# --------------------------------------------------------------------------- #
# 5. 单用例 / 全量评测
# --------------------------------------------------------------------------- #


def evaluate_case(
    case: dict[str, Any],
    styles: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    style_map: dict[str, dict[str, Any]],
    *,
    runs: int,
) -> dict[str, Any]:
    features = HandFeatures.from_dict(case["features"])
    expect = case.get("expect") or {}
    try:
        result = recommend(features, use_llm=False, styles=styles)
    except Exception as exc:  # noqa: BLE001 - 推荐失败也是一条评测结果，不能中断全量
        message = f"推荐失败：{exc}"
        return {
            "id": case["id"],
            "name": case.get("name", ""),
            "top1": "",
            "ids": [],
            "contract_ok": False,
            "contract_issues": [message],
            "fit_ok": False,
            "fit_issues": [message],
            "scene_hit_rate": 0.0,
            "tier_coverage": 0,
            "safe_cards": 0,
            "fill_cards": 0,
            "known_gap": case.get("known_gap") or "",
            "hue_spread": 0.0,
            "hue_ok": False,
            "stability": 0.0,
            "jitter_change_rate": 0.0,
            "error": str(exc),
        }
    recs = _as_records(result)

    contract_issues = check_contract(recs, style_map, taxonomy)
    fit_issues: list[str] = []
    scene_hits = 0
    for rec in recs:
        style = _card_style(rec, style_map)
        fit_issues.extend(check_fit(rec, style, expect, features))
        scene_hits += 1 if check_scene(style, features) else 0
    safe_cards = sum(1 for rec in recs if rec.get("tier") == "safe")
    if safe_cards == 0:
        fit_issues.append("没有 safe 档主推荐")

    # 已知缺口：把「评测发现的规则层缺陷」和「新回归」分开统计——
    # 缺口用例不计入 fit_pass_rate，但缺口是否还失败单独报出来，修好即归零。
    known_gap = case.get("known_gap")

    spread = hue_spread(recs, style_map)
    min_gap = float(taxonomy.get("diversity", {}).get("min_hue_gap", 0))
    top1 = _top1(result)

    # 重复运行：top-1 一致率
    repeats = 0
    for _ in range(max(0, runs - 1)):
        again = recommend(features, use_llm=False, styles=styles)
        repeats += 1 if _top1(again) == top1 else 0
    stability = round((1 + repeats) / runs, 3) if runs > 0 else 0.0

    jitter = jitter_change_rate(features, taxonomy, styles, top1)

    return {
        "id": case["id"],
        "name": case.get("name", ""),
        "top1": top1,
        "ids": [str(rec.get("style_id", "")) for rec in recs],
        "contract_ok": not contract_issues,
        "contract_issues": contract_issues,
        "fit_ok": not fit_issues,
        "fit_issues": fit_issues,
        "scene_hit_rate": round(scene_hits / len(recs), 3) if recs else 0.0,
        "tier_coverage": tier_coverage(recs),
        "safe_cards": safe_cards,
        "fill_cards": sum(1 for rec in recs if rec.get("tier") == "fill"),
        "known_gap": known_gap or "",
        "hue_spread": spread,
        "hue_ok": spread >= min_gap if len(recs) >= 2 else False,
        "stability": stability,
        "jitter_change_rate": jitter,
    }


def _llm_metrics(
    cases: list[dict[str, Any]],
    styles: list[dict[str, Any]],
    style_map: dict[str, dict[str, Any]],
    taxonomy: dict[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    """解释层指标：只看量化项，不评判文笔。"""
    picked = cases[: max(1, limit)]
    latencies: list[float] = []
    valid_cards = 0
    total_cards = 0
    degraded = 0
    errors: list[str] = []
    for case in picked:
        features = HandFeatures.from_dict(case["features"])
        started = time.perf_counter()
        try:
            result = recommend(features, use_llm=True, styles=styles)
        except Exception as exc:  # noqa: BLE001 - 评测不中断
            errors.append(f"{case['id']}: {exc}")
            continue
        latencies.append((time.perf_counter() - started) * 1000)
        meta = (result.get("meta") or {}).get("explainer") or {}
        if meta.get("degraded"):
            degraded += 1
        recs = _as_records(result)
        valid_cards += int(meta.get("llm_cards") or 0)
        total_cards += len(recs)
        if check_contract(recs, style_map, taxonomy):
            errors.append(f"{case['id']}: 解释后契约不通过")
    return {
        "cases": len(picked),
        "valid_rate": round(valid_cards / total_cards, 3) if total_cards else 0.0,
        "degraded_cases": degraded,
        "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "errors": errors,
    }


def evaluate(
    cases: list[dict[str, Any]],
    styles: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    *,
    runs: int = 3,
    llm: bool = False,
    llm_cases: int = 3,
    vision: bool = False,
) -> dict[str, Any]:
    style_map = styles_index(styles)
    case_results = [
        evaluate_case(case, styles, taxonomy, style_map, runs=runs) for case in cases
    ]
    total = len(case_results)
    gap_cases = [item for item in case_results if item["known_gap"]]
    scored_cases = [item for item in case_results if not item["known_gap"]]
    scored_total = len(scored_cases) or 1
    summary = {
        "cases": total,
        "contract_pass_rate": round(sum(1 for item in case_results if item["contract_ok"]) / total, 3),
        "fit_pass_rate": round(sum(1 for item in scored_cases if item["fit_ok"]) / scored_total, 3),
        "scene_fit_rate": round(sum(item["scene_hit_rate"] for item in case_results) / total, 3),
        "diversity_rate": round(sum(1 for item in case_results if item["hue_ok"]) / total, 3),
        "avg_tier_coverage": round(
            sum(item["tier_coverage"] for item in case_results) / total, 2
        ),
        "avg_stability": round(sum(item["stability"] for item in case_results) / total, 3),
        "avg_jitter_change_rate": round(
            sum(item["jitter_change_rate"] for item in case_results) / total, 3
        ),
        "known_gap_cases": len(gap_cases),
        "known_gap_failing": sum(1 for item in gap_cases if not item["fit_ok"]),
        "hand_photo_cases": sum(1 for case in cases if case.get("source") == "hand_photo"),
    }
    report: dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "runs": runs,
            "library_size": len(styles),
            "min_hue_gap": float(taxonomy.get("diversity", {}).get("min_hue_gap", 0)),
        },
        "summary": summary,
        "cases": case_results,
    }
    if llm:
        report["llm"] = _llm_metrics(cases, styles, style_map, taxonomy, limit=llm_cases)
    if vision:
        report["vision"] = check_vision(cases)
    return report


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    _log("=" * 68)
    _log(f"NailFit 评测 · {report['meta']['generated_at']} · 用例 {summary['cases']} · 款式库 {report['meta']['library_size']}")
    _log("=" * 68)
    for item in report["cases"]:
        flag = "✓" if (item["contract_ok"] and item["fit_ok"]) else ("△" if item["known_gap"] else "✗")
        extra = []
        if not item["contract_ok"]:
            extra.append("契约:" + "; ".join(item["contract_issues"]))
        if not item["fit_ok"]:
            extra.append("合理:" + "; ".join(item["fit_issues"]))
        if item["known_gap"]:
            extra.append("已知缺口:" + item["known_gap"])
        _log(
            f"{flag} {item['id']:<4} {item['name'][:14]:<16} top1={item['top1']} "
            f"稳定={item['stability']:.2f} 抖动={item['jitter_change_rate']:.2f} "
            f"色相={item['hue_spread']:.0f} 档位={item['tier_coverage']}"
            + (f"  [{'; '.join(extra)}]" if extra else "")
        )
    _log("-" * 68)
    _log(
        f"契约通过 {summary['contract_pass_rate']:.0%} · 合理性通过 {summary['fit_pass_rate']:.0%} · "
        f"场景命中 {summary['scene_fit_rate']:.0%} · 多样性 {summary['diversity_rate']:.0%}"
    )
    _log(
        f"三档覆盖均值 {summary['avg_tier_coverage']:.2f} · top-1 稳定 {summary['avg_stability']:.0%} · "
        f"单特征抖动改变率 {summary['avg_jitter_change_rate']:.0%}"
    )
    if summary.get("known_gap_cases"):
        _log(
            f"已知缺口 {summary['known_gap_cases']} 例（不计入合理性通过率），"
            f"仍未修复 {summary['known_gap_failing']} 例"
        )
    llm = report.get("llm")
    if llm:
        _log(
            f"解释层：LLM 有效 {llm['valid_rate']:.0%} · 降级 {llm['degraded_cases']} 例 · "
            f"平均耗时 {llm['avg_latency_ms']:.0f} ms"
        )
        for error in llm["errors"]:
            _log(f"  ! {error}")
    vision = report.get("vision")
    if vision:
        detail = " · ".join(f"{field} {rate:.0%}" for field, rate in vision["accuracy"].items())
        _log(
            f"视觉层：检测 {vision['detected']}/{vision['cases']} "
            f"（{vision['detection_rate']:.0%}） · 特征准确率 {detail or '—'}"
        )
        for entry in vision["per_case"]:
            misses = [field for field, hit in entry["matches"].items() if not hit]
            if entry.get("error"):
                _log(f"  ! {entry['id']} 未识别：{entry['error']}")
            elif misses:
                _log(f"  Δ {entry['id']} 特征不符：{', '.join(misses)}")
    _log("=" * 68)


def write_report(report: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NailFit 推荐质量评测（M18）")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="用例 JSON 路径")
    parser.add_argument("--styles", default=None, help="款式库 JSON 路径（默认 data/styles.sample.json）")
    parser.add_argument("--runs", type=int, default=3, help="每个用例重复运行次数（稳定性）")
    parser.add_argument("--llm", action="store_true", help="额外测解释层（需要 .env 里的 DeepSeek Key）")
    parser.add_argument("--llm-cases", type=int, default=3, help="解释层测几个用例")
    parser.add_argument("--vision", action="store_true", help="额外测手照视觉层（M19，需要本地 mediapipe 模型）")
    parser.add_argument("--json", default=None, help="报告输出路径（默认 eval/reports/eval-<时间戳>.json）")
    parser.add_argument("--no-report", action="store_true", help="不落盘 JSON 报告")
    parser.add_argument("--min-fit", type=float, default=0.9, help="--strict 下的合理性通过率下限")
    parser.add_argument("--strict", action="store_true", help="合理性低于 --min-fit 时返回非 0")
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.cases))
    styles = load_styles(Path(args.styles) if args.styles else None)
    taxonomy = load_taxonomy()
    report = evaluate(
        cases,
        styles,
        taxonomy,
        runs=max(1, args.runs),
        llm=args.llm,
        llm_cases=max(1, args.llm_cases),
        vision=args.vision,
    )
    print_report(report)
    if not args.no_report:
        target = (
            Path(args.json)
            if args.json
            else DEFAULT_REPORT_DIR / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        path = write_report(report, target)
        _log(f"报告已写入：{path}")

    if args.strict and report["summary"]["fit_pass_rate"] < args.min_fit:
        _log(f"✗ 合理性通过率 {report['summary']['fit_pass_rate']:.0%} < 阈值 {args.min_fit:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

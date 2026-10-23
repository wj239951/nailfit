"""NailFit 的 Streamlit 前端：填 7 项特征 → 三张推荐卡。

启动：

    pip install -r requirements-frontend.txt
    streamlit run app/streamlit_app.py

页面只做展示与交互，特征校验、推荐编排、视图整理分别复用
core.features / core.pipeline / core.ui_view，和 CLI、FastAPI 行为一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from core.errors import NailFitError  # noqa: E402
from core.features import FeatureError  # noqa: E402
from core.labels import FIELD_TITLES, label, summarize  # noqa: E402
from core.presets import (  # noqa: E402
    DEFAULTS,
    FEATURE_FIELDS,
    SCENARIO_LABELS,
    SCENARIOS,
    feature_options,
)
from core.ui_view import (  # noqa: E402
    avoid_tips,
    card_view,
    generate,
    library_choices,
    payload_json,
)
from core.validator import ContractError  # noqa: E402

st.set_page_config(page_title="NailFit · 手型美甲推荐", page_icon="💅", layout="wide")

CUSTOM_PRESET = "自定义"
LIBRARIES = library_choices()


def _init_state() -> None:
    st.session_state.setdefault("payload", None)
    st.session_state.setdefault("error", None)
    st.session_state.setdefault("preset", CUSTOM_PRESET)
    st.session_state.setdefault("lib_label", LIBRARIES[0][0] if LIBRARIES else "")
    for field in FEATURE_FIELDS:
        st.session_state.setdefault(f"sel_{field}", DEFAULTS[field])


def _on_preset_change() -> None:
    name = st.session_state.get("preset")
    if name and name != CUSTOM_PRESET:
        for field, value in SCENARIOS[name].items():
            st.session_state[f"sel_{field}"] = value


def _reset() -> None:
    st.session_state.preset = CUSTOM_PRESET
    for field in FEATURE_FIELDS:
        st.session_state[f"sel_{field}"] = DEFAULTS[field]
    st.session_state.payload = None
    st.session_state.error = None


def _selection() -> dict[str, str]:
    return {field: st.session_state[f"sel_{field}"] for field in FEATURE_FIELDS}


def _run() -> None:
    lib_label = st.session_state.get("lib_label") or ""
    styles_path = dict(LIBRARIES).get(lib_label)
    try:
        payload = generate(
            _selection(),
            free_text=st.session_state.get("free_text", ""),
            use_llm=bool(st.session_state.get("use_llm", False)),
            styles_path=styles_path,
        )
    except (NailFitError, ContractError, FeatureError, ValueError) as exc:
        st.session_state.payload = None
        st.session_state.error = str(exc)
    else:
        st.session_state.payload = payload
        st.session_state.error = None


# ---------------------------------------------------------------- 侧边栏
def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 💅 NailFit")
        st.caption("手型美甲推荐 · 规则驱动 + 可解释理由")

        st.selectbox(
            "场景预设",
            [CUSTOM_PRESET, *SCENARIOS],
            format_func=lambda name: (
                CUSTOM_PRESET if name == CUSTOM_PRESET else f"{SCENARIO_LABELS[name]}（{name}）"
            ),
            key="preset",
            on_change=_on_preset_change,
        )

        enums = feature_options()
        for field in FEATURE_FIELDS:
            st.selectbox(
                FIELD_TITLES.get(field, field),
                enums[field],
                format_func=lambda value, f=field: f"{label(f, value)}（{value}）",
                key=f"sel_{field}",
            )

        st.divider()
        st.text_input(
            "自由描述（可选）",
            placeholder="例如：想要温柔一点、显白、适合婚礼",
            key="free_text",
        )
        st.checkbox(
            "用大模型生成理由（需 DEEPSEEK_API_KEY）",
            value=False,
            key="use_llm",
        )

        if len(LIBRARIES) > 1:
            st.selectbox(
                "款式库",
                [item[0] for item in LIBRARIES],
                key="lib_label",
                help="样例库用于快速验证流程；演示库带 43 张演示图",
            )

        col_run, col_reset = st.columns(2)
        col_run.button("开始推荐", type="primary", on_click=_run, use_container_width=True)
        col_reset.button("重置", on_click=_reset, use_container_width=True)

        st.divider()
        st.caption("当前特征：" + summarize(_selection()))


# ---------------------------------------------------------------- 主区域
def render_card(index: int, view: dict) -> None:
    with st.container(border=True):
        if view["image"] is not None:
            st.image(str(view["image"]))
        else:
            st.info("这张推荐暂无可展示的款式图（占位数据）。")

        st.markdown(f"**{index}. {view['name']}**")
        st.caption(f"{view['tier_text']} · 匹配度 {view['score_percent']}%")
        st.progress(min(1.0, view["score_percent"] / 100.0))
        st.write(view["reason"])

        if view["caution"]:
            st.warning(view["caution"])

        details = view["matched_reasons"] or [f"命中规则：{rule}" for rule in view["matched_rules"]]
        if details:
            with st.expander("为什么推荐它？"):
                for line in details:
                    st.markdown(f"- {line}")
                if view["style_id"]:
                    st.caption(f"款式 id：{view['style_id']}")


def render_result(payload: dict) -> None:
    meta = payload.get("meta", {})
    left, mid, right = st.columns(3)
    left.metric("候选池可用", f"{meta.get('candidates_considered', '?')} 款")
    mid.metric("规则排除", f"{meta.get('excluded', '?')} 款")
    right.metric("推荐档位", "3 档")

    st.caption("已选特征：" + summarize(payload.get("features") or {}))
    st.divider()

    views = [card_view(card) for card in payload.get("recommendations", [])]
    columns = st.columns(len(views) or 1)
    for index, view in enumerate(views, start=1):
        with columns[index - 1]:
            render_card(index, view)

    tips = avoid_tips(payload)
    if tips:
        st.subheader("避雷提示")
        for tip in tips:
            st.markdown(f"- {tip}")

    with st.expander("查看原始 JSON（便于调试 / 接下游）"):
        st.code(payload_json(payload), language="json")


def main() -> None:
    _init_state()
    render_sidebar()

    st.title("NailFit · 手型美甲推荐")
    st.write(
        "从 7 项手部特征出发，用规则引擎 + 款式库检索给出 **稳妥 / 亮点 / 大胆** 三档推荐，"
        "并解释每条推荐命中了你哪些特征。"
    )

    error = st.session_state.get("error")
    payload = st.session_state.get("payload")

    if error:
        st.error(f"推荐失败：{error}")
        st.info("可以放宽场景/甲长，或在侧边栏换一个款式库再试。")
    elif payload:
        render_result(payload)
    else:
        st.info("在左侧选择特征（或用场景预设），然后点击 **开始推荐**。")
        st.markdown(
            "还没有直觉？先试这几个预设：\n"
            + "\n".join(f"- **{SCENARIO_LABELS[name]}** — `{name}`" for name in SCENARIOS)
        )

    st.divider()
    st.caption(
        "演示图来自公开平台截图，仅用于工程演示，版权归原作者；"
        "正式使用请替换为自拍/可商用图库，见 docs/IMAGE_GUIDE.md。"
    )


main()

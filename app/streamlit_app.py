"""NailFit 的 Streamlit 前端：手照识别 或 手工填 7 项特征 → 三张推荐卡。

启动：

    pip install -r requirements-frontend.txt
    streamlit run app/streamlit_app.py

页面只做展示与交互，特征校验、推荐编排、视图整理分别复用
core.features / core.pipeline / core.ui_view，和 CLI、FastAPI 行为一致。
手照识别（M8/M9）复用 core.vision，mediapipe 是可选依赖。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

try:  # 方便本地 .env：装了 python-dotenv 时自动读取（缺依赖也不影响运行）
    from dotenv import load_dotenv  # noqa: E402

    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001
    pass

from core import vision  # noqa: E402
from core.errors import NailFitError  # noqa: E402
from core.features import FeatureError  # noqa: E402
from core.labels import FIELD_TITLES, label, summarize  # noqa: E402
from core.pipeline import features_from_image  # noqa: E402
from core.presets import (  # noqa: E402
    DEFAULTS,
    FEATURE_FIELDS,
    SCENE_LABELS,
    SCENARIO_LABELS,
    SCENARIOS,
    feature_options,
    scene_options,
)
from core.ui_view import (  # noqa: E402
    avoid_tips,
    card_view,
    default_library_label,
    gallery_styles,
    generate,
    library_choices,
    payload_json,
)
from core.validator import ContractError  # noqa: E402

st.set_page_config(page_title="NailFit · 手型美甲推荐", page_icon="💅", layout="wide")

CUSTOM_PRESET = "自定义"
LIBRARIES = library_choices()
# 用户上传的手照存私密目录：不在 static/ 下，不会被 API 的 /static 公开服务
UPLOAD_DIR = ROOT / "data" / "uploads"
MODE_MANUAL = "手动选择特征"
MODE_VISION = "手照识别"
QUALITY_TEXT = {
    "ok": "✅ 手背平放/自然展开，甲面可全自动量",
    "relaxed": "🟡 手略扣：自动出肤色，甲面特征用下拉补 2 秒",
    "clenched": "🟠 握拳/展示角度：自动出肤色，甲面特征用下拉补 2 秒",
    "pose": "⚠️ 手朝镜头/侧位：甲面特征不可靠",
    "low": "⚠️ 手太小或检测置信度低",
}


def _init_state() -> None:
    st.session_state.setdefault("payload", None)
    st.session_state.setdefault("error", None)
    st.session_state.setdefault("preset", CUSTOM_PRESET)
    library_labels = [label for label, _ in LIBRARIES]
    if st.session_state.get("lib_label") not in library_labels:
        # 首次进入，或库的标签文案变了（条数会变），重置为默认库（优先演示库）
        st.session_state["lib_label"] = default_library_label()
    st.session_state.setdefault("input_mode", MODE_MANUAL)
    st.session_state.setdefault("vision_payload", None)
    st.session_state.setdefault("vision_meta", None)
    st.session_state.setdefault("vision_image", None)
    st.session_state.setdefault("vision_error", None)
    st.session_state.setdefault("vision_scene", "commute")
    st.session_state.setdefault("vision_upload_name", None)
    for field in FEATURE_FIELDS:
        st.session_state.setdefault(f"sel_{field}", DEFAULTS[field])
        st.session_state.setdefault(f"fix_{field}", DEFAULTS[field])


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


def _styles_path() -> str | None:
    return dict(LIBRARIES).get(st.session_state.get("lib_label") or "")


def render_library_select() -> None:
    """「款式库」下拉：两种输入模式共用（手照模式也能切到演示库看真实图片）。"""
    if len(LIBRARIES) <= 1:
        return
    st.selectbox(
        "款式库",
        [label for label, _ in LIBRARIES],
        key="lib_label",
        help="样例库只用来看流程（图片是占位图）；演示库带演示图，推荐卡片能显示真实图片",
    )


def _run() -> None:
    try:
        payload = generate(
            _selection(),
            free_text=st.session_state.get("free_text", ""),
            use_llm=bool(st.session_state.get("use_llm", False)),
            styles_path=_styles_path(),
        )
    except (NailFitError, ContractError, FeatureError, ValueError) as exc:
        st.session_state.payload = None
        st.session_state.error = str(exc)
    else:
        st.session_state.payload = payload
        st.session_state.error = None


# ---------------------------------------------------------------- 手照识别
def _save_upload(uploaded) -> Path:
    data = uploaded.getvalue()
    digest = hashlib.sha1(data).hexdigest()[:12]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(uploaded.name).suffix.lower() or ".jpg"
    target = UPLOAD_DIR / f"hand_{digest}{suffix}"
    target.write_bytes(data)
    return target


def _download_model() -> None:
    try:
        with st.spinner("下载手势模型（约 8MB）…"):
            vision.ensure_model(download=True)
    except (NailFitError, OSError) as exc:
        st.session_state.vision_error = f"模型下载失败：{exc}"
    else:
        st.session_state.vision_error = None
    st.rerun()


def _analyze_hand() -> None:
    image_path = st.session_state.get("vision_image")
    if not image_path:
        st.session_state.vision_error = "先在左侧上传一张手照"
        return
    try:
        payload, meta = features_from_image(
            image_path,
            scene=st.session_state.get("vision_scene", "commute"),
            auto_download=False,
        )
    except (NailFitError, ValueError, OSError) as exc:
        st.session_state.vision_payload = None
        st.session_state.vision_meta = None
        st.session_state.vision_error = str(exc)
    else:
        st.session_state.vision_payload = payload
        st.session_state.vision_meta = meta
        st.session_state.vision_error = None
        st.session_state.payload = None


def _vision_selection() -> dict[str, str]:
    """视觉特征 + 用户对不可靠字段的修正（M11 回退）。"""
    payload = dict(st.session_state.get("vision_payload") or {})
    meta = st.session_state.get("vision_meta") or {}
    for field in meta.get("unreliable", []):
        payload[field] = st.session_state.get(f"fix_{field}", DEFAULTS[field])
    payload["scene"] = st.session_state.get("vision_scene", payload.get("scene", "commute"))
    return payload


def _run_vision() -> None:
    try:
        payload = generate(
            _vision_selection(),
            free_text=st.session_state.get("free_text", ""),
            use_llm=bool(st.session_state.get("use_llm", False)),
            styles_path=_styles_path(),
        )
    except (NailFitError, ContractError, FeatureError, ValueError) as exc:
        st.session_state.payload = None
        st.session_state.error = str(exc)
    else:
        st.session_state.payload = payload
        st.session_state.error = None


def render_vision_sidebar() -> None:
    status = vision.model_status()
    if status["installed"]:
        st.success(f"手部模型就绪（{status['size_mb']} MB）")
    else:
        st.warning("手部模型还没下载（约 8MB）")
        st.button("下载模型", type="primary", on_click=_download_model, use_container_width=True)

    scenes = scene_options()
    if st.session_state.get("vision_scene") not in scenes:
        # 旧会话里可能残留“特征预设名”（如 slender_cool），重置为合法场景
        st.session_state["vision_scene"] = scenes[0]
    st.selectbox(
        "使用场景",
        scenes,
        format_func=lambda name: f"{SCENE_LABELS.get(name, name)}（{name}）",
        key="vision_scene",
        help="场景从手照里推断不出来，需要手动选",
    )

    render_library_select()

    st.text_input(
        "自由描述（可选）",
        placeholder="比如：想显白一点、不要太夸张、婚礼要拍手",
        key="free_text",
    )
    st.checkbox(
        "用大模型生成理由（需在 .env 配好 DEEPSEEK_API_KEY）",
        value=False,
        key="use_llm",
    )

    uploaded = st.file_uploader("上传手照", type=["jpg", "jpeg", "png"], key="vision_upload")
    if uploaded is not None and uploaded.name != st.session_state.get("vision_upload_name"):
        path = _save_upload(uploaded)
        st.session_state.vision_image = str(path)
        st.session_state.vision_upload_name = uploaded.name
        st.session_state.vision_payload = None
        st.session_state.vision_meta = None
        st.session_state.vision_error = None

    if st.session_state.get("vision_image"):
        st.image(st.session_state["vision_image"], caption="已上传手照", width=220)

    st.button("识别手部特征", type="primary", on_click=_analyze_hand, use_container_width=True)
    st.caption(
        "拍法（最省事）：**手背朝上平放在桌面/腿上，手机从正上方拍**，手指自然并拢或微开即可。"
        "握拳、展示美甲这类随手角度也能用——会自动出肤色，甲面几项用下拉补选。"
    )


def render_vision_area() -> None:
    st.title("NailFit · 手照识别")
    st.write(
        "上传一张手照，自动提取 **肤色 / 手型 / 甲床比例 / 甲型 / 甲长**，"
        "再走和手工录入同一套规则引擎给出三档推荐。"
        "自然角度（握拳、展示美甲）也能用，只是甲面几项会让你用下拉补选。"
    )

    vision_error = st.session_state.get("vision_error")
    meta = st.session_state.get("vision_meta")
    payload = st.session_state.get("vision_payload")

    if vision_error:
        st.error(f"手照识别失败：{vision_error}")
    if not meta:
        st.info("在左侧上传手照并点击 **识别手部特征**；也可以用左边的「手动选择特征」直接开始。")
        render_gallery()
        return

    quality = str(meta.get("quality"))
    st.markdown(
        f"**照片质量**：{QUALITY_TEXT.get(quality, quality)} · "
        f"左右手 {meta.get('handedness')} · 手势 {meta.get('gesture')} · "
        f"ITA° {meta.get('ita_degrees')}"
    )
    if payload:
        st.caption("识别结果：" + summarize(payload))

    unreliable = meta.get("unreliable") or []
    if unreliable:
        st.warning(
            "这几项这个角度量不准，用下面的下拉补一下就行（不用重拍）："
            + "、".join(FIELD_TITLES.get(f, f) for f in unreliable)
        )
        enums = feature_options()
        columns = st.columns(min(3, len(unreliable)))
        for index, field in enumerate(unreliable):
            with columns[index % len(columns)]:
                st.selectbox(
                    FIELD_TITLES.get(field, field),
                    enums[field],
                    format_func=lambda value, f=field: f"{label(f, value)}（{value}）",
                    key=f"fix_{field}",
                )

    with st.expander("视觉细节（关键点标注 / 原始几何量）"):
        preview = meta.get("preview")
        if preview and Path(str(preview)).exists():
            st.image(str(preview), caption="关键点标注图")
        st.json(
            {
                "confidences": meta.get("confidences", {}),
                "metrics": meta.get("metrics", {}),
                "notes": meta.get("notes", []),
            },
            expanded=False,
        )

    st.button("用这组特征推荐", type="primary", on_click=_run_vision, use_container_width=False)

    error = st.session_state.get("error")
    payload = st.session_state.get("payload")
    if error:
        st.error(f"推荐失败：{error}")
        st.info("可以调整上面不可靠的字段，或换一个款式库再试。")
    elif payload:
        render_result(payload)


# ---------------------------------------------------------------- 侧边栏
def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 💅 NailFit")
        st.caption("手型美甲推荐 · 规则驱动 + 可解释理由")
        st.radio("输入方式", [MODE_MANUAL, MODE_VISION], key="input_mode", horizontal=True)

        if st.session_state.get("input_mode") == MODE_VISION:
            render_vision_sidebar()
            return

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

        render_library_select()

        col_run, col_reset = st.columns(2)
        col_run.button("开始推荐", type="primary", on_click=_run, use_container_width=True)
        col_reset.button("重置", on_click=_reset, use_container_width=True)

        st.divider()
        st.caption("当前特征：" + summarize(_selection()))


# ---------------------------------------------------------------- 主区域
def render_card(index: int, view: dict) -> None:
    with st.container(border=True):
        if view["image"] is not None:
            st.image(str(view["image"]), width="stretch")
        else:
            st.info("这张推荐暂无可展示的款式图（占位数据）。")
        if view.get("media_caption"):
            st.caption(view["media_caption"])
        if view.get("media_source_url"):
            st.caption(f"[查看图片来源]({view['media_source_url']})")

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
    explainer = meta.get("explainer") or {}
    if explainer.get("mode") == "llm":
        note = f"理由来源：大模型 {explainer.get('model')}（{explainer.get('llm_cards', 0)}/3 条）"
        if explainer.get("degraded"):
            note += "，部分回退模板"
        st.caption(note)
    elif explainer.get("mode") == "template":
        if explainer.get("degraded"):
            st.caption(f"理由来源：模板（{explainer.get('error') or '大模型不可用，已降级'}）")
        else:
            st.caption("理由来源：模板（侧边栏未开启大模型）")
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
        st.download_button(
            "下载推荐结果 JSON",
            data=payload_json(payload),
            file_name="nailfit_recommendation.json",
            mime="application/json",
            width="stretch",
        )


def render_gallery() -> None:
    """首页图廊：先给用户看「这个系统长什么样」，再让他去选特征。

    只展示当前款式库里**确实有图**的款式；一条都没有时给出可执行的修复提示，
    避免页面出现一堆空白占位或干脆什么都不显示。
    """
    items = gallery_styles(_styles_path(), limit=8)
    st.subheader("先看看款式库")
    if not items:
        st.caption(
            "当前款式库没有可展示的图片。运行 `python scripts/make_sample_images.py` "
            "生成样例库占位图，或在侧边栏切到「演示库（带演示图）」后再刷新。"
        )
        return
    current = st.session_state.get("lib_label") or ""
    st.caption(f"{current} ｜ 这里先展示 {len(items)} 款；点击 **开始推荐** 看完整三档推荐与理由。")
    columns = st.columns(4)
    for index, item in enumerate(items):
        with columns[index % 4]:
            st.image(str(item["image"]), caption=item["caption"], width="stretch")


def render_manual_area() -> None:
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
        render_gallery()
        st.markdown(
            "还没有直觉？先试这几个预设：\n"
            + "\n".join(f"- **{SCENARIO_LABELS[name]}** — `{name}`" for name in SCENARIOS)
        )


def main() -> None:
    _init_state()
    render_sidebar()

    if st.session_state.get("input_mode") == MODE_VISION:
        render_vision_area()
    else:
        render_manual_area()

    st.divider()
    st.caption(
        "演示图来自公开平台截图，仅用于工程演示，版权归原作者；"
        "正式使用请替换为自拍/可商用图库，见 docs/IMAGE_GUIDE.md。"
    )


main()

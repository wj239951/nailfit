"""款式库数据校验。

手工录入 200 条款式时，最常见的错误是：字段拼错、枚举值写错、id 重复、
图片路径和文件对不上。这个模块把这些检查集中起来，供 CLI 和测试复用。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")

REQUIRED_FIELDS = (
    "id",
    "name",
    "image",
    "shape",
    "color_family",
    "tone",
    "value",
    "saturation",
    "style",
    "length_fit",
    "scene",
    "hue",
)

# 直接映射 taxonomy["styles"][field]
STYLE_ENUM_FIELDS = ("color_family", "tone", "value", "saturation", "style")


def load_styles_json(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    styles = data["styles"] if isinstance(data, dict) else data
    if not isinstance(styles, list):
        raise ValueError(f"{path} 结构错误：应为数组或 {{'styles': [...]}}")
    return styles


def validate_style(style: object, taxonomy: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(style, dict):
        return ["款式条目必须是 JSON 对象"]

    raw_id = style.get("id")
    sid = str(raw_id) if raw_id else "<无 id>"

    if not raw_id or not ID_PATTERN.match(str(raw_id)):
        errors.append(f"{sid}: id 非法（小写字母/数字/下划线/连字符，2-32 位）")

    for field in REQUIRED_FIELDS:
        value = style.get(field)
        if value is None or value == "" or value == []:
            errors.append(f"{sid}: 缺少或为空字段 {field}")

    shapes = style.get("shape")
    if shapes is not None:
        if not isinstance(shapes, list) or not shapes:
            errors.append(f"{sid}: shape 必须是非空数组")
        else:
            allowed = set(taxonomy["features"]["nail_shape"])
            for value in shapes:
                if value not in allowed:
                    errors.append(f"{sid}: shape 含非法取值 {value!r}（可选 {sorted(allowed)}）")

    for field in STYLE_ENUM_FIELDS:
        value = style.get(field)
        if value is None:
            continue
        allowed = set(taxonomy["styles"].get(field, []))
        if value not in allowed:
            errors.append(f"{sid}: {field} 非法取值 {value!r}（可选 {sorted(allowed)}）")

    scenes = style.get("scene")
    if scenes is not None:
        if not isinstance(scenes, list) or not scenes:
            errors.append(f"{sid}: scene 必须是非空数组")
        else:
            allowed = set(taxonomy["features"]["scene"])
            for value in scenes:
                if value not in allowed:
                    errors.append(f"{sid}: scene 含非法取值 {value!r}（可选 {sorted(allowed)}）")

    bed_fit = style.get("nail_bed_fit")
    if bed_fit is not None:
        if not isinstance(bed_fit, list):
            errors.append(f"{sid}: nail_bed_fit 必须是数组")
        else:
            allowed = set(taxonomy["features"]["nail_bed_ratio"])
            for value in bed_fit:
                if value not in allowed:
                    errors.append(f"{sid}: nail_bed_fit 含非法取值 {value!r}")

    length_fit = style.get("length_fit")
    if length_fit is not None and length_fit not in taxonomy["styles"]["length_fit"]:
        errors.append(
            f"{sid}: length_fit 非法取值 {length_fit!r}（可选 {taxonomy['styles']['length_fit']}）"
        )

    hue = style.get("hue")
    if hue is not None:
        if isinstance(hue, bool) or not isinstance(hue, (int, float)) or not 0 <= float(hue) <= 360:
            errors.append(f"{sid}: hue 必须是 0-360 的数字")

    tags = style.get("tags")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
        errors.append(f"{sid}: tags 必须是字符串数组")

    image = style.get("image")
    if isinstance(image, str) and not image.startswith("static/"):
        errors.append(f"{sid}: image 应使用 static/... 相对路径，当前 {image!r}")

    return errors


def validate_styles(styles: list | tuple, taxonomy: dict) -> list[str]:
    errors: list[str] = []
    seen: set[object] = set()
    for style in styles:
        if isinstance(style, dict):
            sid = style.get("id")
            if sid in seen:
                errors.append(f"{sid}: id 重复")
            seen.add(sid)
        errors.extend(validate_style(style, taxonomy))
    return errors


def check_images(styles: list | tuple, root: str | Path) -> list[str]:
    """检查 image 指向的文件是否真实存在（相对项目根目录）。"""
    errors: list[str] = []
    base = Path(root)
    for style in styles:
        if not isinstance(style, dict):
            continue
        image = style.get("image")
        if not isinstance(image, str) or not image:
            continue
        if not (base / image).is_file():
            errors.append(f"{style.get('id')}: 图片不存在 {image}")
    return errors

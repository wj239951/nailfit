from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from core.data import DEFAULT_LIBRARY, LIBRARIES, ROOT, library_path, load_styles, load_taxonomy
from core.errors import (
    DataFormatError,
    EmptyStyleLibraryError,
    NoCandidateError,
    VisionUnusableError,
)
from core.features import FeatureError, HandFeatures
from core.pipeline import (
    features_from_image,
    recommend,
    recommend_from_image,
)
from core.references import attach_references
from core.validator import ContractError
from core.vision import VisionError

from .schemas import (
    RecommendFromImageRequest,
    RecommendFromImageResponse,
    RecommendRequest,
    RecommendResponse,
    VisionExtractRequest,
    VisionExtractResponse,
)

router = APIRouter(prefix="/api", tags=["nailfit"])

# 上传图片大小上限：12MB（手机原图一般 2–6MB）
MAX_UPLOAD_BYTES = 12 * 1024 * 1024


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "nailfit",
        # 前端据此决定是否可勾选「用大模型生成理由」；没有 Key 时后端会自动降级为模板
        "llm_configured": bool(os.getenv("DEEPSEEK_API_KEY")),
    }


@router.get("/libraries")
def list_libraries() -> dict:
    """可选款式库 + 图片齐全度。前端据此决定默认库与「演示图缺失」提示。"""
    items: list[dict] = []
    for name in sorted(LIBRARIES):
        item: dict = {"name": name, "count": 0, "available": False, "images_ready": False}
        try:
            styles = load_styles(str(LIBRARIES[name]))
        except (EmptyStyleLibraryError, DataFormatError):
            items.append(item)
            continue
        if styles:
            item["count"] = len(styles)
            item["available"] = True
            missing = 0
            for style in styles:
                image = (style.get("media") or {}).get("image") or style.get("image") or ""
                if not (ROOT / str(image)).is_file():
                    missing += 1
            item["images_ready"] = missing == 0
            item["missing_images"] = missing
        items.append(item)
    return {"default": DEFAULT_LIBRARY, "libraries": items}


@router.get("/taxonomy")
def taxonomy() -> dict:
    try:
        return load_taxonomy()
    except DataFormatError as exc:
        raise HTTPException(status_code=503, detail=f"taxonomy 不可用: {exc}") from exc


@router.get("/styles")
def list_styles(library: str = "sample") -> dict:
    """款式库列表。库为空/损坏时返回 503，而不是 500 traceback。"""
    try:
        path = library_path(library)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        styles = load_styles(str(path))
    except EmptyStyleLibraryError as exc:
        raise HTTPException(status_code=503, detail=f"款式库不可用: {exc}") from exc
    except DataFormatError as exc:
        raise HTTPException(status_code=503, detail=f"款式库不可用: {exc}") from exc
    return {"count": len(styles), "styles": list(styles)}


@router.post("/recommend", response_model=RecommendResponse)
def recommend_endpoint(req: RecommendRequest) -> dict:
    # 1) 输入侧：特征非法 → 422
    try:
        features = HandFeatures.from_dict(req.features)
    except FeatureError as exc:
        raise HTTPException(status_code=422, detail=f"特征非法: {exc}") from exc

    # 2) 款式库选择：未知库名 → 422
    try:
        styles = load_styles(str(library_path(req.library)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (EmptyStyleLibraryError, DataFormatError) as exc:
        raise HTTPException(status_code=503, detail=f"款式库不可用: {exc}") from exc

    # 3) 业务侧：区分「服务端数据问题（503）」和「输入太苛刻（422）」
    try:
        return attach_references(
            recommend(features, free_text=req.free_text, use_llm=req.use_llm, styles=styles)
        )
    except (EmptyStyleLibraryError, DataFormatError) as exc:
        raise HTTPException(status_code=503, detail=f"款式库不可用: {exc}") from exc
    except NoCandidateError as exc:
        raise HTTPException(status_code=422, detail=f"无法生成推荐: {exc}") from exc
    except ContractError as exc:
        # 输出契约失败：说明模型编了款式或理由不合规
        raise HTTPException(status_code=502, detail=f"推荐结果校验失败: {exc}") from exc


@router.post("/vision/extract", response_model=VisionExtractResponse)
def vision_extract_endpoint(req: VisionExtractRequest) -> dict:
    """手照 → 手部特征（M8/M9）。只是识别，不做推荐。"""
    try:
        features, meta = features_from_image(
            req.image_path,
            scene=req.scene,
            overrides=req.overrides,
            auto_download=req.auto_download,
        )
    except VisionError as exc:
        raise HTTPException(status_code=422, detail=f"手照识别失败: {exc}") from exc
    return {"features": features, **meta}


@router.post("/recommend/from-image", response_model=RecommendFromImageResponse)
def recommend_from_image_endpoint(req: RecommendFromImageRequest) -> dict:
    """手照直接出推荐（M9）。质量不达标时 422，前端转手工录入（M11）。"""
    try:
        return attach_references(
            recommend_from_image(
                req.image_path,
                scene=req.scene,
                use_llm=req.use_llm,
                free_text=req.free_text,
                overrides=req.overrides,
                auto_download=req.auto_download,
            )
        )
    except VisionError as exc:
        raise HTTPException(status_code=422, detail=f"手照识别失败: {exc}") from exc
    except VisionUnusableError as exc:
        raise HTTPException(status_code=422, detail=f"手照信息不足: {exc}") from exc
    except (EmptyStyleLibraryError, DataFormatError) as exc:
        raise HTTPException(status_code=503, detail=f"款式库不可用: {exc}") from exc
    except NoCandidateError as exc:
        raise HTTPException(status_code=422, detail=f"无法生成推荐: {exc}") from exc
    except ContractError as exc:
        raise HTTPException(status_code=502, detail=f"推荐结果校验失败: {exc}") from exc


@router.post("/vision/upload")
async def vision_upload_endpoint(
    request: Request,
    scene: str = "commute",
    auto_download: bool = False,
) -> dict:
    """上传手照 → 手部特征（网页前端专用）。

    与 `/api/vision/extract` 的区别：前端没有服务端文件路径，直接把图片字节
    放在请求体里（Content-Type: image/jpeg / image/png / image/webp）。
    图片写到系统临时目录，识别后立即清理，不落进项目目录。
    """
    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="上传内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"图片过大：{len(data) // 1024}KB > {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )
    ctype = (request.headers.get("content-type") or "").lower()
    suffix = ".png" if "png" in ctype else ".webp" if "webp" in ctype else ".jpg"
    tmpdir = Path(tempfile.mkdtemp(prefix="nailfit-upload-"))
    path = tmpdir / f"upload{suffix}"
    try:
        path.write_bytes(data)
        features, meta = features_from_image(
            str(path),
            scene=scene,
            auto_download=auto_download,
        )
    except VisionError as exc:
        raise HTTPException(status_code=422, detail=f"手照识别失败: {exc}") from exc
    except FeatureError as exc:
        raise HTTPException(status_code=422, detail=f"手照特征非法: {exc}") from exc
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return {"features": features, **meta}

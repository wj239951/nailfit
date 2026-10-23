from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.data import load_styles, load_taxonomy
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


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "nailfit"}


@router.get("/taxonomy")
def taxonomy() -> dict:
    try:
        return load_taxonomy()
    except DataFormatError as exc:
        raise HTTPException(status_code=503, detail=f"taxonomy 不可用: {exc}") from exc


@router.get("/styles")
def list_styles() -> dict:
    """款式库列表。库为空/损坏时返回 503，而不是 500 traceback。"""
    try:
        styles = load_styles()
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

    # 2) 业务侧：区分「服务端数据问题（503）」和「输入太苛刻（422）」
    try:
        return recommend(features, free_text=req.free_text, use_llm=req.use_llm)
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
        return recommend_from_image(
            req.image_path,
            scene=req.scene,
            use_llm=req.use_llm,
            free_text=req.free_text,
            overrides=req.overrides,
            auto_download=req.auto_download,
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

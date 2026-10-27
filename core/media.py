"""媒体解析层：文本款式 → 参考图 + 来源。

为什么单独一层：
- 推荐决策不依赖网络：core/pipeline.py 只负责「推荐哪三款」，媒体解析只服务展示。
- 缓存优先：scripts/prefetch_media.py 用 Provider 预先抓图写 data/media_cache.json，
  展示层只读缓存 / 样式自带图（毫秒级、可复现、离线可跑）。
- 失败必须降级：没图就返回占位信息，卡片退化成纯文字，绝不阻塞推荐。
- 授权必须可标注：每张图带 license / source_url，前端据此显示「风格参考」与来源。

解析顺序：缓存（未过期）→ LocalProvider（static/ 下已有图）→ 网络 Provider → 占位。
网络 Provider（Pexels / DeepSeek Search / Openverse）只在 prefetch 时启用（allow_network=True），
推荐请求路径默认不联网。

Openverse（M26）是免 Key 的 CC 图源，标题相关性有限：先产出「候选图清单」人工复核，
再决定是否进正式库（scripts/openverse_candidates.py）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_PATH = ROOT / "data" / "media_cache.json"
DEFAULT_REFS_DIR = ROOT / "static" / "refs"

LICENSES = ("demo", "self", "pexels", "unsplash", "openverse", "unknown", "placeholder")
LICENSE_LABELS = {
    "demo": "工程演示素材",
    "self": "自摄 / 自有授权",
    "pexels": "Pexels（可商用）",
    "unsplash": "Unsplash（可商用）",
    "openverse": "Openverse CC 图（需署名）",
    "unknown": "公开网页",
    "placeholder": "占位",
}
REFERENCE_TAIL = "仅风格参考，非本手模拟效果"
PLACEHOLDER_NOTE = "暂无参考图：检索层未命中，仅展示文字推荐"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)")
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

# ---------------------------------------------------------------- Openverse
# 免 Key 的 CC 图源：https://api.openverse.org/v1/images/
# 2026-10-26 实测：API 可用（license 过滤与 page_size 生效），但标题经常是 IMG_1234，
# 关键词只命中 tags；相关性需要过滤 + 人工复核，不能全自动进正式库。
OPENVERSE_API_URL = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENSES = ("cc0", "pdm", "by", "by-sa")  # 允许展示/商用的 CC 许可
OPENVERSE_MIN_EDGE = 600  # 长边像素下限：太小的图不适合做参考图
_NAIL_TOKENS = ("nail", "nails", "manicure", "manicures", "fingernail", "fingernails", "nailart")
_OPENVERSE_STYLE_WORDS = {
    "solid": "solid color",
    "french": "french manicure",
    "gradient": "gradient",
    "cat_eye": "cat eye",
    "chrome": "chrome",
    "drawing": "nail art",
    "rhinestone": "rhinestone",
    "checker": "checkered",
    "marble": "marble",
    "mixed": "nail art",
    "glitter": "glitter",
}
_OPENVERSE_FAMILY_WORDS = {
    "nude_pink": "nude pink",
    "true_red": "red",
    "berry": "berry",
    "orange_brown": "orange brown",
    "blue_green": "blue green",
    "mono": "monochrome",
    "metal": "metallic",
    "glitter": "glitter",
}
_OPENVERSE_SHAPE_WORDS = {
    "round": "round",
    "square": "square",
    "oval": "oval",
    "almond": "almond",
    "squoval": "squoval",
}



def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def empty_media(note: str | None = None) -> dict:
    """占位媒体信息：卡片会显示成纯文字。"""
    return {
        "image": None,
        "source_url": None,
        "license": "placeholder",
        "provider": "none",
        "relevance": None,
        "fetched_at": None,
        "verified": False,
        "note": note or PLACEHOLDER_NOTE,
    }


def media_caption(media: dict | None) -> str:
    """前端图片下方的一行来源标注（授权优先展示）。"""
    media = media or {}
    license_name = str(media.get("license") or "unknown")
    label = LICENSE_LABELS.get(license_name, "公开网页")
    if license_name == "demo":
        return f"{label} · {REFERENCE_TAIL}"
    if license_name == "placeholder":
        # 占位示意图（样例库）与「没有图」不是一回事：前者有图但只是界面演示，不能叫演示素材
        if media.get("image"):
            return "示意占位图 · 非真实款式"
        return "暂无参考图 · 仅展示文字推荐"
    if not media.get("image"):
        return "暂无参考图 · 仅展示文字推荐"
    if license_name in ("pexels", "unsplash"):
        return f"图片：{label} · {REFERENCE_TAIL}"
    if license_name == "self":
        return f"图片：{label} · {REFERENCE_TAIL}"
    if license_name == "openverse":
        detail = str(media.get("license_detail") or "CC 授权").strip()
        creator = str(media.get("creator") or "").strip()
        byline = f" · 作者 {creator}" if creator else ""
        return f"图片：{detail}{byline} · {REFERENCE_TAIL}"
    return f"图片来自网络（{label}）· {REFERENCE_TAIL}"


def media_image_path(media: dict | None, root: str | Path = ROOT) -> Path | None:
    """参考图的本地绝对路径；不是本地文件或不存在时返回 None。"""
    image = (media or {}).get("image")
    if not image or not str(image).startswith("static/"):
        return None
    path = (Path(root) / str(image)).resolve()
    return path if path.is_file() else None


@dataclass
class MediaResult:
    image: str | None = None
    source_url: str | None = None
    license: str = "unknown"
    provider: str = "none"
    relevance: float | None = None
    fetched_at: str | None = None
    verified: bool = False
    note: str | None = None
    creator: str | None = None
    license_detail: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ProviderError(RuntimeError):
    """Provider 不可用（缺 Key / 超时 / 页面没有可用图片）。"""


def _download_image(
    client, url: str, dest_dir: Path, stem: str, timeout: float, root: str | Path = ROOT
) -> str | None:
    """下载一张图到 dest_dir，返回相对 root 的路径；失败返回 None。"""
    try:
        response = client.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - 网络问题统一降级，不把异常抛给调用方
        return None
    content_type = str(response.headers.get("content-type", "")).lower()
    if "image" not in content_type:
        return None
    if not response.content or len(response.content) > MAX_IMAGE_BYTES:
        return None
    suffix = next((s for s in _IMAGE_SUFFIXES if s in content_type), ".jpg")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stem}{suffix}"
    try:
        dest.write_bytes(response.content)
    except OSError:
        return None
    try:
        return dest.relative_to(Path(root)).as_posix()
    except ValueError:
        return str(dest)


class LocalProvider:
    """样式自带图（static/ 下）：演示库/正式库已经准备好的参考图。"""

    name = "local"

    def __init__(self, root: str | Path = ROOT) -> None:
        self.root = Path(root)

    def resolve(self, style: dict) -> MediaResult | None:
        media = style.get("media") or {}
        image = media.get("image") or style.get("image")
        if not image or not str(image).startswith("static/"):
            return None
        if not (self.root / str(image)).is_file():
            return None
        return MediaResult(
            image=str(image),
            source_url=media.get("source_url"),
            license=str(media.get("license") or "placeholder"),
            provider=self.name,
            relevance=media.get("relevance"),
            fetched_at=media.get("fetched_at") or _today(),
            verified=True,
            note=media.get("note"),
        )


class PexelsProvider:
    """可商用图库 Pexels：授权干净、接口稳定，适合正式库的参考图来源。"""

    name = "pexels"
    API_URL = "https://api.pexels.com/v1/search"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 3.0,
        client=None,
        refs_dir: str | Path = DEFAULT_REFS_DIR,
        root: str | Path = ROOT,
    ) -> None:
        self.api_key = api_key or os.environ.get("PEXELS_API_KEY", "")
        self.timeout = timeout
        self._client = client
        self.refs_dir = Path(refs_dir)
        self.root = Path(root)

    def _http(self):
        if self._client is not None:
            return self._client
        import httpx  # 延迟导入：推荐主路径不需要 httpx 也能跑

        self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def resolve(self, style: dict) -> MediaResult | None:
        query = str(style.get("search_query") or style.get("name") or "").strip()
        if not self.api_key:
            raise ProviderError("PexelsProvider 缺少 PEXELS_API_KEY")
        if not query:
            return None
        client = self._http()
        try:
            response = client.get(
                self.API_URL,
                headers={"Authorization": self.api_key},
                params={"query": query, "per_page": 3, "orientation": "portrait"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            photos = (response.json() or {}).get("photos") or []
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Pexels 搜索失败：{exc}") from exc
        for photo in photos:
            src = photo.get("src") or {}
            url = src.get("portrait") or src.get("large2x") or src.get("large")
            if not url:
                continue
            image = _download_image(
                client,
                url,
                self.refs_dir,
                str(style.get("id") or "style"),
                self.timeout,
                root=self.root,
            )
            if image:
                return MediaResult(
                    image=image,
                    source_url=photo.get("url"),
                    license="pexels",
                    provider=self.name,
                    relevance=3.0,
                    fetched_at=_today(),
                    verified=False,
                    note="Pexels 可商用图库，仅风格参考",
                )
        return None


class SearchProvider:
    """DeepSeek Search + Fetch：检索公开网页，取正文首图或文本来源。

    接口见 https://api-docs.deepseek.com/guides/search ，按成功请求计费。

    实测（2026-10-26）：Fetch 只返回纯文本 Markdown，8 个页面 0 个图片标记，
    部分站点还会 404 / ReadTimeout。因此它**不能**作为通用图片源，默认图片链
    （MediaResolver.default_providers）不包含本 Provider，避免无谓计费；
    保留 resolve() 兼容个别带 Markdown 图片的页面，趋势/参考链接请用
    search_sources()（脚本 scripts/web_sources.py）。
    抓到的图默认 license=unknown：商用前必须自行确认授权，前端会显示来源。
    """

    name = "search"
    SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
    FETCH_URL = "https://api.deepseek.com/v1/tools/fetch"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 3.0,
        client=None,
        refs_dir: str | Path = DEFAULT_REFS_DIR,
        root: str | Path = ROOT,
        min_authority: int = 3,
        min_rerank: float = 1.5,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.timeout = timeout
        self._client = client
        self.refs_dir = Path(refs_dir)
        self.root = Path(root)
        self.min_authority = min_authority
        self.min_rerank = min_rerank

    def _http(self):
        if self._client is not None:
            return self._client
        import httpx

        self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _post(self, url: str, payload: dict) -> dict:
        client = self._http()
        try:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json() or {}
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"DeepSeek 检索失败：{exc}") from exc

    def resolve(self, style: dict) -> MediaResult | None:
        query = str(style.get("search_query") or "").strip()
        if not self.api_key:
            raise ProviderError("SearchProvider 缺少 DEEPSEEK_API_KEY")
        if not query:
            return None
        data = self._post(self.SEARCH_URL, {"query": query, "count": 10})
        results = data.get("results") or []
        candidates = [
            item
            for item in results
            if int(item.get("authority") or -1) >= self.min_authority
            and float(item.get("rerank_score") or 0.0) >= self.min_rerank
            and item.get("url")
        ]
        candidates.sort(key=lambda item: float(item.get("rerank_score") or 0.0), reverse=True)
        for item in candidates[:3]:
            page = self._post(self.FETCH_URL, {"url": item["url"]})
            content = str(page.get("content") or "")
            match = _MD_IMAGE_RE.search(content)
            if not match:
                continue
            image = _download_image(
                self._http(),
                match.group(1),
                self.refs_dir,
                str(style.get("id") or "style"),
                self.timeout,
                root=self.root,
            )
            if image:
                return MediaResult(
                    image=image,
                    source_url=str(item.get("url")),
                    license="unknown",
                    provider=self.name,
                    relevance=round(float(item.get("rerank_score") or 0.0), 1),
                    fetched_at=_today(),
                    verified=False,
                    note=f"来源：{item.get('site_name') or '公开网页'}，仅风格参考",
                )
        return None

    def search_sources(self, query: str, *, count: int = 5) -> list[dict]:
        """只做一次 Search 请求，返回干净的文本来源（不 Fetch、不下载图片）。

        供 scripts/web_sources.py 输出「当前趋势 / 参考链接」使用。
        字段：title / url / site / date / summary / authority / relevance。
        """
        if not self.api_key:
            raise ProviderError("SearchProvider 缺少 DEEPSEEK_API_KEY")
        query = str(query or "").strip()
        if not query:
            return []
        data = self._post(self.SEARCH_URL, {"query": query, "count": max(int(count), 1)})
        sources: list[dict] = []
        for item in data.get("results") or []:
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            sources.append(
                {
                    "title": title,
                    "url": url,
                    "site": str(item.get("site_name") or "").strip(),
                    "date": str(item.get("date") or "").strip(),
                    "summary": str(item.get("summary") or item.get("snippet") or "").strip(),
                    "authority": int(item.get("authority") or -1),
                    "relevance": round(float(item.get("rerank_score") or 0.0), 2),
                }
            )
        sources.sort(key=lambda source: source["relevance"], reverse=True)
        return sources[:count]


# ---------------------------------------------------------------- Openverse


def _openverse_text(item: dict) -> str:
    """标题 + tags 拼成小写文本：Openverse 标题常是 IMG_1234，相关性主要看 tags。"""
    parts = [str(item.get("title") or "")]
    for tag in item.get("tags") or []:
        if isinstance(tag, dict):
            name = str(tag.get("name") or "").strip()
            if name:
                parts.append(name)
    return " ".join(parts).lower()


def openverse_queries(style: dict) -> list[str]:
    """款式 → Openverse 英文检索词（从具体到宽泛，逐个兜底）。

    为什么不用 search_query：库里是中文，Openverse 是英文全文检索；
    实测长查询（如 "nude pink french manicure oval"）会 0 结果，
    所以用枚举字段拼短查询，并准备降级链。
    """
    family = _OPENVERSE_FAMILY_WORDS.get(str(style.get("color_family") or ""))
    style_word = _OPENVERSE_STYLE_WORDS.get(str(style.get("style") or ""))
    shape = next(
        (
            _OPENVERSE_SHAPE_WORDS[str(shape)]
            for shape in style.get("shape") or []
            if shape in _OPENVERSE_SHAPE_WORDS
        ),
        None,
    )
    words = [word for word in (family, style_word, shape) if word]
    queries: list[str] = []
    if words:
        joined = " ".join(words)
        queries.append(joined if "manicure" in joined else joined + " nails")
    if family:
        queries.append(family + " nails")
    if style_word:
        queries.append(style_word if style_word.endswith("manicure") else style_word + " nails")
    queries.append("nails")
    unique: list[str] = []
    for query in queries:
        query = query.strip()
        if query and query not in unique:
            unique.append(query)
    return unique


def _openverse_relevance(style: dict, item: dict) -> float:
    """0-5 的相关性：必须出现美甲词（2 分），再按款式/色系/甲型词命中加分。"""
    text = _openverse_text(item)
    if not any(token in text for token in _NAIL_TOKENS):
        return 0.0
    score = 2.0
    for word in openverse_queries(style)[0].split():
        if word in ("nail", "nails", "manicure", "manicures"):
            continue
        if word in text:
            score += 0.5
    return round(min(score, 5.0), 1)


class OpenverseProvider:
    """Openverse（免 Key 的 CC 图源）：产出候选参考图，默认不进图片链。

    实测（2026-10-26）：搜索可用；但标题相关性不稳定（搜 cat eye 可能命中
    「Cat Processing 101」），因此这里做三道过滤：CC 许可白名单、长边尺寸、
    「标题/tags 必须出现美甲词」。即便如此结果仍需人工复核，脚本只产出
    候选清单（scripts/openverse_candidates.py），不自动写正式库。

    网络需求：本机访问 Openverse 需代理，传 proxy="http://127.0.0.1:10090"
    或设置 HTTPS_PROXY 环境变量（httpx 默认 trust_env）。
    """

    name = "openverse"

    def __init__(
        self,
        *,
        timeout: float = 8.0,
        client=None,
        refs_dir: str | Path = DEFAULT_REFS_DIR,
        root: str | Path = ROOT,
        licenses: tuple[str, ...] = OPENVERSE_LICENSES,
        min_edge: int = OPENVERSE_MIN_EDGE,
        proxy: str | None = None,
        retries: int = 1,
    ) -> None:
        self.timeout = timeout
        self._client = client
        self.refs_dir = Path(refs_dir)
        self.root = Path(root)
        self.licenses = tuple(licenses)
        self.min_edge = min_edge
        self.proxy = proxy
        self.retries = retries

    def _http(self):
        if self._client is not None:
            return self._client
        import httpx

        kwargs: dict = {"timeout": self.timeout, "follow_redirects": True}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        self._client = httpx.Client(**kwargs)
        return self._client

    # ------------------------------------------------------------ 检索
    def _request(self, query: str, *, limit: int) -> dict:
        client = self._http()
        params = {
            "q": query,
            "page_size": max(limit * 2, 6),
            "license": ",".join(self.licenses),
            "mature": "false",
        }
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                response = client.get(OPENVERSE_API_URL, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json() or {}
            except Exception as exc:  # noqa: BLE001 - 检索失败统一转 ProviderError
                last_error = exc
        raise ProviderError(f"Openverse 检索失败（{query}）：{last_error}")

    def _candidate(self, style: dict, item: dict) -> dict | None:
        image_url = str(item.get("url") or "").strip()
        landing = str(item.get("foreign_landing_url") or "").strip()
        license_name = str(item.get("license") or "").lower()
        if not image_url or not landing or license_name not in self.licenses:
            return None
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if max(width, height) < self.min_edge:
            return None
        relevance = _openverse_relevance(style, item)
        if relevance < 2.0:
            return None
        version = str(item.get("license_version") or "").strip()
        detail = f"CC {license_name.upper()}" + (f" {version}" if version else "")
        return {
            "title": str(item.get("title") or "").strip(),
            "creator": str(item.get("creator") or "").strip(),
            "license": license_name,
            "license_version": version,
            "license_detail": detail,
            "attribution": str(item.get("attribution") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "category": str(item.get("category") or "").strip(),
            "foreign_landing_url": landing,
            "image_url": image_url,
            "width": width,
            "height": height,
            "relevance": relevance,
        }

    def search(self, style: dict, *, limit: int = 3) -> list[dict]:
        """按降级查询链检索，返回通过过滤的候选（未下载）。"""
        seen: set[str] = set()
        found: list[dict] = []
        for query in openverse_queries(style)[:3]:
            payload = self._request(query, limit=limit)
            for item in payload.get("results") or []:
                candidate = self._candidate(style, item)
                if candidate and candidate["image_url"] not in seen:
                    seen.add(candidate["image_url"])
                    found.append(candidate)
            if len(found) >= limit:
                break
        found.sort(
            key=lambda item: (
                item["relevance"] + (0.5 if item.get("category") == "photograph" else 0.0),
                min(item["width"], item["height"]),
            ),
            reverse=True,
        )
        return found[:limit]

    # ------------------------------------------------------------ 下载
    def candidates(
        self, style: dict, *, limit: int = 3, out_dir: str | Path | None = None
    ) -> list[dict]:
        """检索并下载候选图到缓存目录，返回带本地路径的候选清单。"""
        target = Path(out_dir) if out_dir else self.root / ".cache" / "openverse"
        style_id = str(style.get("id") or "style")
        recorded: list[dict] = []
        for rank, item in enumerate(self.search(style, limit=limit), start=1):
            local = _download_image(
                self._http(),
                item["image_url"],
                target / style_id,
                f"{rank:02d}",
                self.timeout,
                root=self.root,
            )
            if not local:
                continue
            record = dict(item)
            record["rank"] = rank
            record["local_image"] = local
            recorded.append(record)
        return recorded

    def resolve(self, style: dict) -> MediaResult | None:
        """直接解析出一张参考图（写入 refs_dir）；正式入库前仍需人工复核。"""
        results = self.search(style, limit=1)
        if not results:
            return None
        item = results[0]
        image = _download_image(
            self._http(),
            item["image_url"],
            self.refs_dir,
            str(style.get("id") or "style"),
            self.timeout,
            root=self.root,
        )
        if not image:
            return None
        return MediaResult(
            image=image,
            source_url=item["foreign_landing_url"],
            license="openverse",
            provider=self.name,
            relevance=item["relevance"],
            fetched_at=_today(),
            verified=False,
            note=f"Openverse · {item['creator']} · {item['license_detail']} · 候选图，需人工复核",
            creator=item["creator"],
            license_detail=item["license_detail"],
        )


class MediaResolver:
    """媒体解析器：缓存 → Provider 链 → 占位。

    - `resolve_style(..., allow_network=False)`：只读缓存 + 本地图，推荐请求用这个。
    - `resolve_style(..., allow_network=True)`：允许联网 Provider，prefetch 脚本用这个。
    """

    def __init__(
        self,
        cache_path: str | Path | None = None,
        *,
        root: str | Path = ROOT,
        refs_dir: str | Path = DEFAULT_REFS_DIR,
        ttl_days: int = 30,
        timeout: float = 3.0,
        client=None,
    ) -> None:
        self.root = Path(root)
        self.refs_dir = Path(refs_dir)
        self.cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
        self.ttl_days = ttl_days
        self.timeout = timeout
        self.client = client
        self._cache: dict[str, dict] | None = None
        self.dirty = False

    # ---------------------------------------------------------------- 缓存
    def load_cache(self) -> dict[str, dict]:
        if self._cache is not None:
            return self._cache
        items: dict[str, dict] = {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            raw = data.get("items") if isinstance(data, dict) else None
            if isinstance(raw, dict):
                items = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            items = {}
        self._cache = items
        return items

    def save_cache(self) -> None:
        if not self.dirty:
            return
        payload = {
            "version": 1,
            "updated_at": _now_iso(),
            "items": self.load_cache(),
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.cache_path)
        self.dirty = False

    def _fresh(self, media: dict) -> bool:
        if media.get("provider") in ("local", "none") or media.get("license") in (
            "demo",
            "self",
            "placeholder",
        ):
            return True  # 本地图不会“过期”
        fetched = str(media.get("fetched_at") or "")
        if not fetched:
            return False
        try:
            fetched_date = date.fromisoformat(fetched[:10])
        except ValueError:
            return False
        return (date.today() - fetched_date).days <= self.ttl_days

    # ---------------------------------------------------------------- 解析
    def default_providers(self) -> list:
        providers: list = [LocalProvider(self.root)]
        if os.environ.get("PEXELS_API_KEY"):
            providers.append(
                PexelsProvider(timeout=self.timeout, client=self.client, refs_dir=self.refs_dir)
            )
        # 2026-10-26 实测：DeepSeek Fetch 只返回纯文本、不含图片，故 SearchProvider
        # 不进入默认图片链，避免无谓计费。文本来源请用 scripts/web_sources.py。
        return providers

    def resolve_style(
        self,
        style: dict,
        *,
        providers: list | None = None,
        allow_network: bool = False,
        force: bool = False,
    ) -> dict:
        style_id = str(style.get("id") or "")
        cached = self.load_cache().get(style_id)
        if cached and not force and self._fresh(cached):
            return dict(cached)

        chain = providers if providers is not None else self.default_providers()
        last_error: str | None = None
        for provider in chain:
            if not allow_network and provider.name != "local":
                continue
            try:
                result = provider.resolve(style)
            except ProviderError as exc:
                last_error = str(exc)
                continue
            except Exception as exc:  # noqa: BLE001 - 第三方 Provider 的意外错误也要降级
                last_error = f"{provider.name}: {exc}"
                continue
            if result is None:
                continue
            media = result.to_dict()
            self.load_cache()[style_id] = media
            self.dirty = True
            return dict(media)

        return empty_media(
            f"媒体解析失败：{last_error}" if last_error else PLACEHOLDER_NOTE
        )

    def resolve_many(
        self,
        styles: list[dict] | tuple[dict, ...],
        *,
        providers: list | None = None,
        allow_network: bool = False,
        force: bool = False,
        limit: int | None = None,
    ) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for style in styles[: limit if limit else None]:
            style_id = str(style.get("id") or "")
            if not style_id:
                continue
            result[style_id] = self.resolve_style(
                style,
                providers=providers,
                allow_network=allow_network,
                force=force,
            )
        return result


def resolve_card_media(
    styles_by_id: dict[str, dict],
    style_ids: list[str],
    *,
    cache_path: str | Path | None = None,
) -> dict[str, dict]:
    """展示层专用：只读缓存 + 样式自带图，绝不联网。

    pipeline 出卡后调用；返回的 dict 直接挂到 card["media"] 上。
    """
    resolver = MediaResolver(cache_path=cache_path)
    result: dict[str, dict] = {}
    for style_id in style_ids:
        style = styles_by_id.get(style_id)
        if not style:
            result[style_id] = empty_media()
            continue
        result[style_id] = resolver.resolve_style(
            style,
            providers=[LocalProvider(resolver.root)],
            allow_network=False,
        )
    return result

"""媒体解析层：文本款式 → 参考图 + 来源。

为什么单独一层：
- 推荐决策不依赖网络：core/pipeline.py 只负责「推荐哪三款」，媒体解析只服务展示。
- 缓存优先：scripts/prefetch_media.py 用 Provider 预先抓图写 data/media_cache.json，
  展示层只读缓存 / 样式自带图（毫秒级、可复现、离线可跑）。
- 失败必须降级：没图就返回占位信息，卡片退化成纯文字，绝不阻塞推荐。
- 授权必须可标注：每张图带 license / source_url，前端据此显示「风格参考」与来源。

解析顺序：缓存（未过期）→ LocalProvider（static/ 下已有图）→ 网络 Provider → 占位。
网络 Provider（Pexels / DeepSeek Search）只在 prefetch 时启用（allow_network=True），
推荐请求路径默认不联网。
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

LICENSES = ("demo", "self", "pexels", "unsplash", "unknown", "placeholder")
LICENSE_LABELS = {
    "demo": "工程演示素材",
    "self": "自摄 / 自有授权",
    "pexels": "Pexels（可商用）",
    "unsplash": "Unsplash（可商用）",
    "unknown": "公开网页",
    "placeholder": "占位",
}
REFERENCE_TAIL = "仅风格参考，非本手模拟效果"
PLACEHOLDER_NOTE = "暂无参考图：检索层未命中，仅展示文字推荐"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)")
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


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
    if license_name == "placeholder" or not media.get("image"):
        return "暂无参考图 · 仅展示文字推荐"
    if license_name in ("pexels", "unsplash"):
        return f"图片：{label} · {REFERENCE_TAIL}"
    if license_name == "self":
        return f"图片：{label} · {REFERENCE_TAIL}"
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
            license=str(media.get("license") or "demo"),
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

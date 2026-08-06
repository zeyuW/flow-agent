"""文本向量化组件：使用 OpenAI embeddings API 将文本转换为向量。

如果无 API key，降级为简单的关键词频率向量（纯本地 fallback）。
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """文本向量化接口。"""

    def embed(self, text: str) -> list[float]:
        ...

    @property
    def dimension(self) -> int:
        ...


class OpenAIEmbedder:
    """使用 OpenAI text-embedding-3-small 模型进行文本向量化。"""

    def __init__(
        self,
        api_key: str = "",
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
        cache_path: Path | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.dim = 1536
        self._cache: dict[str, list[float]] = {}
        self._cache_path = cache_path
        self._load_cache()

    @property
    def dimension(self) -> int:
        return self.dim

    def embed(self, text: str) -> list[float]:
        if not text.strip():
            return [0.0] * self.dim
        cache_key = self._hash_key(text)
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            vec = self._call_api(text)
        except Exception:
            logger.warning("embedding API failed, using hash fallback")
            vec = self._hash_fallback(text)
        self._cache[cache_key] = vec
        self._save_cache()
        return vec

    def _call_api(self, text: str) -> list[float]:
        """调用 OpenAI embeddings API。"""
        import importlib

        client_mod = importlib.import_module("openai")
        client = client_mod.OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.embeddings.create(model=self.model, input=text)
        emb = resp.data[0].embedding
        self.dim = len(emb)
        return list(emb)

    def _hash_fallback(self, text: str) -> list[float]:
        """纯本地 hash fallback：将文本 hash 展开为伪向量，用于无 API 场景。"""
        text_bytes = text.encode("utf-8")
        h = hashlib.sha256(text_bytes).digest()
        vec: list[float] = []
        for i in range(min(128, self.dim)):
            byte_val = h[i % len(h)]
            vec.append((byte_val / 255.0) * 2.0 - 1.0)
        if len(vec) < self.dim:
            vec.extend([0.0] * (self.dim - len(vec)))
        return vec

    def _hash_key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _load_cache(self) -> None:
        if self._cache_path and self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text("utf-8"))
                self._cache = data
            except Exception:
                pass

    def _save_cache(self) -> None:
        if self._cache_path:
            try:
                self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                self._cache_path.write_text(json.dumps(self._cache, ensure_ascii=False), "utf-8")
            except Exception:
                pass

"""基于 pycorrector 的轻量级中文文本纠错服务

作为三阶段文本纠正流水线的阶段 2：
- 阶段 1：规则预处理（噪声过滤、重复词合并）
- 阶段 2：pycorrector/MacBERT 轻量级纠错（常见错别字）<-- 本模块
- 阶段 3：LLM 精细纠正（同音字、方言模糊匹配等复杂错误）

MacBERT-CSC 模型特点：
- SIGHAN2015 中文拼写纠错基准最佳效果
- GPU 内存占用约 400MB
- 适合处理常见错别字，减轻 LLM 负担

Author: afu
"""

import logging
from functools import lru_cache

from copernicus.config import Settings

logger = logging.getLogger(__name__)


class TextCorrectorService:
    """基于 pycorrector MacBERT 的中文文本纠错服务"""

    def __init__(self, settings: Settings) -> None:
        self._enabled = settings.pycorrector_enabled
        self._model_type = settings.pycorrector_model
        self._corrector = None
        self._initialized = False

    def _lazy_init(self) -> bool:
        """懒加载模型，避免启动时阻塞"""
        if self._initialized:
            return self._corrector is not None

        self._initialized = True

        if not self._enabled:
            logger.info("pycorrector disabled by configuration")
            return False

        try:
            if self._model_type == "macbert":
                from pycorrector import MacBertCorrector
                self._corrector = MacBertCorrector()
                logger.info("pycorrector MacBERT model loaded successfully")
            elif self._model_type == "kenlm":
                from pycorrector import Corrector
                self._corrector = Corrector()
                logger.info("pycorrector Kenlm model loaded successfully")
            else:
                logger.warning(
                    "Unknown pycorrector model type: %s, disabling",
                    self._model_type,
                )
                return False
            return True
        except ImportError as e:
            logger.warning(
                "pycorrector not installed, skipping Phase 2 correction: %s",
                e,
            )
            return False
        except Exception as e:
            logger.warning(
                "Failed to load pycorrector model: [%s] %s",
                type(e).__name__,
                e,
            )
            return False

    def correct(self, text: str) -> str:
        """纠正单条文本

        Args:
            text: 输入文本

        Returns:
            纠正后的文本，如果纠错器未启用或出错则返回原文
        """
        if not text or not text.strip():
            return text

        if not self._lazy_init():
            return text

        try:
            result = self._corrector.correct(text)
            corrected = result.get("target", text) if isinstance(result, dict) else text
            if corrected != text:
                errors = result.get("errors", []) if isinstance(result, dict) else []
                logger.debug(
                    "pycorrector: '%s' -> '%s' (errors=%s)",
                    text[:50],
                    corrected[:50],
                    errors,
                )
            return corrected
        except Exception as e:
            logger.warning(
                "pycorrector correction failed: [%s] %s",
                type(e).__name__,
                e,
            )
            return text

    def correct_batch(self, texts: list[str]) -> list[str]:
        """批量纠正文本

        Args:
            texts: 输入文本列表

        Returns:
            纠正后的文本列表
        """
        if not texts:
            return []

        if not self._lazy_init():
            return texts

        results = []
        corrected_count = 0
        for text in texts:
            corrected = self.correct(text)
            if corrected != text:
                corrected_count += 1
            results.append(corrected)

        if corrected_count > 0:
            logger.info(
                "pycorrector Phase 2: corrected %d/%d texts",
                corrected_count,
                len(texts),
            )

        return results

    def correct_entries(self, entries: list[dict]) -> list[dict]:
        """纠正 transcript entries

        Args:
            entries: 包含 {"id": int, "text": str} 的列表

        Returns:
            纠正后的 entries 列表，结构不变
        """
        if not entries:
            return []

        if not self._lazy_init():
            return entries

        results = []
        corrected_count = 0

        for entry in entries:
            text = entry.get("text", "")
            corrected = self.correct(text)
            if corrected != text:
                corrected_count += 1
            results.append({"id": entry["id"], "text": corrected})

        if corrected_count > 0:
            logger.info(
                "pycorrector Phase 2: corrected %d/%d entries",
                corrected_count,
                len(entries),
            )

        return results

    @property
    def is_available(self) -> bool:
        """检查纠错器是否可用"""
        return self._lazy_init()


@lru_cache(maxsize=1)
def get_text_corrector(settings: Settings) -> TextCorrectorService:
    """获取 TextCorrectorService 单例"""
    return TextCorrectorService(settings)

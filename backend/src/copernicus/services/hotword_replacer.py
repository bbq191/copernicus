"""基于 FlashText 的热词后处理替换服务

作为纠错 pipeline 的阶段 2：
- 阶段 1：规则预处理（噪声过滤、重复词合并、数字规范化）
- 阶段 2：热词强制替换（FlashText 多模式匹配） <-- 本模块
- 阶段 3：pycorrector/MacBERT 轻量级纠错
- 阶段 4：LLM 润色（去口语 + 倒装 + 标点）

hotwords.txt 扩展格式：
- 纯词行（如 `特朗普`）：ASR 保护词 + 自映射（防止后续层误改）
- 映射行（如 `全程双路->全程双录`）：纠错阶段强制替换
- `#` 开头为注释，空行忽略

Author: afu
"""

import logging
from pathlib import Path

from copernicus.config import Settings

logger = logging.getLogger(__name__)


class HotwordReplacerService:
    """基于 FlashText 的热词后处理替换服务"""

    def __init__(self, settings: Settings) -> None:
        self._enabled = settings.hotword_replacer_enabled
        self._hotwords_file = settings.hotwords_file
        self._processor = None
        self._asr_hotwords: list[str] = []
        self._mapping_count = 0
        self._protection_count = 0
        self._initialized = False

    def _lazy_init(self) -> bool:
        """懒加载 FlashText 和热词文件"""
        if self._initialized:
            return self._processor is not None

        self._initialized = True

        if not self._enabled:
            logger.info("HotwordReplacer disabled by configuration")
            return False

        if self._hotwords_file is None or not Path(self._hotwords_file).exists():
            logger.info("No hotwords file configured or file not found, HotwordReplacer inactive")
            return False

        try:
            from flashtext import KeywordProcessor

            processor = KeywordProcessor()
            asr_words: list[str] = []

            lines = Path(self._hotwords_file).read_text(encoding="utf-8").splitlines()
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if "->" in line:
                    # 映射行：错误词->正确词
                    parts = line.split("->", 1)
                    wrong = parts[0].strip()
                    correct = parts[1].strip()
                    if wrong and correct:
                        processor.add_keyword(wrong, correct)
                        self._mapping_count += 1
                        # 正确词侧也加入 ASR 热词
                        asr_words.append(correct)
                else:
                    # 纯词行：保护词（自映射 + ASR 热词）
                    processor.add_keyword(line, line)
                    self._protection_count += 1
                    asr_words.append(line)

            self._processor = processor
            self._asr_hotwords = asr_words

            logger.info(
                "HotwordReplacer loaded: %d protection words, %d correction mappings from %s",
                self._protection_count,
                self._mapping_count,
                self._hotwords_file,
            )
            return True

        except ImportError:
            logger.warning(
                "flashtext not installed, HotwordReplacer disabled. "
                "Install with: pip install flashtext"
            )
            return False
        except Exception as e:
            logger.warning(
                "Failed to load hotwords file: [%s] %s",
                type(e).__name__,
                e,
            )
            return False

    def replace(self, text: str) -> str:
        """替换单条文本中的热词

        Args:
            text: 输入文本

        Returns:
            替换后的文本，如果服务未启用则返回原文
        """
        if not text or not text.strip():
            return text

        if not self._lazy_init():
            return text

        replaced = self._processor.replace_keywords(text)
        if replaced != text:
            logger.debug("HotwordReplacer: '%s' -> '%s'", text[:80], replaced[:80])
        return replaced

    def replace_entries(self, entries: list[dict]) -> list[dict]:
        """批量替换 transcript entries 中的热词

        Args:
            entries: 包含 {"id": int, "text": str} 的列表

        Returns:
            替换后的 entries 列表
        """
        if not entries:
            return []

        if not self._lazy_init():
            return entries

        results = []
        replaced_count = 0

        for entry in entries:
            text = entry.get("text", "")
            replaced = self._processor.replace_keywords(text) if text else text
            if replaced != text:
                replaced_count += 1
            results.append({"id": entry["id"], "text": replaced})

        if replaced_count > 0:
            logger.info(
                "HotwordReplacer Phase 2: replaced %d/%d entries",
                replaced_count,
                len(entries),
            )

        return results

    def get_asr_hotwords(self) -> list[str]:
        """返回 ASR 引擎使用的热词列表（保护词 + 映射正确词侧）"""
        self._lazy_init()
        return list(self._asr_hotwords)

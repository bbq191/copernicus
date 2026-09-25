"""ChatTTS 多说话人对话合成服务。

安装依赖：
    pip install ChatTTS soundfile

VRAM 预估：~4 GB
推理时需通过 ModelManager.use("tts", exclusive=True) 独占显存，ASR 模型将被自动卸载。
每次推理文本不超过 tts_max_sentence_chars 字，防止 Attention 矩阵爆炸导致 OOM 和幻读。
"""

import gc
import hashlib
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from copernicus.utils.ffmpeg import run as ffmpeg_run

_CHATTTS_TOKEN_RE = re.compile(r'\[[a-z_]+(?:_\d+)?\]')

# ChatTTS 仅支持将这三个 token 内联在文本中；
# [speed_N]/[oral_N]/[laugh_N] 等必须通过 InferCodeParams/RefineTextParams 传入，
# 内联会导致 tokenizer 混乱并触发"这个这个这个"幻读。
_VALID_INLINE_TOKENS = frozenset({"[uv_break]", "[v_break]", "[lbreak]", "[laugh]"})


def _normalize_inline_tokens(text: str) -> str:
    """只保留 ChatTTS 合法内联 token，移除 [speed_N]、[laugh_N] 等非法 inline 控制符。"""
    return _CHATTTS_TOKEN_RE.sub(
        lambda m: m.group(0) if m.group(0) in _VALID_INLINE_TOKENS else "", text
    )

import numpy as np
import soundfile as sf

from copernicus.config import Settings
from copernicus.schemas.transcription import TranscriptEntrySchema

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000


def _voice_to_seed(voice_id: str) -> int:
    """将音色标识映射为 ChatTTS 随机种子。纯数字字符串直接转换，否则 MD5 哈希。"""
    if voice_id.isdigit():
        return int(voice_id)
    return int(hashlib.md5(voice_id.encode()).hexdigest()[:8], 16) % (2**16)


class _ChatTTSHandle:
    """持有 ChatTTS.Chat 实例及预采样的音色向量缓存。"""

    def __init__(self, chat):
        self.chat = chat
        self._speaker_cache: dict[int, object] = {}

    def get_speaker(self, seed: int):
        if seed not in self._speaker_cache:
            import torch
            torch.manual_seed(seed)
            self._speaker_cache[seed] = self.chat.sample_random_speaker()
        return self._speaker_cache[seed]

    def synthesize(self, sentence: str, seed: int, params: "SynthesisParams") -> np.ndarray:
        """合成一句话，返回 float32 音频。依赖 ChatTTS 的部分都收在这里，便于测试时替换整个 handle。"""
        import ChatTTS
        import torch

        infer_params = ChatTTS.Chat.InferCodeParams(
            spk_emb=self.get_speaker(seed),
            prompt=f"[speed_{params.speed}]",
            temperature=params.temperature,
            top_P=params.top_p,
            top_K=params.top_k,
            max_new_token=params.max_new_token,
        )
        refine_params = ChatTTS.Chat.RefineTextParams(
            prompt=f"[oral_{params.oral_level}][laugh_{params.laugh_level}][break_{params.break_level}]"
        )
        # 每句推理前锁定同一随机种子，保持音色前后一致
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)
        wavs = self.chat.infer(
            [sentence],
            params_infer_code=infer_params,
            params_refine_text=refine_params,
            use_decoder=True,
        )
        return wavs[0].astype(np.float32)


def load_chattts(model_dir: Path | None = None) -> _ChatTTSHandle:
    """供 ModelManager.register_loader 使用的加载函数。

    model_dir 指向包含 safetensors 权重的本地目录（settings.chattts_model_dir）。
    传 None 时让 ChatTTS 自行查找默认路径（HuggingFace 缓存）。
    """
    import ChatTTS
    chat = ChatTTS.Chat()
    if model_dir is not None:
        ok = chat.load(source="local", custom_path=str(model_dir), compile=False)
    else:
        ok = chat.load(compile=False)
    if not ok:
        raise RuntimeError(f"ChatTTS load() returned False — check model files in {model_dir}")
    return _ChatTTSHandle(chat)


def unload_chattts(model: _ChatTTSHandle) -> None:
    """供 ModelManager 使用的卸载函数。"""
    import torch
    model._speaker_cache.clear()
    del model.chat
    gc.collect()
    torch.cuda.empty_cache()


def build_voice_map(
    speakers: list[str],
    default_voices: list[str],
    override: dict[str, str] | None = None,
) -> dict[str, str]:
    """将去重后的说话人 ID 按出现顺序循环分配到音色池，可选覆盖。

    default_voices 中的纯数字字符串直接用作 ChatTTS seed，
    其他字符串通过 MD5 映射为 seed（兼容自定义音色名）。
    """
    seen: list[str] = []
    for spk in speakers:
        if spk not in seen:
            seen.append(spk)
    result = {spk: default_voices[i % len(default_voices)] for i, spk in enumerate(seen)}
    if override:
        result.update(override)
    return result


def merge_by_speaker(
    transcript: list[TranscriptEntrySchema],
) -> list[tuple[str, str]]:
    """将连续相同 speaker 的段落合并为一个文本块（保留出场顺序）。

    块间用句号分隔，引导 TTS 在句子边界自然换气停顿。
    单段超过 60 字时强制分段，防止超长合并导致语调呆板。
    """
    MAX_CHUNK_CHARS = 60
    chunks: list[tuple[str, str]] = []
    for entry in transcript:
        text = (entry.text_corrected or entry.text).strip()
        if not text:
            continue
        if chunks and chunks[-1][0] == entry.speaker and len(chunks[-1][1]) < MAX_CHUNK_CHARS:
            chunks[-1] = (chunks[-1][0], chunks[-1][1] + "。" + text)
        else:
            chunks.append((entry.speaker, text))
    return chunks


_DIGIT_MAP = str.maketrans("0123456789", "零一二三四五六七八九")
_INVALID_CHARS = str.maketrans({
    "！": "，",   # 全角感叹号 → 停顿（ChatTTS 不识别，转为逗号保留节奏）
    "（": "，",   # 全角括号 → 停顿
    "）": "，",
    "(": "，",
    ")": "，",
    "＊": "",    # 全角星号（LLM markdown 强调符）→ 删除
    "*":  "",    # 半角星号
    "【": "，",
    "】": "，",
    "「": "，",
    "」": "，",
    "《": "",
    "》": "",
    "—": "，",   # 破折号 → 停顿
    "…": "，",   # 省略号 → 停顿
})


def _sanitize_for_chattts(text: str) -> str:
    """移除 ChatTTS tokenizer 不支持的字符，保留原生控制 token（如 [speed_9]、[uv_break]）。

    用 re.split/findall 将文本拆成"普通文本"和"控制 token"交替片段，
    只对普通文本做字符转换，控制 token 原样保留后重新拼回，
    彻底避免 placeholder 内数字被 _DIGIT_MAP 误转的问题。
    """
    text_parts = _CHATTTS_TOKEN_RE.split(text)
    token_parts = _CHATTTS_TOKEN_RE.findall(text)

    result: list[str] = []
    for i, part in enumerate(text_parts):
        result.append(part.translate(_DIGIT_MAP).translate(_INVALID_CHARS))
        if i < len(token_parts):
            result.append(token_parts[i])

    return "".join(result).strip()


def _slice_sentences(text: str, max_chars: int) -> list[str]:
    """按标点切分文本，每段不超过 max_chars 字。

    ChatTTS 对长文本的 Attention 矩阵敏感，切片是防 OOM 和幻读的核心机制。
    """
    parts = re.split(r'([。！？；，,\n])', text)
    sentences: list[str] = []
    current = ""
    for part in parts:
        current += part
        if len(current) >= max_chars or part in {'。', '！', '？', '；', '\n'}:
            if current.strip():
                sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())
    return sentences or [text]


def _energy_to_speed(energy: int) -> int:
    """将激情等级（0-9）映射为 ChatTTS speed token（1-9）。"""
    return max(1, min(9, round(1 + energy * 0.88)))


def _apply_fade(wav: np.ndarray, fade_ms: float = 8.0) -> np.ndarray:
    """对音频片段施加线性淡入淡出，消除拼接边界的咔哒声。"""
    fade_samples = int(SAMPLE_RATE * fade_ms / 1000)
    if len(wav) < fade_samples * 2:
        return wav
    result = wav.copy()
    ramp = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    result[:fade_samples] *= ramp
    result[-fade_samples:] *= ramp[::-1]
    return result


@dataclass(frozen=True)
class SynthesisParams:
    """一次合成的全部可调参数。合成链路各层只传这一个对象，不再逐层转发十几个参数。"""

    pause_switch_ms: int = 800        # 换说话人间隔（ms）
    batch_chars: int = 1000           # 每批最大字符数，批间清空 VRAM 缓存
    max_sentence_chars: int = 40      # 单次推理最大字符数，防 OOM 和幻读
    oral_level: int = 2
    break_level: int = 4
    laugh_level: int = 0
    energy_level: int = 5
    temperature: float = 0.1
    top_p: float = 0.7
    top_k: int = 20
    max_new_token: int = 2048

    @property
    def speed(self) -> int:
        """ChatTTS speed token（1-9）。energy >= 8 时上限为 7：[speed_8/9] 配合高温会触发幻读，
        [speed_6/7] + 逗号驱动文本在听感上已经足够紧凑。"""
        speed = _energy_to_speed(self.energy_level)
        return min(7, speed) if self.energy_level >= 8 else speed

    @classmethod
    def from_settings(cls, settings: Settings) -> "SynthesisParams":
        return cls(
            pause_switch_ms=settings.tts_pause_switch_speaker_ms,
            batch_chars=settings.tts_synthesis_batch_chars,
            max_sentence_chars=settings.tts_max_sentence_chars,
            oral_level=settings.tts_oral_level,
            break_level=settings.tts_break_level,
            laugh_level=settings.tts_laugh_level,
            energy_level=settings.tts_energy_level,
            temperature=settings.tts_temperature,
            top_p=settings.tts_top_p,
            top_k=settings.tts_top_k,
            max_new_token=settings.tts_max_new_token,
        )


def _free_gpu_cache() -> None:
    """释放 PyTorch 缓存的显存；无 GPU（CPU 模式）时什么也不做。"""
    import torch

    if torch.cuda.is_available():
        torch.cuda.synchronize()
        gc.collect()
        torch.cuda.empty_cache()


def _synthesize_chunks(
    chunks: list[tuple[str, str]],
    model: _ChatTTSHandle,
    voice_map: dict[str, str],
    params: SynthesisParams,
) -> np.ndarray:
    """合成一批预处理的 (speaker, text) 块，返回拼接后的 float32 音频数组。"""
    import torch

    pause = np.zeros(int(SAMPLE_RATE * params.pause_switch_ms / 1000), dtype=np.float32)
    sentence_gap = np.zeros(int(SAMPLE_RATE * 0.08), dtype=np.float32)  # 80ms，过长静音会加重拼接感
    segments: list[np.ndarray] = []
    prev_speaker: str | None = None

    for speaker, text in chunks:
        seed = _voice_to_seed(voice_map.get(speaker, "2222"))

        # 先清除 LLM 可能残留的 inline token（[uv_break] 等），逗号和句号已足够驱动节奏
        sentences = [
            _sanitize_for_chattts(s)
            for s in _slice_sentences(_normalize_inline_tokens(text), params.max_sentence_chars)
        ]
        for i, sentence in enumerate(s for s in sentences if s.strip()):
            logger.debug("[%s] seed=%d synthesizing: %s", speaker, seed, sentence)
            try:
                wav = _apply_fade(model.synthesize(sentence, seed, params))
            except (torch.cuda.OutOfMemoryError, MemoryError):
                logger.warning("OOM on sentence (skipped): %s", sentence)
                _free_gpu_cache()
                continue

            if i == 0:
                if prev_speaker is not None:
                    segments.append(pause.copy())
                prev_speaker = speaker
            else:
                segments.append(sentence_gap.copy())
            segments.append(wav)
        # 显存缓存在批结束时统一释放：逐句 empty_cache 会让分配器反复归还再申请，反而更慢

    return np.concatenate(segments) if segments else np.array([], dtype=np.float32)


def _split_into_batches(chunks: list[tuple[str, str]], batch_chars: int) -> list[list[tuple[str, str]]]:
    """按字符数把 chunks 分成若干批：批与批之间清空显存缓存，防止长文本累积碎片。"""
    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_chars = 0
    for chunk in chunks:
        chunk_len = len(chunk[1])
        if current and current_chars + chunk_len > batch_chars:
            batches.append(current)
            current, current_chars = [chunk], chunk_len
        else:
            current.append(chunk)
            current_chars += chunk_len
    if current:
        batches.append(current)
    return batches


def synthesize_chunks_batched(
    chunks: list[tuple[str, str]],
    model: _ChatTTSHandle,
    voice_map: dict[str, str],
    params: SynthesisParams,
    work_dir: Path,
) -> list[Path]:
    """把 chunks 分批合成为 WAV 文件，返回各批的临时路径。"""
    import torch

    batches = _split_into_batches(chunks, params.batch_chars)
    parts: list[Path] = []

    for idx, batch in enumerate(batches):
        logger.info(
            "Batch %d/%d (%d chars, %d chunks)",
            idx + 1, len(batches), sum(len(c[1]) for c in batch), len(batch),
        )
        audio = _synthesize_chunks(batch, model, voice_map, params)
        if len(audio) == 0:
            logger.warning("Batch %d/%d produced no audio, skipping", idx + 1, len(batches))
            continue

        part_path = work_dir / f"synthesis_part_{len(parts)}.wav"
        sf.write(str(part_path), audio, SAMPLE_RATE)
        parts.append(part_path)

        del audio
        _free_gpu_cache()
        if torch.cuda.is_available():
            logger.info(
                "Batch %d/%d done → %s | VRAM alloc=%.2fGB reserved=%.2fGB",
                idx + 1, len(batches), part_path.name,
                torch.cuda.memory_allocated() / 1024**3,
                torch.cuda.memory_reserved() / 1024**3,
            )

    return parts


async def concat_parts_to_mp3(parts: list[Path], dest: Path) -> None:
    """将多个 WAV 片段用 ffmpeg 拼接并编码为 192k MP3。"""
    concat_list: Path | None = None
    if len(parts) == 1:
        source_args = ["-i", str(parts[0])]
    else:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            concat_list = Path(f.name)
            for p in parts:
                f.write(f"file '{p}'\n")
        source_args = ["-f", "concat", "-safe", "0", "-i", str(concat_list)]
    try:
        cmd = ["ffmpeg", "-y", *source_args, "-codec:a", "libmp3lame", "-b:a", "192k", str(dest)]
        rc, stderr = await ffmpeg_run(cmd, timeout=300)
        if rc != 0:
            raise RuntimeError(f"ffmpeg MP3 encode failed: {stderr}")
    finally:
        if concat_list is not None:
            concat_list.unlink(missing_ok=True)

"""ChatTTS 多说话人对话合成服务。

安装依赖：
    pip install ChatTTS soundfile

VRAM 预估：~4 GB
推理时需通过 ModelManager.acquire("tts") 独占显存，ASR/LLM 模型将被自动卸载。
每次推理文本不超过 tts_max_sentence_chars 字，防止 Attention 矩阵爆炸导致 OOM 和幻读。
"""

import gc
import hashlib
import logging
import re
import tempfile
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


def _merge_by_speaker(
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


def _split_by_uv_break(text: str, max_actual_chars: int) -> list[str]:
    """将含 [uv_break] 的文本按换气点分组，每组实际文字（去除 token）不超过 max_actual_chars。

    防止整段过长触发 ChatTTS 的 'hit max_new_token: 384' 截断；
    每组保留自己的控制 token，ChatTTS 仍能处理换气和笑声效果。
    """
    parts = re.split(r'(?=\[uv_break\])', text)
    groups: list[str] = []
    current = ""
    for part in parts:
        candidate = current + part
        actual_len = len(_CHATTTS_TOKEN_RE.sub("", candidate))
        if current and actual_len > max_actual_chars:
            groups.append(current.strip())
            current = part
        else:
            current = candidate
    if current.strip():
        groups.append(current.strip())
    return groups or [text]


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


def _synthesize_chunks(
    chunks: list[tuple[str, str]],
    model: _ChatTTSHandle,
    voice_map: dict[str, str],
    pause_switch_ms: int,
    max_sentence_chars: int,
    oral_level: int,
    break_level: int,
    laugh_level: int = 0,
    energy_level: int = 5,
    temperature: float = 0.1,
    top_p: float = 0.7,
    top_k: int = 20,
    max_new_token: int = 2048,
) -> np.ndarray:
    """合成一批预处理的 (speaker, text) 块，返回拼接后的 float32 音频数组。"""
    import ChatTTS
    import torch

    pause = np.zeros(int(SAMPLE_RATE * pause_switch_ms / 1000), dtype=np.float32)
    sentence_gap = np.zeros(int(SAMPLE_RATE * 0.08), dtype=np.float32)  # 80ms，过长静音会加重拼接感
    segments: list[np.ndarray] = []
    prev_speaker: str | None = None

    for speaker, text in chunks:
        voice_id = voice_map.get(speaker, "2222")
        seed = _voice_to_seed(voice_id)
        spk_emb = model.get_speaker(seed)
        # energy >= 8 时速度上限为 7：[speed_8/9] 配合高温会触发幻读，
        # [speed_6/7] + 逗号驱动文本在听感上已经足够紧凑。
        speed = min(7, _energy_to_speed(energy_level)) if energy_level >= 8 else _energy_to_speed(energy_level)
        params_infer = ChatTTS.Chat.InferCodeParams(
            spk_emb=spk_emb,
            prompt=f"[speed_{speed}]",
            temperature=temperature,
            top_P=top_p,
            top_K=top_k,
            max_new_token=max_new_token,
        )
        params_refine = ChatTTS.Chat.RefineTextParams(
            prompt=f"[oral_{oral_level}][laugh_{laugh_level}][break_{break_level}]"
        )

        # 先清除 LLM 可能残留的 inline token（[uv_break] 等），逗号和句号已足够驱动节奏
        sentences = [_sanitize_for_chattts(s) for s in _slice_sentences(_normalize_inline_tokens(text), max_sentence_chars)]
        sentences = [s for s in sentences if s.strip()]
        for i, sentence in enumerate(sentences):
            logger.debug("[%s] seed=%d synthesizing: %s", speaker, seed, sentence)
            try:
                # 每句推理前锁定同一随机种子，保持音色前后一致
                torch.manual_seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed(seed)
                wavs = model.chat.infer(
                    [sentence],
                    params_infer_code=params_infer,
                    params_refine_text=params_refine,
                    use_decoder=True,
                )
            except torch.cuda.OutOfMemoryError:
                logger.warning("OOM on sentence (skipped): %s", sentence)
                torch.cuda.empty_cache()
                continue

            wav = _apply_fade(wavs[0].astype(np.float32))

            if i == 0:
                if prev_speaker is not None:
                    segments.append(pause.copy())
                prev_speaker = speaker
            else:
                segments.append(sentence_gap.copy())

            segments.append(wav)
            torch.cuda.empty_cache()

    return np.concatenate(segments) if segments else np.array([], dtype=np.float32)


def synthesize_dialogue(
    transcript: list[TranscriptEntrySchema],
    model: _ChatTTSHandle,
    voice_map: dict[str, str],
    pause_switch_ms: int,
) -> np.ndarray:
    """单批合成全部转写段落，返回 float32 numpy 数组（采样率 SAMPLE_RATE = 24000）。"""
    chunks = _merge_by_speaker(transcript)
    if not chunks:
        return np.array([], dtype=np.float32)
    return _synthesize_chunks(chunks, model, voice_map, pause_switch_ms, 40, 2, 4, 0)


def synthesize_chunks_batched(
    chunks: list[tuple[str, str]],
    model: _ChatTTSHandle,
    voice_map: dict[str, str],
    pause_switch_ms: int,
    batch_chars: int,
    work_dir: Path,
    max_sentence_chars: int = 40,
    oral_level: int = 2,
    break_level: int = 4,
    laugh_level: int = 0,
    energy_level: int = 5,
    temperature: float = 0.1,
    top_p: float = 0.7,
    top_k: int = 20,
    max_new_token: int = 2048,
) -> list[Path]:
    """直接接受预处理的 chunks 分批合成（供口语改写后的调用路径使用）。"""
    return _batched_from_chunks(
        chunks, model, voice_map, pause_switch_ms, batch_chars, work_dir,
        max_sentence_chars, oral_level, break_level, laugh_level, energy_level,
        temperature, top_p, top_k, max_new_token,
    )


def _batched_from_chunks(
    chunks: list[tuple[str, str]],
    model: _ChatTTSHandle,
    voice_map: dict[str, str],
    pause_switch_ms: int,
    batch_chars: int,
    work_dir: Path,
    max_sentence_chars: int,
    oral_level: int,
    break_level: int,
    laugh_level: int,
    energy_level: int = 5,
    temperature: float = 0.1,
    top_p: float = 0.7,
    top_k: int = 20,
    max_new_token: int = 2048,
) -> list[Path]:
    """将 chunks 分批合成为 WAV 文件，返回所有临时路径。"""
    import torch

    if not chunks:
        return []

    batches: list[list[tuple[str, str]]] = []
    current_batch: list[tuple[str, str]] = []
    current_chars = 0
    for chunk in chunks:
        chunk_len = len(chunk[1])
        if current_batch and current_chars + chunk_len > batch_chars:
            batches.append(current_batch)
            current_batch = [chunk]
            current_chars = chunk_len
        else:
            current_batch.append(chunk)
            current_chars += chunk_len
    if current_batch:
        batches.append(current_batch)

    total_batches = len(batches)
    parts: list[Path] = []

    for idx, batch in enumerate(batches):
        batch_text_chars = sum(len(c[1]) for c in batch)
        logger.info("Batch %d/%d (%d chars, %d chunks)", idx + 1, total_batches, batch_text_chars, len(batch))

        audio = _synthesize_chunks(
            batch, model, voice_map, pause_switch_ms,
            max_sentence_chars, oral_level, break_level, laugh_level, energy_level,
            temperature, top_p, top_k, max_new_token,
        )
        if len(audio) == 0:
            logger.warning("Batch %d/%d produced no audio, skipping", idx + 1, total_batches)
            continue

        part_path = work_dir / f"synthesis_part_{len(parts)}.wav"
        sf.write(str(part_path), audio, SAMPLE_RATE)
        parts.append(part_path)

        del audio
        torch.cuda.synchronize()
        gc.collect()
        torch.cuda.empty_cache()

        logger.info(
            "Batch %d/%d done → %s | VRAM alloc=%.2fGB reserved=%.2fGB",
            idx + 1, total_batches, part_path.name,
            torch.cuda.memory_allocated() / 1024**3,
            torch.cuda.memory_reserved() / 1024**3,
        )

    return parts


def synthesize_dialogue_batched(
    transcript: list[TranscriptEntrySchema],
    model: _ChatTTSHandle,
    voice_map: dict[str, str],
    pause_switch_ms: int,
    batch_chars: int,
    work_dir: Path,
    max_sentence_chars: int = 40,
    oral_level: int = 2,
    break_level: int = 4,
    laugh_level: int = 0,
) -> list[Path]:
    """从转写记录合并 chunks 后分批合成（不经过口语改写的调用路径）。"""
    chunks = _merge_by_speaker(transcript)
    return _batched_from_chunks(
        chunks, model, voice_map, pause_switch_ms, batch_chars, work_dir,
        max_sentence_chars, oral_level, break_level, laugh_level,
    )


async def concat_parts_to_mp3(parts: list[Path], dest: Path) -> None:
    """将多个 WAV 片段用 ffmpeg concat 拼接为 192k MP3。"""
    if len(parts) == 1:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(parts[0]),
            "-codec:a", "libmp3lame", "-b:a", "192k",
            str(dest),
        ]
        rc, stderr = await ffmpeg_run(cmd, timeout=300)
        if rc != 0:
            raise RuntimeError(f"ffmpeg MP3 encode failed: {stderr}")
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        concat_list = Path(f.name)
        for p in parts:
            f.write(f"file '{p}'\n")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-codec:a", "libmp3lame", "-b:a", "192k",
            str(dest),
        ]
        rc, stderr = await ffmpeg_run(cmd, timeout=300)
        if rc != 0:
            raise RuntimeError(f"ffmpeg concat+encode failed: {stderr}")
    finally:
        concat_list.unlink(missing_ok=True)

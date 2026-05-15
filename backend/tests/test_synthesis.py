"""单元测试：tts 服务层的合并逻辑与音频拼接（无需 GPU 或真实 TTS 模型）。"""

import numpy as np
import pytest

from copernicus.schemas.transcription import TranscriptEntrySchema
from copernicus.services.tts import (
    SAMPLE_RATE,
    _merge_by_speaker,
    _voice_to_seed,
    build_voice_map,
    synthesize_dialogue,
)


def _entry(speaker: str, text: str, corrected: str = "") -> TranscriptEntrySchema:
    return TranscriptEntrySchema(
        timestamp="00:00",
        timestamp_ms=0,
        end_ms=0,
        speaker=speaker,
        text=text,
        text_corrected=corrected or text,
    )


# ---------------------------------------------------------------------------
# _merge_by_speaker
# ---------------------------------------------------------------------------

class TestMergeBySpeaker:
    def test_consecutive_same_speaker_merged(self):
        entries = [
            _entry("A", "你好"),
            _entry("A", "今天天气不错"),
            _entry("B", "是的"),
        ]
        result = _merge_by_speaker(entries)
        assert len(result) == 2
        assert result[0] == ("A", "你好。今天天气不错")
        assert result[1] == ("B", "是的")

    def test_alternating_speakers_not_merged(self):
        entries = [
            _entry("A", "第一句"),
            _entry("B", "回应"),
            _entry("A", "第三句"),
        ]
        result = _merge_by_speaker(entries)
        assert len(result) == 3

    def test_empty_text_skipped(self):
        entries = [
            _entry("A", "有内容"),
            _entry("A", ""),
            _entry("B", "继续"),
        ]
        result = _merge_by_speaker(entries)
        assert len(result) == 2
        assert result[0][1] == "有内容"

    def test_prefers_text_corrected(self):
        entry = _entry("A", "原始", corrected="纠正后")
        result = _merge_by_speaker([entry])
        assert result[0][1] == "纠正后"

    def test_empty_transcript(self):
        assert _merge_by_speaker([]) == []

    def test_long_chunk_forces_new_segment(self):
        long_text = "这是一段很长的文字" * 8  # > 60 字
        entries = [_entry("A", long_text), _entry("A", "短句")]
        result = _merge_by_speaker(entries)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# build_voice_map
# ---------------------------------------------------------------------------

class TestBuildVoiceMap:
    def test_round_robin_assignment(self):
        voices = ["2222", "3333"]
        speakers = ["Speaker_0", "Speaker_1", "Speaker_2"]
        result = build_voice_map(speakers, voices)
        assert result["Speaker_0"] == "2222"
        assert result["Speaker_1"] == "3333"
        assert result["Speaker_2"] == "2222"  # 循环回头

    def test_override_applied(self):
        voices = ["2222", "3333"]
        speakers = ["Speaker_0", "Speaker_1"]
        result = build_voice_map(speakers, voices, override={"Speaker_0": "9999"})
        assert result["Speaker_0"] == "9999"
        assert result["Speaker_1"] == "3333"

    def test_preserves_first_appearance_order(self):
        voices = ["1111", "2222", "3333"]
        speakers = ["Speaker_1", "Speaker_0", "Speaker_1"]
        result = build_voice_map(speakers, voices)
        assert result["Speaker_1"] == "1111"
        assert result["Speaker_0"] == "2222"


# ---------------------------------------------------------------------------
# _voice_to_seed
# ---------------------------------------------------------------------------

class TestVoiceToSeed:
    def test_numeric_string_returns_int_directly(self):
        assert _voice_to_seed("2222") == 2222

    def test_same_voice_same_seed(self):
        assert _voice_to_seed("中文男") == _voice_to_seed("中文男")

    def test_different_voices_different_seeds(self):
        assert _voice_to_seed("中文男") != _voice_to_seed("中文女")

    def test_seed_in_valid_range(self):
        seed = _voice_to_seed("测试音色")
        assert 0 <= seed < 2**16


# ---------------------------------------------------------------------------
# synthesize_dialogue（用 mock model 验证拼接逻辑）
# ---------------------------------------------------------------------------

class _MockChat:
    """模拟 ChatTTS.Chat，每次 infer 返回 0.1 秒静音数组。"""

    def infer(self, texts, params_infer_code=None, params_refine_text=None, use_decoder=True):
        audio_data = np.zeros(int(SAMPLE_RATE * 0.1), dtype=np.float32)
        return [audio_data]


class MockChatTTS:
    """模拟 _ChatTTSHandle。"""

    def __init__(self):
        self.chat = _MockChat()

    def get_speaker(self, seed: int):
        return None  # spk_emb 在 mock 中不使用


class TestSynthesizeDialogue:
    def test_output_is_float32(self):
        model = MockChatTTS()
        entries = [_entry("A", "测试")]
        voice_map = {"A": "2222"}
        audio = synthesize_dialogue(entries, model, voice_map, pause_switch_ms=800)
        assert audio.dtype == np.float32

    def test_pause_inserted_between_speakers(self):
        model = MockChatTTS()
        entries = [_entry("A", "甲"), _entry("B", "乙")]
        voice_map = {"A": "2222", "B": "3333"}
        pause_ms = 800
        audio = synthesize_dialogue(entries, model, voice_map, pause_switch_ms=pause_ms)

        segment_len = int(SAMPLE_RATE * 0.1)
        pause_len = int(SAMPLE_RATE * pause_ms / 1000)
        expected_len = segment_len + pause_len + segment_len
        assert len(audio) == expected_len

    def test_same_speaker_merged_sentence_gap(self):
        model = MockChatTTS()
        # A 说了两句合并为 "第一。第二"，句号触发切片 → 2 次推理，中间插入 0.2s 句间停顿
        entries = [_entry("A", "第一"), _entry("A", "第二")]
        voice_map = {"A": "2222"}
        audio = synthesize_dialogue(entries, model, voice_map, pause_switch_ms=800)
        segment_len = int(SAMPLE_RATE * 0.1)
        gap_len = int(SAMPLE_RATE * 0.2)
        assert len(audio) == segment_len + gap_len + segment_len

    def test_empty_transcript_returns_empty(self):
        model = MockChatTTS()
        audio = synthesize_dialogue([], model, {}, pause_switch_ms=800)
        assert len(audio) == 0

    def test_unknown_speaker_falls_back_to_default(self):
        model = MockChatTTS()
        entries = [_entry("Unknown_99", "测试")]
        voice_map = {}
        audio = synthesize_dialogue(entries, model, voice_map, pause_switch_ms=800)
        assert len(audio) > 0

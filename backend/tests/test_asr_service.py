"""ASRService 的推理后处理：用假模型验证解析、降噪、切分与说话人分离（不需要 GPU 与模型文件）。"""

from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

from copernicus.config import Settings
from copernicus.exceptions import ASRError
from copernicus.services.asr import ASRService
from copernicus.services.asr.diarization import SpeakerDiarizer
from copernicus.services.asr.segment_builders import (
    build_segments_from_sentence_info,
    build_segments_from_sentences,
)
from copernicus.services.asr.text_cleanup import (
    clean_sensevoice_text,
    is_noise_segment,
    split_long_segment,
)


def _service(mode: str = "paraformer", *, has_spk: bool = False, spk_model=None, **overrides) -> ASRService:
    """绕过模型加载，直接装配一个带假模型的服务。"""
    settings = Settings(asr_mode=mode, **overrides)
    svc = ASRService.__new__(ASRService)
    svc._settings = settings
    svc._mode = mode
    svc._batch_size = settings.asr_batch_size
    svc._max_segment_ms = settings.sensevoice_max_segment_ms
    svc._diarizer = SpeakerDiarizer(
        window_ms=settings.spk_sliding_window_ms,
        step_ms=settings.spk_sliding_step_ms,
        threshold_ms=settings.spk_sliding_threshold_ms,
        distance_threshold=settings.spk_distance_threshold,
    )
    svc._filter_noise = settings.filter_noise_segments
    svc._model = MagicMock()
    svc._has_spk = has_spk
    svc._spk_model = spk_model
    svc._sensevoice_language = "auto"
    return svc


class TestTextCleanup:
    def test_sensevoice_tags_emoji_and_repeated_punctuation_are_removed(self):
        raw = "<|zh|><|NEUTRAL|>你好😀，，，世界。。"
        assert clean_sensevoice_text(raw) == "你好。世界。"

    def test_punctuation_only_text_becomes_empty(self):
        assert clean_sensevoice_text("，，") == ""

    @pytest.mark.parametrize("text", ["嗯嗯", "嗯。", "啊啊啊", "the yeah", "Um, uh.", "  "])
    def test_filler_only_segments_are_noise(self, text):
        assert is_noise_segment(text)

    @pytest.mark.parametrize("text", ["好的我们开始", "Yes we can", "嗯我同意"])
    def test_real_content_is_not_noise(self, text):
        assert not is_noise_segment(text)


class TestSplitLongSegment:
    def test_splits_at_punctuation_and_keeps_all_text(self):
        text = "一二三四五。六七八九十。甲乙丙丁戊"
        timestamps = [[i * 1000, i * 1000 + 900] for i in range(len(text))]

        parts = split_long_segment(text, timestamps, max_duration_ms=6000)

        assert len(parts) >= 2
        assert "".join(p["text"] for p in parts) == text
        assert parts[0]["start"] == 0 and parts[-1]["end"] == timestamps[-1][1]
        assert all(p["start"] <= p["end"] for p in parts)

    def test_without_timestamps_returns_the_text_untouched(self):
        assert split_long_segment("你好", [], 1000) == [{"text": "你好", "start": 0, "end": 0}]


class TestSegmentBuilders:
    def test_sentence_info_maps_speaker_time_and_average_confidence(self):
        info = [
            {"text": "你好。", "start": 0, "end": 900, "spk": 0, "timestamp": [[0, 400], [400, 900]]},
            {"text": "再见。", "start": 1000, "end": 1900, "spk": 1, "timestamp": [[1000, 1400], [1400, 1900]]},
        ]
        segs = build_segments_from_sentence_info(info, [0.9, 0.7, 0.5, 0.5])

        assert [(s.speaker, s.start_ms, s.end_ms) for s in segs] == [(0, 0, 900), (1, 1000, 1900)]
        assert segs[0].confidence == pytest.approx(0.8) and segs[1].confidence == pytest.approx(0.5)

    def test_sentences_skip_punctuation_when_aligning_token_confidence(self):
        segs = build_segments_from_sentences(["你好。", "再见！"], [1.0, 0.5, 0.2, 0.4])
        assert [s.confidence for s in segs] == [pytest.approx(0.75), pytest.approx(0.3)]

    def test_no_token_confidence_gives_plain_segments(self):
        segs = build_segments_from_sentences(["你好。"], [])
        assert segs[0].text == "你好。" and segs[0].confidence == 0.0


class TestParaformer:
    def test_builds_segments_and_forwards_decoding_options(self, tmp_path):
        svc = _service(has_spk=True, asr_batch_size=3000)
        svc._model.generate.return_value = [{
            "text": "你好。",
            "sentence_info": [{"text": "你好。", "start": 0, "end": 900, "spk": 1, "timestamp": [[0, 900]]}],
            "token_confidence": [0.9],
        }]

        result = svc.transcribe(tmp_path / "a.wav", hotwords=["科哥", "谱网"], sentence_timestamp=True)

        kwargs = svc._model.generate.call_args.kwargs
        assert kwargs["hotword"] == "科哥 谱网"
        assert kwargs["return_spk_res"] is True and kwargs["sentence_timestamp"] is True
        assert kwargs["batch_size_s"] == 60  # 说话人分离时 batch 被限制，避免 OOM
        assert result.text == "你好。" and result.segments[0].speaker == 1

    def test_without_sentence_info_falls_back_to_splitting_the_text(self, tmp_path):
        svc = _service()
        svc._model.generate.return_value = [{"text": "第一句。第二句。"}]
        result = svc.transcribe(tmp_path / "a.wav")
        assert [s.text for s in result.segments] == ["第一句。", "第二句。"]

    def test_empty_model_output_is_an_empty_result(self, tmp_path):
        svc = _service()
        svc._model.generate.return_value = []
        result = svc.transcribe(tmp_path / "a.wav")
        assert result.text == "" and result.segments == []

    def test_model_errors_are_wrapped(self, tmp_path):
        svc = _service()
        svc._model.generate.side_effect = RuntimeError("CUDA out of memory")
        with pytest.raises(ASRError, match="CUDA out of memory"):
            svc.transcribe(tmp_path / "a.wav")


class TestSenseVoice:
    def test_cleans_text_drops_noise_and_uses_word_timestamps(self, tmp_path):
        svc = _service("sensevoice")
        svc._model.generate.return_value = [
            {"text": "<|zh|>大家好。", "timestamp": [[100, 400], [400, 1200]]},
            {"text": "嗯嗯", "timestamp": [[1300, 1500]]},
            {"text": "开始吧。", "timestamp": [[2000, 2500], [2500, 3000]]},
        ]
        result = svc.transcribe(tmp_path / "a.wav", sentence_timestamp=True)

        assert [(s.text, s.start_ms, s.end_ms) for s in result.segments] == [
            ("大家好。", 100, 1200), ("开始吧。", 2000, 3000),
        ]
        assert result.text == "大家好。开始吧。"

    def test_overlong_segment_is_split(self, tmp_path):
        svc = _service("sensevoice", sensevoice_max_segment_ms=5000)
        text = "一二三四五。六七八九十。"
        svc._model.generate.return_value = [
            {"text": text, "timestamp": [[i * 1000, i * 1000 + 900] for i in range(len(text))]}
        ]
        result = svc.transcribe(tmp_path / "a.wav")
        assert len(result.segments) >= 2
        assert "".join(s.text for s in result.segments) == text


def _two_voice_wav(path, seconds: int = 6) -> None:
    """前半段振幅小、后半段振幅大：假声纹模型据此给出两个正交的 embedding。"""
    sr = 16000
    half = np.full(seconds // 2 * sr, 0.1, dtype="float32")
    sf.write(str(path), np.concatenate([half, half * 5]), sr)


def _fake_voiceprint():
    spk = MagicMock()

    def generate(input):
        loud = float(np.mean(np.abs(input))) > 0.3
        return [{"spk_embedding": [0.0, 1.0] if loud else [1.0, 0.0]}]

    spk.generate.side_effect = generate
    return spk


class TestDiarization:
    def test_segments_get_speakers_by_voiceprint_clustering(self, tmp_path):
        wav = tmp_path / "a.wav"
        _two_voice_wav(wav)
        svc = _service("sensevoice", has_spk=True, spk_model=_fake_voiceprint())
        svc._model.generate.return_value = [
            {"text": "第一位说话。", "timestamp": [[0, 2800]]},
            {"text": "第二位说话。", "timestamp": [[3200, 5900]]},
        ]

        result = svc.transcribe(wav, sentence_timestamp=True)

        speakers = [s.speaker for s in result.segments]
        assert len(result.segments) == 2 and speakers[0] != speakers[1]

    def test_single_untimed_segment_is_split_into_speaker_turns(self, tmp_path):
        wav = tmp_path / "a.wav"
        _two_voice_wav(wav)
        svc = _service("sensevoice", has_spk=True, spk_model=_fake_voiceprint())
        svc._model.generate.return_value = [{"text": "甲说的话在前乙说的话在后", "timestamp": []}]

        result = svc.transcribe(wav, sentence_timestamp=True)

        assert len(result.segments) == 2
        assert result.segments[0].speaker != result.segments[1].speaker
        assert "".join(s.text for s in result.segments) == "甲说的话在前乙说的话在后"
        assert result.segments[0].start_ms < result.segments[1].start_ms

    def test_unreadable_audio_falls_back_to_undiarized_segments(self, tmp_path):
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"not audio")
        svc = _service("sensevoice", has_spk=True, spk_model=_fake_voiceprint())
        svc._model.generate.return_value = [{"text": "你好。", "timestamp": [[0, 1000]]}]

        result = svc.transcribe(bad, sentence_timestamp=True)

        assert [s.text for s in result.segments] == ["你好。"] and result.segments[0].speaker == -1

    def test_without_sentence_timestamp_diarization_is_skipped(self, tmp_path):
        spk = _fake_voiceprint()
        svc = _service("sensevoice", has_spk=True, spk_model=spk)
        svc._model.generate.return_value = [{"text": "你好。", "timestamp": [[0, 1000]]}]
        svc.transcribe(tmp_path / "a.wav", sentence_timestamp=False)
        spk.generate.assert_not_called()


class TestWeightLifecycle:
    def test_unload_then_reload(self, monkeypatch):
        svc = _service()
        assert svc.is_loaded()
        svc.unload_weights()
        assert not svc.is_loaded() and svc._spk_model is None

        reloaded = MagicMock()
        monkeypatch.setattr(svc, "_init_paraformer_mode", lambda *_: setattr(svc, "_model", reloaded))
        monkeypatch.setattr(Settings, "resolve_asr_device", lambda self: "cpu")
        svc.reload()
        assert svc.is_loaded()

    def test_reload_when_loaded_is_a_noop(self, monkeypatch):
        svc = _service()
        called = MagicMock()
        monkeypatch.setattr(svc, "_init_paraformer_mode", called)
        svc.reload()
        called.assert_not_called()

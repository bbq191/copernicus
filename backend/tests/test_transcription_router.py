from unittest.mock import AsyncMock

import pytest

from copernicus.services.asr import Segment
from copernicus.services.pipeline import TranscriptionResult


class TestTranscribeEndpoint:
    def test_transcribe_success(self, client, mock_pipeline):
        mock_pipeline.process = AsyncMock(
            return_value=TranscriptionResult(
                raw_text="原始文本",
                corrected_text="纠正文本",
                segments=[Segment(text="原始文本", start_ms=0, end_ms=1000)],
                processing_time_ms=123.45,
            )
        )

        response = client.post(
            "/api/v1/transcribe",
            files={"file": ("test.wav", b"fake-audio-bytes", "audio/wav")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["raw_text"] == "原始文本"
        assert data["corrected_text"] == "纠正文本"
        assert len(data["segments"]) == 1
        assert data["processing_time_ms"] == 123.45

    def test_transcribe_with_hotwords(self, client, mock_pipeline):
        mock_pipeline.process = AsyncMock(
            return_value=TranscriptionResult(
                raw_text="text",
                corrected_text="text",
                segments=[],
                processing_time_ms=50.0,
            )
        )

        response = client.post(
            "/api/v1/transcribe",
            files={"file": ("test.wav", b"fake", "audio/wav")},
            data={"hotwords": '["热词一", "热词二"]'},
        )

        assert response.status_code == 200
        mock_pipeline.process.assert_called_once()
        call_args = mock_pipeline.process.call_args
        assert call_args[1].get("hotwords") or call_args[0][2] == ["热词一", "热词二"]

    def test_transcribe_invalid_hotwords(self, client, mock_pipeline):
        response = client.post(
            "/api/v1/transcribe",
            files={"file": ("test.wav", b"fake", "audio/wav")},
            data={"hotwords": "not-json"},
        )

        assert response.status_code == 422


class TestTranscribeRawEndpoint:
    def test_transcribe_raw_success(self, client, mock_pipeline):
        mock_pipeline.process_raw = AsyncMock(
            return_value=TranscriptionResult(
                raw_text="原始文本",
                corrected_text="原始文本",
                segments=[],
                processing_time_ms=80.0,
            )
        )

        response = client.post(
            "/api/v1/transcribe/raw",
            files={"file": ("test.wav", b"fake-audio-bytes", "audio/wav")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["raw_text"] == "原始文本"
        assert "corrected_text" not in data


class TestHealthEndpoint:
    def test_health_check(self, client, mock_pipeline):
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["asr_loaded"] is True
        assert data["llm_reachable"] is True

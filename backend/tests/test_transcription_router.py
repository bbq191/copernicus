from unittest.mock import AsyncMock

import pytest

from copernicus.services.pipeline import TranscriptResult
from copernicus.services.pipeline.base import TranscriptEntry


class TestTranscribeTranscriptEndpoint:
    def test_transcribe_transcript_success(self, client, mock_pipeline):
        mock_pipeline.process_transcript = AsyncMock(
            return_value=TranscriptResult(
                transcript=[
                    TranscriptEntry(
                        timestamp="00:00",
                        timestamp_ms=0,
                        end_ms=1000,
                        speaker="Speaker 1",
                        text="原始文本",
                        text_corrected="纠正文本",
                    )
                ],
                processing_time_ms=123.45,
            )
        )

        response = client.post(
            "/api/v1/transcribe/transcript",
            files={"file": ("test.wav", b"fake-audio-bytes", "audio/wav")},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["transcript"]) == 1
        assert data["transcript"][0]["text"] == "原始文本"
        assert data["transcript"][0]["text_corrected"] == "纠正文本"
        assert data["processing_time_ms"] == 123.45

    def test_transcribe_transcript_with_hotwords(self, client, mock_pipeline):
        mock_pipeline.process_transcript = AsyncMock(
            return_value=TranscriptResult(
                transcript=[],
                processing_time_ms=50.0,
            )
        )

        response = client.post(
            "/api/v1/transcribe/transcript",
            files={"file": ("test.wav", b"fake", "audio/wav")},
            data={"hotwords": '["热词一", "热词二"]'},
        )

        assert response.status_code == 200
        mock_pipeline.process_transcript.assert_called_once()
        call_args = mock_pipeline.process_transcript.call_args
        assert call_args[1].get("hotwords") or call_args[0][2] == ["热词一", "热词二"]

    def test_transcribe_transcript_invalid_hotwords(self, client, mock_pipeline):
        response = client.post(
            "/api/v1/transcribe/transcript",
            files={"file": ("test.wav", b"fake", "audio/wav")},
            data={"hotwords": "not-json"},
        )

        assert response.status_code == 422


class TestHealthEndpoint:
    def test_health_check(self, client, mock_pipeline):
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["asr_loaded"] is True
        assert data["llm_reachable"] is True

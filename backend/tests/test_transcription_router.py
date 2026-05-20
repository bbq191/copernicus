from unittest.mock import MagicMock


class TestSubmitTranscriptEndpoint:
    def test_submit_transcript_success(self, client, mock_task_store):
        response = client.post(
            "/api/v1/tasks/transcript",
            files={"file": ("test.wav", b"fake-audio-bytes", "audio/wav")},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["task_id"] == "test-task-id"
        assert data["status"] == "pending"
        mock_task_store.submit_transcript.assert_called_once()

    def test_submit_transcript_with_hotwords(self, client, mock_task_store):
        response = client.post(
            "/api/v1/tasks/transcript",
            files={"file": ("test.wav", b"fake", "audio/wav")},
            data={"hotwords": '["热词一", "热词二"]'},
        )

        assert response.status_code == 202
        mock_task_store.submit_transcript.assert_called_once()
        call_kwargs = mock_task_store.submit_transcript.call_args
        hotwords_arg = call_kwargs[1].get("hotwords") or call_kwargs[0][2]
        assert hotwords_arg == ["热词一", "热词二"]

    def test_submit_transcript_invalid_hotwords(self, client):
        response = client.post(
            "/api/v1/tasks/transcript",
            files={"file": ("test.wav", b"fake", "audio/wav")},
            data={"hotwords": "not-json"},
        )

        assert response.status_code == 422

    def test_submit_transcript_returns_existing_on_duplicate(self, client, mock_task_store: MagicMock):
        mock_task_store.lookup_by_hash.return_value = "existing-task-id"
        mock_task_store.get.return_value = None

        response = client.post(
            "/api/v1/tasks/transcript",
            files={"file": ("test.wav", b"fake-audio-bytes", "audio/wav")},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["task_id"] == "existing-task-id"
        assert data["existing"] is True
        mock_task_store.submit_transcript.assert_not_called()


class TestHealthEndpoint:
    def test_health_check(self, client, mock_pipeline):
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert data["asr"]["status"] in ("ok", "degraded", "down")
        assert data["llm"]["status"] in ("ok", "down")
        assert "tasks" in data

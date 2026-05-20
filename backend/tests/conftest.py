from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from copernicus.services.corrector import CorrectorService
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_store import TaskStore


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_pipeline() -> MagicMock:
    """Create a mocked PipelineService for router tests."""
    pipeline = MagicMock(spec=PipelineService)
    pipeline._asr = MagicMock()
    pipeline._corrector = MagicMock(spec=CorrectorService)
    pipeline._corrector.is_reachable = AsyncMock(return_value=True)
    return pipeline


@pytest.fixture
def mock_task_store() -> MagicMock:
    """Create a mocked TaskStore for task router tests."""
    store = MagicMock(spec=TaskStore)
    store.lookup_by_hash.return_value = None
    store.submit_transcript.return_value = "test-task-id"
    store.submit_standard_minutes.return_value = "test-task-id"
    store.get.return_value = None
    store.persistence.persist_media.return_value = Path("/tmp/test.wav")
    return store


@pytest.fixture
def test_app(mock_pipeline: MagicMock, mock_task_store: MagicMock):
    """Create a test FastAPI app with mocked dependencies."""
    from fastapi import FastAPI
    from copernicus.routers.transcription import router as transcription_router
    from copernicus.routers.task import router as task_router

    app = FastAPI()
    app.state.pipeline = mock_pipeline
    app.state.task_store = mock_task_store
    app.include_router(transcription_router)
    app.include_router(task_router)
    return app


@pytest.fixture
def client(test_app) -> TestClient:
    return TestClient(test_app)

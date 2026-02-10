from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from copernicus.services.corrector import CorrectorService
from copernicus.services.pipeline import PipelineService


@pytest.fixture
def mock_pipeline() -> MagicMock:
    """Create a mocked PipelineService for router tests."""
    pipeline = MagicMock(spec=PipelineService)
    pipeline._asr = MagicMock()
    pipeline._corrector = MagicMock(spec=CorrectorService)
    pipeline._corrector.is_reachable = AsyncMock(return_value=True)
    return pipeline


@pytest.fixture
def test_app(mock_pipeline: MagicMock):
    """Create a test FastAPI app with mocked dependencies."""
    from fastapi import FastAPI
    from copernicus.routers.transcription import router as transcription_router

    app = FastAPI()
    app.state.pipeline = mock_pipeline
    app.include_router(transcription_router)
    return app


@pytest.fixture
def client(test_app) -> TestClient:
    return TestClient(test_app)

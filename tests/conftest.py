from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from copernicus.services.corrector import CorrectorService
from copernicus.services.evaluator import EvaluatorService
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
def mock_evaluator() -> MagicMock:
    """Create a mocked EvaluatorService for router tests."""
    return MagicMock(spec=EvaluatorService)


@pytest.fixture
def test_app(mock_pipeline: MagicMock, mock_evaluator: MagicMock):
    """Create a test FastAPI app with mocked dependencies."""
    from fastapi import FastAPI
    from copernicus.routers.transcription import router as transcription_router
    from copernicus.routers.evaluation import router as evaluation_router

    app = FastAPI()
    app.state.pipeline = mock_pipeline
    app.state.evaluator = mock_evaluator
    app.include_router(transcription_router)
    app.include_router(evaluation_router)
    return app


@pytest.fixture
def client(test_app) -> TestClient:
    return TestClient(test_app)

from fastapi import Request

from copernicus.services.compliance import ComplianceService
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_store import TaskStore


def get_pipeline(request: Request) -> PipelineService:
    """Retrieve the PipelineService singleton from app state."""
    return request.app.state.pipeline


def get_task_store(request: Request) -> TaskStore:
    """Retrieve the TaskStore singleton from app state."""
    return request.app.state.task_store


def get_evaluator(request: Request) -> EvaluatorService:
    """Retrieve the EvaluatorService singleton from app state."""
    return request.app.state.evaluator


def get_compliance_service(request: Request) -> ComplianceService:
    """Retrieve the ComplianceService singleton from app state."""
    return request.app.state.compliance

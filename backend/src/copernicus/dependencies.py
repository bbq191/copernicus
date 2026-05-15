from fastapi import Request

from copernicus.services.compliance import ComplianceService
from copernicus.services.llm import OllamaClient
from copernicus.services.model_manager import ModelManager
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_store import TaskStore
from copernicus.services.template_manager import TemplateManager
from copernicus.services.upload_session import UploadSessionService


def get_pipeline(request: Request) -> PipelineService:
    return request.app.state.pipeline


def get_task_store(request: Request) -> TaskStore:
    return request.app.state.task_store


def get_compliance_service(request: Request) -> ComplianceService:
    return request.app.state.compliance


def get_upload_session_service(request: Request) -> UploadSessionService:
    return request.app.state.upload_session


def get_model_manager(request: Request) -> ModelManager | None:
    return getattr(request.app.state, "model_manager", None)


def get_template_manager(request: Request) -> TemplateManager:
    return request.app.state.template_manager


def get_llm_client(request: Request) -> OllamaClient:
    return request.app.state.llm_client

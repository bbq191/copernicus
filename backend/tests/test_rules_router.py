"""/api/v1/rules：自定义合规规则库的 CRUD 接口。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copernicus.error_handlers import register_error_handlers
from copernicus.routers.rules import router as rules_router
from copernicus.schemas.task import TaskStatus
from copernicus.services.rule_store import RuleStore

_BODY = {
    "title": "不得承诺保本",
    "content": "严禁承诺保本保息",
    "category": "forbidden_phrase",
    "check_mode": "semantic",
}


@pytest.fixture
def store(tmp_path) -> RuleStore:
    return RuleStore(tmp_path / "rules")


@pytest.fixture
def api(store, mock_task_store: MagicMock) -> TestClient:
    app = FastAPI()
    app.state.rule_store = store
    app.state.task_store = mock_task_store
    app.include_router(rules_router)
    register_error_handlers(app)
    return TestClient(app)


class TestCreateAndList:
    def test_create_returns_201_with_assigned_id(self, api):
        r = api.post("/api/v1/rules", json=_BODY)
        assert r.status_code == 201
        body = r.json()
        assert body["id"] == 1000
        assert body["enabled"] is True

    def test_missing_required_field_is_422(self, api):
        r = api.post("/api/v1/rules", json={"title": "x"})
        assert r.status_code == 422

    def test_list_returns_everything_created(self, api):
        api.post("/api/v1/rules", json=_BODY)
        api.post("/api/v1/rules", json={**_BODY, "title": "第二条"})

        r = api.get("/api/v1/rules")
        assert r.status_code == 200
        assert [item["title"] for item in r.json()] == ["不得承诺保本", "第二条"]


class TestGetUpdateDelete:
    def test_get_unknown_is_404(self, api):
        assert api.get("/api/v1/rules/1000").status_code == 404

    def test_get_returns_the_created_rule(self, api):
        created = api.post("/api/v1/rules", json=_BODY).json()
        r = api.get(f"/api/v1/rules/{created['id']}")
        assert r.status_code == 200
        assert r.json() == created

    def test_patch_updates_only_given_fields(self, api):
        created = api.post("/api/v1/rules", json=_BODY).json()
        r = api.patch(f"/api/v1/rules/{created['id']}", json={"enabled": False})
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["title"] == created["title"]

    def test_patch_unknown_is_404(self, api):
        assert api.patch("/api/v1/rules/1000", json={"enabled": False}).status_code == 404

    def test_delete_then_get_is_404(self, api):
        created = api.post("/api/v1/rules", json=_BODY).json()
        assert api.delete(f"/api/v1/rules/{created['id']}").status_code == 204
        assert api.get(f"/api/v1/rules/{created['id']}").status_code == 404

    def test_delete_unknown_is_404(self, api):
        assert api.delete("/api/v1/rules/1000").status_code == 404


class TestAffectedTasksAndReaudit:
    def test_affected_tasks_404_for_unknown_rule(self, api):
        assert api.get("/api/v1/rules/999/affected-tasks").status_code == 404

    def test_affected_tasks_lists_what_persistence_scan_returns(self, api, mock_task_store):
        created = api.post("/api/v1/rules", json=_BODY).json()
        mock_task_store.persistence.scan_task_ids_using_rule.return_value = ["task-a", "task-b"]

        r = api.get(f"/api/v1/rules/{created['id']}/affected-tasks")

        assert r.status_code == 200
        assert r.json() == {"task_ids": ["task-a", "task-b"], "total": 2}
        mock_task_store.persistence.scan_task_ids_using_rule.assert_called_once_with(created["id"])

    def test_reaudit_404_for_unknown_rule(self, api):
        assert api.post("/api/v1/rules/999/reaudit-affected").status_code == 404

    def test_reaudit_422_when_nothing_affected(self, api, mock_task_store):
        created = api.post("/api/v1/rules", json=_BODY).json()
        mock_task_store.persistence.scan_task_ids_using_rule.return_value = []

        r = api.post(f"/api/v1/rules/{created['id']}/reaudit-affected")

        assert r.status_code == 422

    def test_reaudit_returns_202_with_job_id(self, api, mock_task_store):
        created = api.post("/api/v1/rules", json=_BODY).json()
        mock_task_store.persistence.scan_task_ids_using_rule.return_value = ["task-a"]
        # 后台任务马上就会跑：喂一个一次性结果，避免真的卡在等待子任务终态上
        mock_task_store.persistence.load_json.return_value = None
        mock_task_store.submit_compliance_audit.return_value = "sub-1"
        mock_task_store.get.return_value = SimpleNamespace(status=TaskStatus.FAILED, error="x")

        r = api.post(f"/api/v1/rules/{created['id']}/reaudit-affected")

        assert r.status_code == 202
        body = r.json()
        assert body["total"] == 1
        assert "job_id" in body

    def test_reaudit_job_status_404_for_unknown_job(self, api):
        assert api.get("/api/v1/rules/reaudit-jobs/does-not-exist").status_code == 404

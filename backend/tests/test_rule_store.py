"""RuleStore：自定义合规规则库的 CRUD 持久化。"""

import pytest

from copernicus.schemas.compliance import CustomRuleCreate, CustomRuleUpdate
from copernicus.services.rule_store import RuleStore


def _create(**over) -> CustomRuleCreate:
    fields = {
        "title": "测试规则",
        "content": "不得承诺保本保息",
        "category": "forbidden_phrase",
        "check_mode": "semantic",
        **over,
    }
    return CustomRuleCreate(**fields)


@pytest.fixture
def store(tmp_path) -> RuleStore:
    return RuleStore(tmp_path / "rules")


class TestCreate:
    def test_assigns_an_id_starting_at_1000(self, store):
        rule = store.create_rule(_create())
        assert rule.id == 1000
        assert rule.title == "测试规则" and rule.enabled is True
        assert rule.created_at == rule.updated_at

    def test_ids_increment_and_never_reused_after_delete(self, store):
        a = store.create_rule(_create())
        b = store.create_rule(_create())
        assert b.id == a.id + 1

        store.delete_rule(a.id)
        c = store.create_rule(_create())
        assert c.id == b.id + 1  # 不回收已删除的 id

    def test_defaults(self, store):
        rule = store.create_rule(_create())
        assert rule.evidence_sources == ["transcript"]
        assert rule.keywords == []
        assert rule.severity_default == "medium"


class TestReadAndList:
    def test_list_is_sorted_by_id(self, store):
        ids = [store.create_rule(_create(title=f"r{i}")).id for i in range(3)]
        assert [r.id for r in store.list_rules()] == ids

    def test_get_missing_returns_none(self, store):
        assert store.get_rule(9999) is None

    def test_get_round_trips_persisted_data(self, store):
        created = store.create_rule(_create(keywords=["保本", "保息"]))
        fetched = store.get_rule(created.id)
        assert fetched == created


class TestUpdate:
    def test_partial_update_only_touches_given_fields(self, store):
        rule = store.create_rule(_create())
        updated = store.update_rule(rule.id, CustomRuleUpdate(enabled=False))

        assert updated.enabled is False
        assert updated.title == rule.title  # 其余字段不变
        assert updated.updated_at >= rule.updated_at
        assert store.get_rule(rule.id).enabled is False  # 已落盘

    def test_update_missing_rule_returns_none(self, store):
        assert store.update_rule(1234, CustomRuleUpdate(enabled=False)) is None


class TestDelete:
    def test_delete_removes_the_file(self, store):
        rule = store.create_rule(_create())
        assert store.delete_rule(rule.id) is True
        assert store.get_rule(rule.id) is None

    def test_delete_missing_returns_false(self, store):
        assert store.delete_rule(1) is False


class TestCorruptFileIsSkipped:
    def test_unreadable_file_is_logged_and_skipped_not_raised(self, store, tmp_path):
        good = store.create_rule(_create())
        (tmp_path / "rules" / "bogus.json").write_text("not json", encoding="utf-8")

        rules = store.list_rules()

        assert [r.id for r in rules] == [good.id]

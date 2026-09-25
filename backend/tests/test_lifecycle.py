import json
from datetime import datetime, timedelta, timezone

import pytest

from copernicus.services.lifecycle import LifecycleService

_NOW = datetime.now(timezone.utc)


def _make_task(root, name, *, age_hours, done, media=b"x" * 10, processed_age_hours=None):
    d = root / name
    d.mkdir()
    meta = {"created_at": (_NOW - timedelta(hours=age_hours)).isoformat()}
    if processed_age_hours is not None:
        meta["processed_at"] = (_NOW - timedelta(hours=processed_age_hours)).isoformat()
    (d / "meta.json").write_text(json.dumps(meta))
    if media:
        (d / "audio.wav").write_bytes(media)
    if done:
        (d / "transcript.json").write_text("{}")
    return d


@pytest.fixture
def svc(tmp_path):
    return LifecycleService(tmp_path, retention_hours=24)


class TestExpiredMedia:
    def test_deletes_media_of_expired_completed_task_but_keeps_results(self, tmp_path, svc):
        d = _make_task(tmp_path, "old", age_hours=48, done=True)

        assert svc.cleanup_expired_media() == 1
        assert not (d / "audio.wav").exists()
        assert (d / "transcript.json").exists() and (d / "meta.json").exists()

    def test_keeps_recent_media(self, tmp_path, svc):
        d = _make_task(tmp_path, "new", age_hours=1, done=True)
        assert svc.cleanup_expired_media() == 0
        assert (d / "audio.wav").exists()

    def test_reprocessed_old_task_is_not_expired(self, tmp_path, svc):
        d = _make_task(tmp_path, "rerun", age_hours=100, done=True, processed_age_hours=1)
        assert svc.cleanup_expired_media() == 0
        assert (d / "audio.wav").exists()


class TestStaleFailedTasks:
    def test_removes_old_task_without_transcript(self, tmp_path, svc):
        d = _make_task(tmp_path, "failed", age_hours=48, done=False)
        assert svc.cleanup_stale_failed_tasks() == 1
        assert not d.exists()

    def test_keeps_completed_tasks(self, tmp_path, svc):
        d = _make_task(tmp_path, "ok", age_hours=48, done=True)
        assert svc.cleanup_stale_failed_tasks() == 0
        assert d.exists()

    def test_recently_started_task_without_transcript_is_kept(self, tmp_path):
        # 保留期设得很短时，也不能删除刚开始处理、尚无结果的任务
        svc = LifecycleService(tmp_path, retention_hours=0)
        d = _make_task(tmp_path, "running", age_hours=0.5, done=False)
        assert svc.cleanup_stale_failed_tasks() == 0
        assert d.exists()

    def test_rerun_of_old_task_is_kept(self, tmp_path, svc):
        d = _make_task(tmp_path, "rerun", age_hours=100, done=False, processed_age_hours=0.1)
        assert svc.cleanup_stale_failed_tasks() == 0
        assert d.exists()


class TestStaleSessions:
    def test_removes_only_expired_sessions(self, tmp_path, svc):
        sessions = tmp_path / ".sessions"
        sessions.mkdir()
        old, new = sessions / "old", sessions / "new"
        old.mkdir()
        new.mkdir()
        ancient = (_NOW - timedelta(hours=72)).timestamp()
        import os
        os.utime(old, (ancient, ancient))

        assert svc.cleanup_stale_sessions() == 1
        assert not old.exists() and new.exists()


class TestStorageQuota:
    def test_disabled_by_default(self, tmp_path, svc):
        _make_task(tmp_path, "a", age_hours=1, done=True, media=b"x" * 1000)
        assert svc.enforce_storage_quota() == 0

    def test_evicts_oldest_media_first_until_under_quota(self, tmp_path):
        svc = LifecycleService(tmp_path, retention_hours=24, max_storage_gb=0)
        svc._max_storage_bytes = 2500  # 直接设字节数，避免构造 GB 级文件
        oldest = _make_task(tmp_path, "oldest", age_hours=30, done=True, media=b"x" * 1000)
        middle = _make_task(tmp_path, "middle", age_hours=20, done=True, media=b"x" * 1000)
        newest = _make_task(tmp_path, "newest", age_hours=1, done=True, media=b"x" * 1000)

        deleted = svc.enforce_storage_quota()

        assert deleted >= 1
        assert not (oldest / "audio.wav").exists()
        assert (newest / "audio.wav").exists()
        # 结果文件始终保留
        assert (oldest / "transcript.json").exists()
        assert (middle / "meta.json").exists()


class TestRunOnce:
    def test_runs_all_policies(self, tmp_path, svc):
        _make_task(tmp_path, "old", age_hours=48, done=True)
        _make_task(tmp_path, "failed", age_hours=48, done=False)

        result = svc.run_once()

        assert result["expired_media"] == 1
        assert result["stale_failed_tasks"] == 1

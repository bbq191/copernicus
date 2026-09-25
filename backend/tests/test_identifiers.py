import pytest

from copernicus.exceptions import CopernicusError, InvalidIdentifierError
from copernicus.services.persistence import PersistenceService
from copernicus.services.upload_session import UploadSessionService


class TestInvalidIdentifier:
    def test_is_both_domain_and_value_error(self):
        # 保持对 `except ValueError` 调用方的兼容，同时可被专属 handler 精确捕获
        assert issubclass(InvalidIdentifierError, CopernicusError)
        assert issubclass(InvalidIdentifierError, ValueError)

    @pytest.mark.parametrize("bad", ["../etc/passwd", "short", "G" * 32, ""])
    def test_persistence_rejects_bad_task_id(self, tmp_path, bad):
        svc = PersistenceService(tmp_path)
        with pytest.raises(InvalidIdentifierError):
            svc.task_dir(bad)

    def test_upload_session_rejects_bad_hash(self, tmp_path):
        svc = UploadSessionService(tmp_path)
        with pytest.raises(InvalidIdentifierError):
            svc.get_session("../../x")

    def test_plain_value_error_is_not_identifier_error(self):
        assert not issubclass(ValueError, InvalidIdentifierError)

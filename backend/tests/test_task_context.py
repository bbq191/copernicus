import logging

from copernicus.task_context import (
    get_task_id,
    install_log_record_factory,
    reset_task_id,
    set_task_id,
)


class TestTaskId:
    def test_set_get_reset_round_trip(self):
        assert get_task_id() == "-"
        token = set_task_id("t" * 32)
        assert get_task_id() == "t" * 32
        reset_task_id(token)
        assert get_task_id() == "-"

    def test_log_records_inside_the_context_carry_its_id(self, caplog):
        install_log_record_factory()
        token = set_task_id("task-123")
        try:
            with caplog.at_level(logging.INFO, logger="probe"):
                logging.getLogger("probe").info("inside task")
        finally:
            reset_task_id(token)

        assert caplog.records[-1].task_id == "task-123"

    def test_log_records_outside_the_context_use_placeholder(self, caplog):
        install_log_record_factory()
        with caplog.at_level(logging.INFO, logger="probe2"):
            logging.getLogger("probe2").info("outside")
        assert caplog.records[-1].task_id == "-"

    def test_installing_twice_is_a_noop(self):
        install_log_record_factory()
        factory_after_first_install = logging.getLogRecordFactory()
        install_log_record_factory()
        assert logging.getLogRecordFactory() is factory_after_first_install

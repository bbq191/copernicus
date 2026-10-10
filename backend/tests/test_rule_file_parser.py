"""rule_file_parser：合规规则 CSV/XLSX 解析（从 compliance.py 抽出）。"""

import pytest

from copernicus.exceptions import ComplianceError
from copernicus.services.rule_file_parser import parse_rule_file


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


class TestParseCsv:
    def test_parses_numbered_rule_and_examples(self):
        rules, examples = parse_rule_file(
            _csv("1不得承诺保本保息,合格,实际话术示例\n"), "rules.csv"
        )
        assert len(rules) == 1
        assert rules[0].id == 1
        assert rules[0].content == "不得承诺保本保息"
        assert examples == ["规则1(不得承诺保本保息...): 实际话术示例"]

    def test_skips_header_row(self):
        rules, _ = parse_rule_file(
            _csv("序号,必备要素,检查结果\n1不得承诺保本保息,,\n"), "rules.csv"
        )
        assert len(rules) == 1

    def test_stops_at_issues_section(self):
        rules, _ = parse_rule_file(
            _csv("1不得承诺保本保息,,\n存在的问题,,\n2这条不该被解析,,\n"), "rules.csv"
        )
        assert len(rules) == 1

    def test_falls_back_to_sequential_id_without_leading_number(self):
        rules, _ = parse_rule_file(_csv("不得承诺保本保息,,\n"), "rules.csv")
        assert rules[0].id == 1
        assert rules[0].content == "不得承诺保本保息"

    def test_skips_blank_and_placeholder_cells(self):
        _, examples = parse_rule_file(
            _csv("1不得承诺保本保息,合格,不涉及,None,\n"), "rules.csv"
        )
        assert examples == []

    def test_gbk_encoded_file_decodes(self):
        rules, _ = parse_rule_file("1不得承诺保本保息".encode("gbk"), "rules.csv")
        assert rules[0].content == "不得承诺保本保息"

    def test_undecodable_bytes_raise_compliance_error(self):
        with pytest.raises(ComplianceError):
            parse_rule_file(b"\xff\xfe\x00\x01", "rules.csv")


class TestFilenameDispatch:
    def test_xlsx_extension_routes_to_xlsx_parser(self):
        # 非法 XLSX 字节内容：若走的是 csv 分支会被当成一行文本静默"解析成功"，
        # 走 xlsx 分支则会在 openpyxl 加载阶段报错——借此确认按扩展名分发正确。
        with pytest.raises(Exception):
            parse_rule_file(b"not a real xlsx", "rules.xlsx")

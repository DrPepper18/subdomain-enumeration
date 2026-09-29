"""Тесты CLI (interface)."""

import json
from unittest.mock import patch

import pytest

from interface import run
from services import DnsResolver, SubdomainSource


class _OneSubdomainSource(SubdomainSource):
    name = "fake"

    def find(self, domain: str) -> set[str]:
        return {f"www.{domain}"}


class _AllResolvedResolver(DnsResolver):
    def resolve(self, hostname: str) -> str | None:
        return "10.0.0.1"


@pytest.fixture(autouse=True)
def _patch_sources_and_resolver():
    with (
        patch(
            "interface.build_sources",
            return_value=[_OneSubdomainSource()],
        ),
        patch(
            "interface.SocketDnsResolver",
            return_value=_AllResolvedResolver(),
        ),
    ):
        yield


def test_run_prints_text_output(capsys) -> None:
    exit_code = run(["example.com"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "www.example.com" in captured.out
    assert "10.0.0.1" in captured.out


def test_run_prints_json_output(capsys) -> None:
    exit_code = run(["example.com", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    data = json.loads(captured.out)
    names = {item["subdomain"] for item in data}
    assert "www.example.com" in names


def test_run_saves_to_file(tmp_path, capsys) -> None:
    out_file = tmp_path / "result.json"
    exit_code = run(["example.com", "--json", "-o", str(out_file)])

    assert exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    names = {item["subdomain"] for item in data}
    assert "www.example.com" in names


def test_run_rejects_unknown_source() -> None:
    with pytest.raises(SystemExit):
        run(["example.com", "--sources", "not-a-real-source"])

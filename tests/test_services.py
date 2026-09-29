"""Тесты сервисов: источники, резолвер, writers, use case."""

import json
import socket
from unittest.mock import MagicMock, patch

import pytest
import requests

from models import Subdomain
from services import (
    AVAILABLE_SOURCES,
    AnubisDbSource,
    CrtShSource,
    EnumerateSubdomainsUseCase,
    HackerTargetSource,
    JsonResultWriter,
    SocketDnsResolver,
    TextResultWriter,
    _normalize,
    build_sources,
)

# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


def test_normalize_strips_and_lowercases() -> None:
    assert _normalize("  WWW.Example.COM.", "example.com") == "www.example.com"


def test_normalize_drops_wildcards() -> None:
    assert _normalize("*.example.com", "example.com") is None


def test_normalize_filters_unrelated_domain() -> None:
    assert _normalize("evil.attacker.com", "example.com") is None


def test_normalize_keeps_main_domain() -> None:
    assert _normalize("example.com", "example.com") == "example.com"


def test_normalize_rejects_invalid_hostname() -> None:
    assert _normalize("-bad.example.com", "example.com") is None


# ---------------------------------------------------------------------------
# Fake implementations for use-case tests
# ---------------------------------------------------------------------------


class FakeSource:
    def __init__(self, names: set[str], name: str = "fake") -> None:
        self._names = names
        self.name = name

    def find(self, domain: str) -> set[str]:
        return self._names


class FailingSource:
    name = "failing"

    def find(self, domain: str) -> set[str]:
        raise RuntimeError("source is down")


class FakeResolver:
    def __init__(self, table: dict[str, str]) -> None:
        self._table = table

    def resolve(self, hostname: str) -> str | None:
        return self._table.get(hostname)


# ---------------------------------------------------------------------------
# Use Case
# ---------------------------------------------------------------------------


def test_execute_merges_and_resolves() -> None:
    source = FakeSource({"www.example.com", "api.example.com"})
    resolver = FakeResolver({"www.example.com": "1.1.1.1", "example.com": "2.2.2.2"})
    use_case = EnumerateSubdomainsUseCase(sources=[source], resolver=resolver)

    result = use_case.execute("example.com")
    names = {s.name for s in result}

    assert names == {"www.example.com", "api.example.com", "example.com"}
    resolved = {s.name: s.ip_address for s in result}
    assert resolved["www.example.com"] == "1.1.1.1"
    assert resolved["example.com"] == "2.2.2.2"
    assert resolved["api.example.com"] is None


def test_execute_dedupes_across_sources() -> None:
    source_a = FakeSource({"dup.example.com"}, name="a")
    source_b = FakeSource({"DUP.example.com."}, name="b")
    resolver = FakeResolver({})
    use_case = EnumerateSubdomainsUseCase(sources=[source_a, source_b], resolver=resolver)

    result = use_case.execute("example.com")
    names = [s.name for s in result]
    assert names.count("dup.example.com") == 1


def test_execute_ignores_unrelated_domains() -> None:
    source = FakeSource({"evil.attacker.com", "www.example.com"})
    resolver = FakeResolver({})
    use_case = EnumerateSubdomainsUseCase(sources=[source], resolver=resolver)

    result = use_case.execute("example.com")
    names = {s.name for s in result}

    assert "evil.attacker.com" not in names
    assert "www.example.com" in names


def test_execute_survives_failing_source() -> None:
    ok_source = FakeSource({"www.example.com"})
    use_case = EnumerateSubdomainsUseCase(
        sources=[ok_source, FailingSource()], resolver=FakeResolver({})
    )

    result = use_case.execute("example.com")
    names = {s.name for s in result}
    assert "www.example.com" in names


def test_requires_at_least_one_source() -> None:
    with pytest.raises(ValueError):
        EnumerateSubdomainsUseCase(sources=[], resolver=FakeResolver({}))


def test_result_is_sorted() -> None:
    source = FakeSource({"z.example.com", "a.example.com"})
    use_case = EnumerateSubdomainsUseCase(sources=[source], resolver=FakeResolver({}))

    result = use_case.execute("example.com")
    assert [s.name for s in result] == sorted(s.name for s in result)


# ---------------------------------------------------------------------------
# CrtShSource
# ---------------------------------------------------------------------------


def _mock_session(status_code: int = 200, body: str = "[]") -> MagicMock:
    session = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.text = body
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError("boom")
    session.get.return_value = response
    return session


def test_crtsh_parses_name_value() -> None:
    body = json.dumps(
        [
            {"name_value": "www.example.com"},
            {"name_value": "api.example.com\nold.example.com"},
        ]
    )
    source = CrtShSource(session=_mock_session(body=body))
    assert source.find("example.com") == {"www.example.com", "api.example.com", "old.example.com"}


def test_crtsh_returns_empty_on_http_error() -> None:
    source = CrtShSource(session=_mock_session(status_code=500))
    assert source.find("example.com") == set()


def test_crtsh_returns_empty_on_invalid_json() -> None:
    source = CrtShSource(session=_mock_session(body="not json"))
    assert source.find("example.com") == set()


def test_crtsh_returns_empty_on_network_error() -> None:
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("no network")
    source = CrtShSource(session=session)
    assert source.find("example.com") == set()


# ---------------------------------------------------------------------------
# HackerTargetSource
# ---------------------------------------------------------------------------


def test_hackertarget_parses_csv() -> None:
    session = _mock_session(body="www.example.com,1.2.3.4\napi.example.com,5.6.7.8")
    source = HackerTargetSource(session=session)
    assert source.find("example.com") == {"www.example.com", "api.example.com"}


def test_hackertarget_returns_empty_on_error() -> None:
    session = _mock_session(body="error: something went wrong")
    source = HackerTargetSource(session=session)
    assert source.find("example.com") == set()


# ---------------------------------------------------------------------------
# AnubisDbSource
# ---------------------------------------------------------------------------


def test_anubisdb_parses_json_list() -> None:
    session = _mock_session(body=json.dumps(["www.example.com", "api.example.com"]))
    source = AnubisDbSource(session=session)
    assert source.find("example.com") == {"www.example.com", "api.example.com"}


def test_anubisdb_returns_empty_on_bad_response() -> None:
    session = _mock_session(status_code=404)
    source = AnubisDbSource(session=session)
    assert source.find("example.com") == set()


def test_anubisdb_returns_empty_on_non_list() -> None:
    session = _mock_session(body=json.dumps({"key": "value"}))
    source = AnubisDbSource(session=session)
    assert source.find("example.com") == set()


# ---------------------------------------------------------------------------
# SocketDnsResolver
# ---------------------------------------------------------------------------


def test_resolver_returns_ip() -> None:
    resolver = SocketDnsResolver(timeout=2.0)
    with patch("socket.gethostbyname", return_value="93.184.216.34") as mocked:
        result = resolver.resolve("example.com")
    mocked.assert_called_once_with("example.com")
    assert result == "93.184.216.34"


def test_resolver_returns_none_on_gaierror() -> None:
    resolver = SocketDnsResolver(timeout=2.0)
    with patch("socket.gethostbyname", side_effect=socket.gaierror("not found")):
        result = resolver.resolve("does-not-exist.example.com")
    assert result is None


def test_resolver_returns_none_on_timeout() -> None:
    resolver = SocketDnsResolver(timeout=0.01)

    def _slow(_hostname: str) -> str:
        import time

        time.sleep(1)
        return "1.1.1.1"

    with patch("socket.gethostbyname", side_effect=_slow):
        result = resolver.resolve("slow.example.com")
    assert result is None


# ---------------------------------------------------------------------------
# Result Writers
# ---------------------------------------------------------------------------


def test_text_writer_empty() -> None:
    writer = TextResultWriter()
    assert writer.render([]) == "Subdomains not found."


def test_text_writer_content() -> None:
    writer = TextResultWriter()
    subs = [Subdomain("www.example.com", "1.1.1.1"), Subdomain("api.example.com")]
    rendered = writer.render(subs)
    assert "Subdomains found: 2" in rendered
    assert "www.example.com" in rendered
    assert "api.example.com" in rendered


def test_json_writer_content() -> None:
    writer = JsonResultWriter()
    subs = [Subdomain("www.example.com", "1.1.1.1")]
    data = json.loads(writer.render(subs))
    assert data == [{"subdomain": "www.example.com", "ip": "1.1.1.1"}]


# ---------------------------------------------------------------------------
# build_sources
# ---------------------------------------------------------------------------


def test_build_sources_all() -> None:
    sources = build_sources()
    assert len(sources) == 3
    assert all(isinstance(s, type) or hasattr(s, "find") for s in sources)


def test_build_sources_selected() -> None:
    sources = build_sources(["crtsh"])
    assert len(sources) == 1
    assert sources[0].name == "crtsh"


def test_build_sources_unknown_raises() -> None:
    with pytest.raises(ValueError):
        build_sources(["nonexistent"])


# ---------------------------------------------------------------------------
# AVAILABLE_SOURCES
# ---------------------------------------------------------------------------


def test_available_sources_keys() -> None:
    assert set(AVAILABLE_SOURCES) == {"crtsh", "hackertarget", "anubisdb"}

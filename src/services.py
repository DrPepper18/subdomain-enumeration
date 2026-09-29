"""Интерфейсы (порты), реализации и use-case.

Порты определены как ABC-классы — это ядро Clean Architecture в данном
проекте. Use-case зависит только от портов, а не от конкретных реализаций.
Конкретные реализации (HTTP-запросы, socket) живут в этом же файле, но
ниже по иерархии — при желании их легко вынести в отдельные модули.
"""

from __future__ import annotations

import json
import re
import socket
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from models import Subdomain

# ---------------------------------------------------------------------------
# Порты (интерфейсы)
# ---------------------------------------------------------------------------


class SubdomainSource(ABC):
    """Источник "сырых" имён поддоменов (пассивный OSINT-источник)."""

    name: str = "unknown"

    @abstractmethod
    def find(self, domain: str) -> set[str]:
        """Вернуть множество имён поддоменов.

        Реализация обязана отлавливать сетевые ошибки и возвращать пустое
        множество, а не бросать исключение — падение одного источника не
        должно останавливать весь поиск.
        """


class DnsResolver(ABC):
    """Резолвер, определяющий текущий IP-адрес имени хоста."""

    @abstractmethod
    def resolve(self, hostname: str) -> str | None:
        """Вернуть IPv4-адрес или None, если имя не резолвится."""


class ResultWriter(ABC):
    """Форматтер результатов (text/json и т.п.)."""

    @abstractmethod
    def render(self, subdomains: Iterable[Subdomain]) -> str:
        """Сериализовать список поддоменов в строку."""


# ---------------------------------------------------------------------------
# Реализации портов
# ---------------------------------------------------------------------------

_VALID_HOSTNAME_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$")


def _normalize(raw: str, domain: str) -> str | None:
    """Привести сырое имя к нижнему регистру, отбросить мусор и wildcard'ы."""
    raw_name = raw.strip()
    if raw_name.startswith("*."):
        return None
    name = raw_name.lower().rstrip(".")
    if not name or not (name == domain or name.endswith(f".{domain}")):
        return None
    if not _VALID_HOSTNAME_RE.match(name):
        return None
    return name


# --- Sources ---------------------------------------------------------------


class CrtShSource(SubdomainSource):
    """crt.sh — публичный индекс Certificate Transparency логов."""

    name = "crtsh"
    _URL = "https://crt.sh/"

    def __init__(self, timeout: float = 15.0, session: requests.Session | None = None) -> None:
        self._timeout = timeout
        self._session = session or requests.Session()

    def find(self, domain: str) -> set[str]:
        params = {"q": f"%.{domain}", "output": "json"}
        try:
            response = self._session.get(self._URL, params=params, timeout=self._timeout)
            response.raise_for_status()
            entries = json.loads(response.text)
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            return set()

        found: set[str] = set()
        for entry in entries:
            value = entry.get("name_value", "")
            for line in value.splitlines():
                line = line.strip()
                if line:
                    found.add(line)
        return found


class HackerTargetSource(SubdomainSource):
    """HackerTarget — бесплатный API пассивного DNS-поиска."""

    name = "hackertarget"
    _URL = "https://api.hackertarget.com/hostsearch/"

    def __init__(self, timeout: float = 15.0, session: requests.Session | None = None) -> None:
        self._timeout = timeout
        self._session = session or requests.Session()

    def find(self, domain: str) -> set[str]:
        try:
            response = self._session.get(self._URL, params={"q": domain}, timeout=self._timeout)
            response.raise_for_status()
            text = response.text
        except requests.RequestException:
            return set()

        if "error" in text.lower() or "API count exceeded" in text:
            return set()

        found: set[str] = set()
        for line in text.splitlines():
            name = line.split(",")[0].strip()
            if name:
                found.add(name)
        return found


class AnubisDbSource(SubdomainSource):
    """AnubisDB — открытый агрегатор поддоменов."""

    name = "anubisdb"
    _URL_TEMPLATE = "https://anubisdb.com/anubis/subdomains/{domain}"

    def __init__(self, timeout: float = 15.0, session: requests.Session | None = None) -> None:
        self._timeout = timeout
        self._session = session or requests.Session()

    def find(self, domain: str) -> set[str]:
        try:
            response = self._session.get(
                self._URL_TEMPLATE.format(domain=domain), timeout=self._timeout
            )
            if response.status_code != 200:
                return set()
            data = response.json()
            if not isinstance(data, list):
                data = json.loads(response.text)
        except (requests.RequestException, ValueError, TypeError):
            return set()

        if not isinstance(data, list):
            return set()
        return {str(item).strip() for item in data if str(item).strip()}


AVAILABLE_SOURCES: dict[str, type[SubdomainSource]] = {
    "crtsh": CrtShSource,
    "hackertarget": HackerTargetSource,
    "anubisdb": AnubisDbSource,
}


def build_sources(names: list[str] | None = None) -> list[SubdomainSource]:
    """Инстанцировать источники по именам. None -> все источники."""
    selected = names or list(AVAILABLE_SOURCES)
    unknown = set(selected) - AVAILABLE_SOURCES.keys()
    if unknown:
        raise ValueError(f"Unknown sources: {', '.join(sorted(unknown))}")
    return [AVAILABLE_SOURCES[name]() for name in selected]


# --- DNS Resolver ----------------------------------------------------------


class SocketDnsResolver(DnsResolver):
    """Резолвер через стандартный модуль socket (без OS-команд)."""

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout

    def resolve(self, hostname: str) -> str | None:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(socket.gethostbyname, hostname)
            try:
                return future.result(timeout=self._timeout)
            except (socket.gaierror, UnicodeError, OSError):
                return None


# --- Result Writers --------------------------------------------------------


class TextResultWriter(ResultWriter):
    def render(self, subdomains: Iterable[Subdomain]) -> str:
        subdomains = list(subdomains)
        if not subdomains:
            return "Subdomains not found."
        lines = [f"Subdomains found: {len(subdomains)}", ""]
        lines += [str(sub) for sub in subdomains]
        return "\n".join(lines)


class JsonResultWriter(ResultWriter):
    def __init__(self, indent: int = 2) -> None:
        self._indent = indent

    def render(self, subdomains: Iterable[Subdomain]) -> str:
        payload = [sub.to_dict() for sub in subdomains]
        return json.dumps(payload, ensure_ascii=False, indent=self._indent)


def save_to_file(content: str, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content + "\n", encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Use Case
# ---------------------------------------------------------------------------


class EnumerateSubdomainsUseCase:
    """Собирает поддомены со всех источников, резолвит их IP и отдаёт результат."""

    def __init__(
        self,
        sources: Sequence[SubdomainSource],
        resolver: DnsResolver,
        max_workers: int = 20,
    ) -> None:
        if not sources:
            raise ValueError("At least one source must be provided.")
        self._sources = sources
        self._resolver = resolver
        self._max_workers = max_workers

    def execute(self, domain: str) -> list[Subdomain]:
        domain = domain.strip().lower().rstrip(".")
        raw_names = self._collect_raw_names(domain)
        return self._resolve_all(raw_names)

    def _collect_raw_names(self, domain: str) -> set[str]:
        found: set[str] = set()
        with ThreadPoolExecutor(max_workers=len(self._sources)) as pool:
            futures = [pool.submit(source.find, domain) for source in self._sources]
            for future in futures:
                try:
                    for raw in future.result():
                        normalized = _normalize(raw, domain)
                        if normalized:
                            found.add(normalized)
                except Exception:
                    continue
        found.add(domain)
        return found

    def _resolve_all(self, names: Iterable[str]) -> list[Subdomain]:
        names = sorted(names)
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            ips = list(pool.map(self._resolver.resolve, names))
        results = [Subdomain(name=n, ip_address=ip) for n, ip in zip(names, ips, strict=True)]
        return sorted(results)

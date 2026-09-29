"""Доменная сущность — поддомен с IP-адресом."""

from __future__ import annotations

from dataclasses import dataclass

NOT_APPLICABLE = "N/A"


@dataclass(frozen=True, slots=True, order=True)
class Subdomain:
    """Поддомен вместе с его текущим IP-адресом (если он резолвится)."""

    name: str
    ip_address: str | None = None

    @property
    def resolved(self) -> bool:
        return self.ip_address is not None

    def to_dict(self) -> dict[str, str]:
        return {"subdomain": self.name, "ip": self.ip_address or NOT_APPLICABLE}

    def __str__(self) -> str:  # noqa: D105
        width = 44 if self.ip_address is not None else 40
        return f"{self.name:<{width}}{self.ip_address or NOT_APPLICABLE}"

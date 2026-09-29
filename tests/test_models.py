"""Тесты доменной сущности Subdomain."""

from dataclasses import FrozenInstanceError

import pytest

from models import NOT_APPLICABLE, Subdomain


def test_subdomain_str_format() -> None:
    sub = Subdomain(name="www.example.com", ip_address="1.2.3.4")
    assert str(sub) == "www.example.com                             1.2.3.4"


def test_subdomain_str_format_na() -> None:
    sub = Subdomain(name="test.example.com")
    assert str(sub) == f"test.example.com                        {NOT_APPLICABLE}"


def test_subdomain_to_dict() -> None:
    sub = Subdomain(name="api.example.com", ip_address="5.6.7.8")
    assert sub.to_dict() == {"subdomain": "api.example.com", "ip": "5.6.7.8"}


def test_subdomain_to_dict_na() -> None:
    sub = Subdomain(name="noip.example.com")
    assert sub.to_dict() == {"subdomain": "noip.example.com", "ip": NOT_APPLICABLE}


def test_subdomain_resolved_property() -> None:
    assert Subdomain(name="x.com", ip_address="1.1.1.1").resolved is True
    assert Subdomain(name="x.com").resolved is False


def test_subdomain_ordering() -> None:
    a = Subdomain(name="a.example.com")
    b = Subdomain(name="b.example.com")
    assert a < b
    assert sorted([b, a]) == [a, b]


def test_subdomain_is_immutable() -> None:
    sub = Subdomain(name="example.com")
    with pytest.raises(FrozenInstanceError):
        sub.name = "hacked.com"

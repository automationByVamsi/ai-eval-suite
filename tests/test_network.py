"""Smoke tests for shared HTTP request utils (no network)."""

from __future__ import annotations

from src.core import network as net


def test_split_host_path():
    assert net.split_host_path("http://localhost:8080") == ("http", "localhost:8080", "")
    assert net.split_host_path("https://host.example.com/v1") == (
        "https",
        "host.example.com",
        "/v1",
    )


def test_with_params():
    url = net._with_params("https://h/path", {"format": "json"})
    assert "format=json" in url
    url2 = net._with_params("https://h/path?a=1", {"b": "2"})
    assert "a=1" in url2 and "b=2" in url2


def test_verbs_are_exported():
    assert callable(net.get)
    assert callable(net.post)
    assert callable(net.put)
    assert callable(net.patch)
    assert callable(net.request)

"""Tests for the web query abuse guard (PLAN.md K-14). Offline: no scan runs."""

from __future__ import annotations

import threading

import pytest

from karne import storage
from karne.models import Scan
from karne.web import query


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "karne.db"
    conn = storage.connect(path)
    storage.init_db(conn)
    conn.close()
    monkeypatch.setattr(query.reports, "DB_PATH", path)
    monkeypatch.setattr(query, "_guard", query._Guard())
    return path


def _settings(cooldown: int = 600, max_concurrent: int = 4) -> dict:
    return {"web": {"rescan_cooldown_seconds": cooldown, "max_concurrent_scans": max_concurrent}}


def _insert_adhoc_scan(path, domain: str) -> int:
    conn = storage.connect(path)
    try:
        d = storage.get_or_create_domain(conn, domain, source="web")
        return storage.insert_scan(conn, Scan(domain_id=d.id, scanner_version="0.1.0"))
    finally:
        conn.close()


def test_web_limits_reads_settings_and_clamps():
    assert query.web_limits(_settings(300, 2)) == (300, 2)
    assert query.web_limits({}) == (600, 4)
    assert query.web_limits(_settings(-5, 0)) == (0, 1)


def test_recent_adhoc_scan_is_returned_without_scanning(db, monkeypatch):
    existing = _insert_adhoc_scan(db, "example.com")
    monkeypatch.setattr(query.dns_email, "load_settings", lambda: _settings())

    def boom(domain, settings):
        raise AssertionError("must not rescan within the cooldown")

    monkeypatch.setattr(query, "_scan_and_store", boom)
    assert query.run_live_scan("example.com") == existing


def test_zero_cooldown_always_scans(db, monkeypatch):
    _insert_adhoc_scan(db, "example.com")
    monkeypatch.setattr(query.dns_email, "load_settings", lambda: _settings(cooldown=0))
    monkeypatch.setattr(query, "_scan_and_store", lambda domain, settings: 999)
    assert query.run_live_scan("example.com") == 999


def test_slot_is_released_after_a_failed_scan(db, monkeypatch):
    monkeypatch.setattr(query.dns_email, "load_settings", lambda: _settings(max_concurrent=1))

    def fail(domain, settings):
        raise RuntimeError("collector crashed")

    monkeypatch.setattr(query, "_scan_and_store", fail)
    with pytest.raises(RuntimeError):
        query.run_live_scan("example.com")
    monkeypatch.setattr(query, "_scan_and_store", lambda domain, settings: 7)
    assert query.run_live_scan("example.com") == 7


def test_busy_when_all_slots_taken(db, monkeypatch):
    monkeypatch.setattr(query.dns_email, "load_settings", lambda: _settings(max_concurrent=1))
    assert query._guard.claim("a.com", 1) is None  # another scan holds the only slot
    monkeypatch.setattr(query, "_scan_and_store", lambda domain, settings: 1)
    with pytest.raises(query.ScanBusy):
        query.run_live_scan("b.com")
    query._guard.release("a.com")
    assert query.run_live_scan("b.com") == 1


def test_second_query_for_same_domain_waits_for_the_first(db, monkeypatch):
    monkeypatch.setattr(query.dns_email, "load_settings", lambda: _settings())
    started = threading.Event()
    finish = threading.Event()
    calls: list[str] = []

    def slow_scan(domain, settings):
        calls.append(domain)
        started.set()
        finish.wait(5)
        return _insert_adhoc_scan(db, domain)

    monkeypatch.setattr(query, "_scan_and_store", slow_scan)
    results: dict[str, int] = {}
    first = threading.Thread(target=lambda: results.setdefault("a", query.run_live_scan("x.com")))
    first.start()
    assert started.wait(5)
    second = threading.Thread(target=lambda: results.setdefault("b", query.run_live_scan("x.com")))
    second.start()
    finish.set()
    first.join(5)
    second.join(5)
    assert calls == ["x.com"]  # one scan only
    assert results["a"] == results["b"]

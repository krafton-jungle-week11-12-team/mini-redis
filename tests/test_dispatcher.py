"""입력값 검사 테스트 (VAL). HTTP 없이 dispatcher.execute를 바로 불러요.
케이스 ID는 docs/test-cases/phase1/test-cases.md를 따라요."""

import pytest

from mini_redis import dispatcher
from mini_redis.store import HashTable


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    """테스트마다 빈 저장소로 시작해요."""
    monkeypatch.setattr(dispatcher, "store", HashTable())


def assert_error(result, status, code):
    got_status, payload = result
    assert got_status == status
    assert payload["ok"] is False
    assert payload["result"] is None
    assert payload["error"]["code"] == code


@pytest.mark.parametrize("case_id, command, args", [
    ("VAL-01", "SET", []),
    ("VAL-02", "SET", ["key1", "val1", "val2"]),
    ("VAL-03", "SET", ["key1"]),
    ("VAL-04", "GET", []),
    ("VAL-05", "GET", ["key1", "key2"]),
])
def test_wrong_args(case_id, command, args):
    assert_error(dispatcher.execute(command, args), 400, "WRONG_ARGS")


@pytest.mark.parametrize("case_id, args", [
    ("VAL-06", [None, "val1"]),
    ("VAL-07", ["key1", None]),
    ("VAL-14", [123, "val1"]),
    ("VAL-15", ["key1", {"a": 1}]),
])
def test_wrong_type(case_id, args):
    assert_error(dispatcher.execute("SET", args), 400, "WRONG_TYPE")


def test_val08_key_99_bytes_allowed():
    key = "k" * 99
    status, payload = dispatcher.execute("SET", [key, "val1"])
    assert status == 200
    assert payload["result"] == "OK"
    assert dispatcher.execute("GET", [key])[1]["result"] == "val1"


def test_val09_key_over_99_bytes_rejected():
    assert_error(dispatcher.execute("SET", ["k" * 100, "val1"]), 400, "KEY_TOO_LONG")


def test_val12_key_length_counted_in_bytes_rejected():
    key = "가" * 34  # 34글자, 102byte
    assert_error(dispatcher.execute("SET", [key, "val1"]), 400, "KEY_TOO_LONG")


def test_val13_key_length_counted_in_bytes_allowed():
    key = "가" * 33  # 33글자, 99byte
    status, payload = dispatcher.execute("SET", [key, "val1"])
    assert status == 200
    assert payload["result"] == "OK"


def test_info_reports_store_stats():
    dispatcher.execute("SET", ["a", "1"])
    dispatcher.execute("SET", ["b", "2"])
    dispatcher.execute("DEL", ["a"])
    status, payload = dispatcher.execute("INFO", [])
    assert status == 200
    assert payload["result"] == {
        "size": 1,
        "capacity": dispatcher.store.capacity,
        "tombstones": 1,
    }


def test_info_rejects_args():
    assert_error(dispatcher.execute("INFO", ["x"]), 400, "WRONG_ARGS")


def test_flushall_removes_all_and_resets_table():
    for i in range(10):                        # 8칸 → 16칸으로 확장시켜요
        dispatcher.execute("SET", [f"k{i}", "v"])
    dispatcher.execute("DEL", ["k0"])
    status, payload = dispatcher.execute("FLUSHALL", [])
    assert status == 200
    assert payload["result"] == 9              # 지운 개수
    assert dispatcher.execute("DBSIZE", [])[1]["result"] == 0
    assert dispatcher.execute("GET", ["k1"])[1]["result"] is None
    assert dispatcher.execute("INFO", [])[1]["result"] == {
        "size": 0, "capacity": 8, "tombstones": 0,
    }


def test_flushall_on_empty_store_returns_zero():
    status, payload = dispatcher.execute("FLUSHALL", [])
    assert status == 200
    assert payload["result"] == 0


def test_flushall_then_set_works():
    dispatcher.execute("SET", ["a", "1"])
    dispatcher.execute("FLUSHALL", [])
    dispatcher.execute("SET", ["a", "2"])
    assert dispatcher.execute("GET", ["a"])[1]["result"] == "2"


def test_flushall_rejects_args():
    assert_error(dispatcher.execute("FLUSHALL", ["x"]), 400, "WRONG_ARGS")

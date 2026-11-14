"""명령어 테스트. HTTP 없이 dispatcher.execute를 바로 불러요.
케이스 ID는 docs/test-cases/phase1/test-cases.md(VAL),
phase3/test-cases.md(MST, MGT, GTS, SNX, SXX, INC, DEC, ARG),
phase4/test-cases.md(STL, LZY, OVW, TTL, DBS, REG)를 따라요."""

import pytest

from mini_redis import dispatcher
from mini_redis import store as store_module
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
    ("VAL-02", "SET", ["key1", "val1", "30", "x"]),   # 세 번째 인자는 TTL이라 4개로 확인해요 (REG-03)
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


def test_flush_removes_all_and_resets_table():
    for i in range(10):                        # 8칸 → 16칸으로 확장시켜요
        dispatcher.execute("SET", [f"k{i}", "v"])
    dispatcher.execute("DEL", ["k0"])
    status, payload = dispatcher.execute("FLUSH", [])
    assert status == 200
    assert payload["result"] == 9              # 지운 개수
    assert dispatcher.execute("DBSIZE", [])[1]["result"] == 0
    assert dispatcher.execute("GET", ["k1"])[1]["result"] is None
    assert dispatcher.execute("INFO", [])[1]["result"] == {
        "size": 0, "capacity": 8, "tombstones": 0,
    }


def test_flush_on_empty_store_returns_zero():
    status, payload = dispatcher.execute("FLUSH", [])
    assert status == 200
    assert payload["result"] == 0


def test_flush_then_set_works():
    dispatcher.execute("SET", ["a", "1"])
    dispatcher.execute("FLUSH", [])
    dispatcher.execute("SET", ["a", "2"])
    assert dispatcher.execute("GET", ["a"])[1]["result"] == "2"


def test_flush_rejects_args():
    assert_error(dispatcher.execute("FLUSH", ["x"]), 400, "WRONG_ARGS")


# ---------------------------------------------------------------------------
# Phase 3 원자적 명령어
# ---------------------------------------------------------------------------

INT64_MAX = "9223372036854775807"
INT64_MIN = "-9223372036854775808"


def run(command, *args):
    """성공을 확인하고 result만 돌려줘요."""
    status, payload = dispatcher.execute(command, list(args))
    assert status == 200, payload
    assert payload["ok"] is True
    return payload["result"]


def fill(n):
    for k in range(1, n + 1):
        run("SET", f"key{k}", f"val{k}")


def info():
    return run("INFO")


# MSET ----------------------------------------------------------------------

def test_mst01_mset_stores_all():
    assert run("MSET", "key1", "val1", "key2", "val2") == "OK"
    assert run("GET", "key1") == "val1"
    assert run("GET", "key2") == "val2"


def test_mst02_mset_resizes_once_before_writing():
    fill(6)
    run("MSET", "key7", "val7", "key8", "val8", "key9", "val9")
    assert info() == {"size": 9, "capacity": 16, "tombstones": 0}


def test_mst03_mset_odd_args_stores_nothing():
    assert_error(dispatcher.execute("MSET", ["key1", "val1", "key2"]), 400, "WRONG_ARGS")
    assert run("DBSIZE") == 0


def test_mst04_mset_overwrites_existing_key():
    run("SET", "key1", "old")
    run("MSET", "key1", "new", "key2", "val2")
    assert run("GET", "key1") == "new"
    assert run("DBSIZE") == 2


def test_mst05_mset_same_key_keeps_last_value():
    run("MSET", "key1", "a", "key1", "b")
    assert run("GET", "key1") == "b"
    assert run("DBSIZE") == 1


def test_mst06_mset_later_key_too_long_stores_nothing():
    assert_error(dispatcher.execute("MSET", ["key1", "val1", "k" * 100, "val2"]), 400, "KEY_TOO_LONG")
    assert run("DBSIZE") == 0


def test_mst07_mset_later_value_not_string_stores_nothing():
    assert_error(dispatcher.execute("MSET", ["key1", "val1", "key2", 123]), 400, "WRONG_TYPE")
    assert run("DBSIZE") == 0


def test_mst08_mset_store_full_stores_nothing(monkeypatch):
    monkeypatch.setattr(store_module, "MAX_CAPACITY", 8)
    fill(3)
    args = ["key4", "val4", "key5", "val5", "key6", "val6", "key7", "val7"]
    assert_error(dispatcher.execute("MSET", args), 507, "STORE_FULL")   # (3 + 4) / 8 > 0.75
    assert run("DBSIZE") == 3
    assert run("GET", "key4") is None


def test_mst09_mset_over_20_keys():
    args = [x for k in range(1, 22) for x in (f"key{k}", f"val{k}")]
    assert_error(dispatcher.execute("MSET", args), 400, "WRONG_ARGS")


# MGET ----------------------------------------------------------------------

def test_mgt01_mget_returns_all():
    fill(3)
    assert run("MGET", "key1", "key2", "key3") == ["val1", "val2", "val3"]


def test_mgt02_mget_missing_key_is_nil():
    fill(3)
    assert run("MGET", "key1", "key2", "key4") == ["val1", "val2", None]


def test_mgt03_mget_keeps_order_and_duplicates():
    fill(2)
    assert run("MGET", "key2", "key1", "key2") == ["val2", "val1", "val2"]


def test_mgt04_mget_over_20_keys():
    args = [f"key{k}" for k in range(1, 22)]
    assert_error(dispatcher.execute("MGET", args), 400, "WRONG_ARGS")


def test_mgt05_mget_later_key_too_long():
    assert_error(dispatcher.execute("MGET", ["key1", "k" * 100]), 400, "KEY_TOO_LONG")


# GETSET --------------------------------------------------------------------

def test_gts01_getset_missing_key_returns_nil_and_stores():
    assert run("GETSET", "key1", "val1") is None
    assert run("GET", "key1") == "val1"


def test_gts02_getset_returns_old_value():
    run("SET", "key1", "0")
    assert run("GETSET", "key1", "1") == "0"
    assert run("GET", "key1") == "1"


def test_gts03_getset_resizes_at_boundary():
    fill(6)
    assert run("GETSET", "key7", "val7") is None
    assert info()["capacity"] == 16


# SETNX ---------------------------------------------------------------------

def test_snx01_setnx_missing_key_stores():
    assert run("SETNX", "key1", "val1") == 1
    assert run("GET", "key1") == "val1"


def test_snx02_setnx_existing_key_does_nothing():
    run("SET", "key1", "val1")
    assert run("SETNX", "key1", "val2") == 0
    assert run("GET", "key1") == "val1"


def test_snx03_setnx_fail_does_not_resize():
    fill(6)
    assert run("SETNX", "key6", "x") == 0
    assert info()["capacity"] == 8               # 같은 상황에서 SET은 확장해요 (EXP-03)


def test_snx04_setnx_new_key_resizes_then_stores():
    fill(6)
    assert run("SETNX", "key7", "val7") == 1
    assert run("GET", "key7") == "val7"
    assert info()["capacity"] == 16


# SETXX ---------------------------------------------------------------------

def test_sxx01_setxx_missing_key_does_nothing():
    assert run("SETXX", "key1", "val1") == 0
    assert run("GET", "key1") is None
    assert run("DBSIZE") == 0


def test_sxx02_setxx_existing_key_overwrites():
    run("SET", "key1", "val1")
    assert run("SETXX", "key1", "val2") == 1
    assert run("GET", "key1") == "val2"


def test_sxx03_setxx_does_not_resize_at_boundary():
    fill(6)
    assert run("SETXX", "key6", "new") == 1
    assert info()["capacity"] == 8


# INCR ----------------------------------------------------------------------

def test_inc01_incr_adds_one():
    run("SET", "key1", "1")
    assert run("INCR", "key1") == 2              # 응답은 정수
    assert run("GET", "key1") == "2"             # 저장은 문자열


def test_inc02_incr_missing_key_starts_at_zero():
    assert run("INCR", "key1") == 1
    assert run("GET", "key1") == "1"


def test_inc03_incr_negative():
    run("SET", "key1", "-5")
    assert run("INCR", "key1") == -4


def test_inc04_incr_not_integer_keeps_value():
    run("SET", "key1", "string")
    assert_error(dispatcher.execute("INCR", ["key1"]), 400, "NOT_INTEGER")
    assert run("GET", "key1") == "string"


@pytest.mark.parametrize("value", [" 1", "+1", "1_000", "1\n", "1.5", ""])
def test_inc05_incr_rejects_non_integer_format(value):
    run("SET", "key1", value)
    assert_error(dispatcher.execute("INCR", ["key1"]), 400, "NOT_INTEGER")


def test_inc06_incr_overflow_keeps_value():
    run("SET", "key1", INT64_MAX)
    assert_error(dispatcher.execute("INCR", ["key1"]), 400, "INTEGER_OVERFLOW")
    assert run("GET", "key1") == INT64_MAX


def test_inc07_incr_stored_value_out_of_range():
    run("SET", "key1", "9223372036854775808")    # INT64_MAX + 1
    assert_error(dispatcher.execute("INCR", ["key1"]), 400, "NOT_INTEGER")


def test_inc08_incr_new_key_resizes_at_boundary():
    fill(6)
    assert run("INCR", "counter") == 1
    assert info()["capacity"] == 16


def test_inc09_incr_existing_key_does_not_resize():
    fill(5)
    run("SET", "num", "1")
    assert run("INCR", "num") == 2
    assert info()["capacity"] == 8               # 같은 상황에서 SET은 확장해요 (EXP-03)


# DECR ----------------------------------------------------------------------

def test_dec01_decr_subtracts_one():
    run("SET", "key1", "1")
    assert run("DECR", "key1") == 0
    assert run("GET", "key1") == "0"


def test_dec02_decr_missing_key_starts_at_zero():
    assert run("DECR", "key1") == -1


def test_dec03_decr_not_integer():
    run("SET", "key1", "string")
    assert_error(dispatcher.execute("DECR", ["key1"]), 400, "NOT_INTEGER")


def test_dec04_decr_overflow():
    run("SET", "key1", INT64_MIN)
    assert_error(dispatcher.execute("DECR", ["key1"]), 400, "INTEGER_OVERFLOW")


# 인자 검사 -----------------------------------------------------------------

@pytest.mark.parametrize("command, args", [
    ("GETSET", ["key1"]),
    ("SETNX", ["key1"]),
    ("SETXX", ["key1"]),
    ("INCR", []),
    ("DECR", ["key1", "key2"]),
    ("MSET", []),
    ("MGET", []),
])
def test_arg01_wrong_arg_count(command, args):
    assert_error(dispatcher.execute(command, args), 400, "WRONG_ARGS")


@pytest.mark.parametrize("command, args", [
    ("GETSET", ["key1", 123]),
    ("SETNX", ["key1", None]),
    ("SETXX", [123, "val1"]),
])
def test_arg02_non_string_arg(command, args):
    assert_error(dispatcher.execute(command, args), 400, "WRONG_TYPE")


# ---------------------------------------------------------------------------
# Phase 4 만료(TTL). 케이스 ID는 docs/test-cases/phase4/test-cases.md를 따라요.
# REG-02(기존 테스트가 그대로 통과)는 위의 Phase 1 ~ 3 테스트 전체가 확인해요.
# ---------------------------------------------------------------------------

@pytest.fixture
def clock(clock, monkeypatch):
    """가짜 시계를 넣은 빈 저장소로 바꿔요. 테스트에서 clock.now를 바꿔 시간을 옮겨요."""
    monkeypatch.setattr(dispatcher, "store", HashTable(clock=lambda: clock.now))
    return clock


# SET TTL 지정 ---------------------------------------------------------------

def test_stl01_alive_until_expire_at_then_gone(clock):
    run("SET", "key1", "val1", "10")
    clock.now = 9.999
    assert run("GET", "key1") == "val1"
    clock.now = 10                               # now >= expire_at이면 만료
    assert run("GET", "key1") is None


def test_stl02_set_again_replaces_ttl(clock):
    run("SET", "key1", "val1", "10")
    assert run("SET", "key1", "val1", "100") == "OK"
    clock.now = 50
    assert run("TTL", "key1") == 50


@pytest.mark.parametrize("ttl", ["1", "1728000"])
def test_stl03_ttl_range_ends_are_stored(clock, ttl):
    assert run("SET", "key1", "val1", ttl) == "OK"
    assert run("TTL", "key1") == int(ttl)


@pytest.mark.parametrize("ttl", [
    "0", "1728001", "-1", "007", " 1", "+1", "1.5", "abc", "99999999999999",
])
def test_stl04_invalid_ttl_stores_nothing(clock, ttl):
    assert_error(dispatcher.execute("SET", ["key1", "val1", ttl]), 400, "INVALID_TTL")
    assert run("DBSIZE") == 0                    # 검사가 저장보다 먼저예요


# 지연 만료 -------------------------------------------------------------------

def test_lzy01_get_expired_key_becomes_tombstone(clock):
    run("SET", "key1", "val1", "10")
    clock.now = 10
    assert run("GET", "key1") is None
    assert info()["size"] == 0
    assert info()["tombstones"] == 1             # size + tombstones는 그대로예요


@pytest.mark.parametrize("command, args, expected", [
    ("EXISTS", ["key1"], 0),
    ("DEL", ["key1"], 0),
    ("SETNX", ["key1", "x"], 1),
    ("SETXX", ["key1", "x"], 0),
    ("GETSET", ["key1", "x"], None),
    ("INCR", ["key1"], 1),
    ("MGET", ["key1"], [None]),
    ("TTL", ["key1"], -2),
])
def test_lzy03_expired_key_is_missing_for_every_command(clock, command, args, expected):
    run("SET", "key1", "val1", "10")
    clock.now = 10
    assert run(command, *args) == expected


@pytest.mark.parametrize("command, args", [
    ("SETNX", ["key1", "val2"]),
    ("INCR", ["key1"]),
])
def test_lzy04_new_key_in_expired_slot_has_no_old_ttl(clock, command, args):
    run("SET", "key1", "val1", "10")
    clock.now = 10
    run(command, *args)
    assert run("TTL", "key1") == -1


# 덮어쓰기와 TTL ---------------------------------------------------------------

@pytest.mark.parametrize("command, args", [
    ("SET", ["key1", "val2"]),
    ("GETSET", ["key1", "val2"]),
    ("SETXX", ["key1", "val2"]),
    ("MSET", ["key1", "val2"]),
])
def test_ovw01_overwrite_clears_ttl(clock, command, args):
    run("SET", "key1", "val1", "10")
    run(command, *args)
    assert run("TTL", "key1") == -1


@pytest.mark.parametrize("command", ["INCR", "DECR"])
def test_ovw02_incr_decr_keep_ttl(clock, command):
    run("SET", "key1", "1", "10")
    run(command, "key1")
    assert run("TTL", "key1") == 10


# TTL ---------------------------------------------------------------------------

def test_ttl01_remaining_time_rounds_up(clock):
    run("SET", "key1", "val1", "10")
    clock.now = 0.6
    assert run("TTL", "key1") == 10              # 남은 9.4초
    clock.now = 9.999
    assert run("TTL", "key1") == 1               # 살아 있는 key는 0으로 보이지 않아요


def test_ttl02_no_expiry_is_minus_one(clock):
    run("SET", "key1", "val1")
    assert run("TTL", "key1") == -1


def test_ttl03_missing_key_is_minus_two(clock):
    assert run("TTL", "key1") == -2


@pytest.mark.parametrize("args", [[], ["key1", "key2"]])
def test_ttl04_wrong_arg_count(clock, args):
    assert_error(dispatcher.execute("TTL", args), 400, "WRONG_ARGS")


# DBSIZE ------------------------------------------------------------------------

def test_dbs02_expired_key_counted_until_cleaned(clock):
    run("SET", "key1", "val1", "10")
    run("SET", "key2", "val2")
    clock.now = 10
    assert run("DBSIZE") == 2                    # 아무도 조회하지 않아 OCCUPIED로 남아요
    assert run("GET", "key1") is None
    assert run("DBSIZE") == 1


# 회귀 --------------------------------------------------------------------------

def test_reg03_third_set_arg_is_ttl(clock):
    assert_error(dispatcher.execute("SET", ["key1", "val1", "val2"]), 400, "INVALID_TTL")
    assert_error(dispatcher.execute("SET", ["key1", "val1", "30", "x"]), 400, "WRONG_ARGS")


def test_reg04_flush_keeps_clock(clock):
    run("SET", "key1", "val1")
    run("FLUSH")
    run("SET", "key1", "val1", "10")
    clock.now = 10                               # 실제 시계로 바뀌었다면 값이 남아요
    assert run("GET", "key1") is None

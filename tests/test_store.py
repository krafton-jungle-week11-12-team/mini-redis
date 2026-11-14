"""해시 테이블(store.py) 테스트. 케이스 ID는 docs/test-cases/phase1/test-cases.md와
phase3/test-cases.md(ENS, WRT, REG)를 따라요.

표기법
- fill N: key1~keyN을 val1~valN으로 차례로 저장
- col N: hash mock으로 key1~keyN의 홈 버킷을 모두 1번으로 고정 (keyK는 K번 버킷에 저장)
- hash H부터 col N: 홈 버킷을 H번으로 고정
"""

import pytest

from mini_redis import store as store_module
from mini_redis.store import MAX_CAPACITY, HashTable, State, StoreFullError, fnv1a_64


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------

@pytest.fixture
def table():
    return HashTable()


@pytest.fixture
def fix_hash(monkeypatch):
    """key별 해시값을 고정해요. 등록하지 않은 key는 실제 해시 함수를 써요."""
    mapping = {}
    real = store_module.fnv1a_64
    monkeypatch.setattr(store_module, "fnv1a_64", lambda key: mapping[key] if key in mapping else real(key))
    return mapping


def fill(table, n):
    for k in range(1, n + 1):
        table.set(f"key{k}", f"val{k}")


def col(table, fix_hash, n, home=1):
    """key1~keyN의 홈 버킷을 home으로 고정하고 차례로 저장해요."""
    for k in range(1, n + 1):
        fix_hash[f"key{k}"] = home
    fill(table, n)


def bucket_of(table, key):
    """key가 저장된 버킷을 찾아요."""
    matches = [b for b in table.buckets if b.state == State.OCCUPIED and b.key == key]
    assert len(matches) == 1
    return matches[0]


# ---------------------------------------------------------------------------
# 확장/적재율
# ---------------------------------------------------------------------------

def test_exp01_no_resize_at_or_below_load_factor(table):
    fill(table, 5)
    table.set("key6", "val6")
    assert table.size == 6
    assert table.capacity == 8


def test_exp02_resize_over_load_factor(table):
    fill(table, 6)
    table.set("key7", "val7")
    assert table.capacity == 16


def test_exp03_overwrite_at_boundary_also_resizes(table):
    fill(table, 6)
    table.set("key6", "val6x")
    assert table.capacity == 16
    assert table.size == 6
    assert table.get("key6") == "val6x"


def test_exp04_load_factor_counts_tombstones_and_resize_drops_them(table):
    fill(table, 6)
    table.delete("key1")
    table.set("key7", "val7")
    assert table.capacity == 16
    assert table.tombstones == 0
    assert table.size == 6


def test_exp05_get_existing_key_after_resize(table):
    fill(table, 7)
    assert table.get("key1") == "val1"


def test_exp06_get_deleted_key_after_resize(table):
    fill(table, 7)
    table.delete("key1")
    assert table.get("key1") is None


# ---------------------------------------------------------------------------
# 탐사(probe)
# ---------------------------------------------------------------------------

def test_prb01_probe_starts_at_home_bucket(table, fix_hash):
    fix_hash["key1"] = 3
    table.set("key1", "val1")
    assert table._probe("key1") == (3, 3)


def test_prb02_probe_stops_at_empty(table, fix_hash):
    col(table, fix_hash, 1)
    fix_hash["key2"] = 1
    assert table._probe("key2") == (None, 2)


def test_prb03_probe_passes_tombstone_to_find_key(table, fix_hash):
    col(table, fix_hash, 3)
    table.delete("key2")
    assert table._probe("key3") == (3, 3)


def test_prb04_probe_remembers_first_tombstone(table, fix_hash):
    col(table, fix_hash, 3)
    table.delete("key2")
    table.delete("key3")
    assert table._probe("key3") == (None, 2)


# ---------------------------------------------------------------------------
# 랩어라운드
# ---------------------------------------------------------------------------

def test_wrp01_after_last_bucket_comes_zero(table, fix_hash):
    col(table, fix_hash, 3, home=6)  # key1@6, key2@7, key3@0
    fix_hash["key4"] = 6
    assert table._probe("key4") == (None, 1)


def test_wrp02_find_key_past_zero(table, fix_hash):
    col(table, fix_hash, 4, home=6)  # key1@6, key2@7, key3@0, key4@1
    assert table._probe("key4") == (1, 1)


# ---------------------------------------------------------------------------
# SET
# ---------------------------------------------------------------------------

def test_set01_fills_empty_bucket(table):
    table.set("key1", "val1")
    assert table.get("key1") == "val1"
    b = bucket_of(table, "key1")
    assert b.state == State.OCCUPIED
    assert b.key == "key1"
    assert b.key_len == 4
    assert b.value == "val1"
    assert b.value_len == 4


def test_set02_overwrite_same_key(table):
    table.set("key1", "val1")
    table.set("key1", "val2")
    assert table.get("key1") == "val2"
    assert table.size == 1


def test_set03_overwrite_key_behind_tombstone(table, fix_hash):
    col(table, fix_hash, 3)
    table.delete("key2")
    table.set("key3", "val3x")
    assert table.get("key3") == "val3x"
    assert table.size == 2
    assert table.tombstones == 1


def test_set04_empty_string_is_not_nil(table):
    table.set("key1", "")
    assert table.get("key1") == ""


def test_set05_overwrite_updates_value_len(table):
    table.set("key1", "val1")
    table.set("key1", "value22")
    assert bucket_of(table, "key1").value_len == 7


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------

def test_get01_missing_key(table):
    assert table.get("key1") is None


def test_get02_deleted_key(table):
    table.set("key1", "val1")
    table.delete("key1")
    assert table.get("key1") is None


def test_get03_collided_key(table, fix_hash):
    col(table, fix_hash, 3)
    assert table.get("key3") == "val3"


def test_get04_get_past_tombstone(table, fix_hash):
    col(table, fix_hash, 3)
    table.delete("key2")
    assert table.get("key3") == "val3"


# ---------------------------------------------------------------------------
# DEL
# ---------------------------------------------------------------------------

def test_del01_missing_key(table):
    assert table.delete("key1") == 0


def test_del02_deleted_bucket_becomes_tombstone(table):
    fill(table, 2)
    table.delete("key1")
    assert table.tombstones == 1
    assert table.size == 1


def test_del03_returns_deleted_count(table):
    table.set("key1", "val1")
    assert table.delete("key1") == 1


def test_del04_delete_twice(table):
    fill(table, 1)
    table.delete("key1")
    assert table.delete("key1") == 0
    assert table.tombstones == 1


# ---------------------------------------------------------------------------
# EXISTS
# ---------------------------------------------------------------------------

def test_exs01_stored_key(table):
    table.set("key1", "val1")
    assert table.exists("key1") == 1


def test_exs02_missing_key(table):
    assert table.exists("key1") == 0


def test_exs03_deleted_key(table):
    table.set("key1", "val1")
    table.delete("key1")
    assert table.exists("key1") == 0


def test_exs04_exists_past_tombstone(table, fix_hash):
    col(table, fix_hash, 3)
    table.delete("key2")
    assert table.exists("key3") == 1


# ---------------------------------------------------------------------------
# DBSIZE
# ---------------------------------------------------------------------------

def test_dbs01_dbsize_counts_occupied(table):
    fill(table, 3)
    table.delete("key1")
    assert table.size == 2
    assert table.tombstones == 1


# ---------------------------------------------------------------------------
# 해시 함수 (mock 없이 실제 함수)
# ---------------------------------------------------------------------------

def test_hsh04_same_key_same_hash():
    assert fnv1a_64("key1") == fnv1a_64("key1")


def test_hsh05_matches_fnv1a_64_reference_values():
    assert fnv1a_64("") == 0xcbf29ce484222325
    assert fnv1a_64("a") == 0xaf63dc4c8601ec8c


@pytest.mark.parametrize("key", ["key1", "key2", "a", "", "가", "가나다", "x" * 99])
def test_hsh06_index_in_range(key):
    assert 0 <= fnv1a_64(key) % 8 < 8


# ---------------------------------------------------------------------------
# Phase 3 공통 함수. 케이스 ID는 docs/test-cases/phase3/test-cases.md를 따라요.
# REG-01(SET을 공통 함수로 바꿔도 Phase 1과 같게 동작)은 위의 Phase 1 테스트 전체가 확인해요.
# ---------------------------------------------------------------------------

def info(table):
    return {"size": table.size, "capacity": table.capacity, "tombstones": table.tombstones}


def test_ens01_no_resize_at_or_below_load_factor(table):
    table._ensure_capacity(6)                   # 6 / 8 = 0.75
    assert table.capacity == 8


def test_ens02_resize_over_load_factor(table):
    table._ensure_capacity(7)                   # 7 / 8 > 0.75
    assert table.capacity == 16


def test_ens03_counts_tombstones_and_resize_drops_them(table):
    fill(table, 6)
    table.delete("key1")
    table._ensure_capacity(1)                   # (5 + 1 + 1) / 8 > 0.75
    assert info(table) == {"size": 5, "capacity": 16, "tombstones": 0}


def test_ens04_doubles_until_enough(table):
    table._ensure_capacity(20)                  # 20 / 16 > 0.75, 20 / 32 <= 0.75
    assert table.capacity == 32


def test_ens05_over_max_capacity_raises_without_change(table):
    fill(table, 3)
    with pytest.raises(StoreFullError):
        table._ensure_capacity(MAX_CAPACITY)
    assert info(table) == {"size": 3, "capacity": 8, "tombstones": 0}


def test_wrt01_write_to_empty_bucket(table, fix_hash):
    fix_hash["key1"] = 1
    table._write(None, 1, "key1", "val1")
    assert table.get("key1") == "val1"
    assert table.buckets[1].key == "key1"
    assert info(table) == {"size": 1, "capacity": 8, "tombstones": 0}   # _write는 확장하지 않아요


def test_wrt02_overwrite_occupied_bucket(table, fix_hash):
    fix_hash["key1"] = 1
    table.set("key1", "val1")
    table._write(1, 1, "key1", "val2")
    assert table.get("key1") == "val2"
    assert table.size == 1
    assert table.tombstones == 0


def test_wrt03_write_to_tombstone_bucket(table, fix_hash):
    col(table, fix_hash, 2)                     # key1 → 1번, key2 → 2번
    table.delete("key1")
    table._write(None, 1, "key1", "val1")
    assert table.get("key1") == "val1"
    assert table.size == 2
    assert table.tombstones == 0

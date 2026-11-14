"""key-value를 저장하는 해시 테이블. 응답 형식은 모르고, 문제가 생기면 예외를 던져요.

설계: docs/design/phase1/hash-table.md, docs/design/phase3/atomic-commands.md
"""

import re
from enum import Enum

INITIAL_CAPACITY = 8          # R-06
LOAD_FACTOR_LIMIT = 0.75      # R-07
MAX_CAPACITY = 1 << 20        # 약 100만 버킷
MAX_KEY_LEN = 99              # R-23

FNV_OFFSET = 14695981039346656037   # 0xcbf29ce484222325
FNV_PRIME = 1099511628211           # 0x100000001b3
MASK_64 = 0xFFFFFFFFFFFFFFFF

INT64_MIN = -(1 << 63)              # INCR·DECR 범위. 실제 Redis와 같아요.
INT64_MAX = (1 << 63) - 1
# int()는 " 1", "+1", "1_000"도 받아들이고, \d는 "٣" 같은 다른 숫자도 받아서 직접 정해요.
_INTEGER = re.compile(r"-?[0-9]+")


class StoreFullError(Exception):
    """적재율 0.75를 지키려면 MAX_CAPACITY보다 커져야 할 때 던져요."""


class NotIntegerError(Exception):
    """INCR·DECR 대상 value가 정수가 아닐 때 던져요."""


class IntegerOverflowError(Exception):
    """INCR·DECR 결과가 64비트 정수 범위를 넘을 때 던져요."""


class State(Enum):
    EMPTY = 0
    OCCUPIED = 1
    TOMBSTONE = 2


class Bucket:
    __slots__ = ("state", "key", "key_len", "value", "value_len")

    def __init__(self):
        self.state = State.EMPTY
        self.key = None
        self.key_len = 0
        self.value = None
        self.value_len = 0

    def fill(self, key, value):
        """새로 넣거나 덮어쓸 때 모든 필드를 한 번에 채워요."""
        self.state = State.OCCUPIED
        self.key = key
        self.key_len = len(key.encode("utf-8"))
        self.value = value
        self.value_len = len(value.encode("utf-8"))

    def mark_deleted(self):
        """TOMBSTONE으로 바꾸고 데이터를 비워요."""
        self.state = State.TOMBSTONE
        self.key = None
        self.key_len = 0
        self.value = None
        self.value_len = 0


def fnv1a_64(key):
    """FNV-1a 64bit 해시. Python 정수는 저절로 잘리지 않아서 곱할 때마다 64bit로 잘라요. (R-09)"""
    h = FNV_OFFSET
    for byte in key.encode("utf-8"):
        h ^= byte
        h = (h * FNV_PRIME) & MASK_64
    return h


class HashTable:
    def __init__(self, capacity=INITIAL_CAPACITY):
        self.capacity = capacity
        self.size = 0           # OCCUPIED 버킷 수 (R-19)
        self.tombstones = 0     # TOMBSTONE 버킷 수. 적재율에 포함해요
        self.buckets = [Bucket() for _ in range(capacity)]

    def _probe(self, key):
        """(found, insert_at)을 돌려줘요. found는 key가 저장된 위치, 없으면 None이에요. (R-08)"""
        i = fnv1a_64(key) % self.capacity
        first_tombstone = None

        for _ in range(self.capacity):
            b = self.buckets[i]
            if b.state == State.EMPTY:
                insert_at = first_tombstone if first_tombstone is not None else i
                return None, insert_at
            if b.state == State.TOMBSTONE:
                if first_tombstone is None:
                    first_tombstone = i
            elif b.key == key:
                return i, i
            i = (i + 1) % self.capacity

        return None, first_tombstone

    def _resize(self, new_capacity):
        """OCCUPIED만 새 배열로 옮기고 TOMBSTONE은 버려요. (R-22)"""
        old_buckets = self.buckets

        self.capacity = new_capacity
        self.buckets = [Bucket() for _ in range(new_capacity)]
        self.size = 0
        self.tombstones = 0

        for b in old_buckets:
            if b.state == State.OCCUPIED:
                _, insert_at = self._probe(b.key)
                self.buckets[insert_at].fill(b.key, b.value)
                self.size += 1

    def _ensure_capacity(self, extra):
        """key를 extra개 새로 넣어도 적재율이 0.75 이하가 되게 확장해요. (R-07)
        넘으면 아무것도 바꾸지 않고 StoreFullError를 던져요."""
        if (self.size + self.tombstones + extra) / self.capacity <= LOAD_FACTOR_LIMIT:
            return
        # 확장하면 TOMBSTONE이 사라져요. MSET은 한 번에 여러 개라 2배로 부족할 수 있어요.
        new_capacity = self.capacity * 2
        while (self.size + extra) / new_capacity > LOAD_FACTOR_LIMIT:
            new_capacity *= 2
        if new_capacity > MAX_CAPACITY:
            raise StoreFullError
        self._resize(new_capacity)

    def _write(self, found, insert_at, key, value):
        """_probe 결과 자리에 쓰고 size, tombstones를 맞춰요. 확장은 하지 않아요."""
        if found is not None:
            self.buckets[found].fill(key, value)   # 덮어쓰기: 개수 변화 없음 (R-14)
            return
        bucket = self.buckets[insert_at]
        if bucket.state == State.TOMBSTONE:
            self.tombstones -= 1
        bucket.fill(key, value)                    # R-13
        self.size += 1

    def set(self, key, value):
        # 덮어쓰기도 +1로 확인하므로 경계에서는 확장이 한 번 더 일어날 수 있어요. (R-07)
        self._ensure_capacity(1)
        # 확장 뒤에는 홈 버킷이 바뀌므로 반드시 확장 다음에 탐사해요.
        found, insert_at = self._probe(key)
        self._write(found, insert_at, key, value)

    def getset(self, key, value):
        """저장하고 저장 전 value를 돌려줘요. 없었으면 None이에요. (R-39)"""
        self._ensure_capacity(1)
        found, insert_at = self._probe(key)
        old = self.buckets[found].value if found is not None else None
        self._write(found, insert_at, key, value)
        return old

    def setnx(self, key, value):
        """key가 없을 때만 저장해요. 저장했으면 1, 아니면 0이에요. (R-44)"""
        found, _ = self._probe(key)
        if found is not None:
            return 0                               # 실패하면 확장도 하지 않아요
        self._ensure_capacity(1)
        _, insert_at = self._probe(key)            # 확장됐을 수 있어서 다시 탐사해요
        self._write(None, insert_at, key, value)
        return 1

    def setxx(self, key, value):
        """key가 있을 때만 덮어써요. 덮어썼으면 1, 아니면 0이에요. (R-45)
        개수가 늘지 않아서 확장하지 않아요."""
        found, _ = self._probe(key)
        if found is None:
            return 0
        self.buckets[found].fill(key, value)
        return 1

    def incr_by(self, key, delta):
        """저장된 정수에 delta를 더해 저장하고 결과를 정수로 돌려줘요. 없는 key는 0으로 봐요. (R-46 ~ R-48)"""
        found, _ = self._probe(key)
        if found is None:
            current = 0
        else:
            value = self.buckets[found].value
            if not _INTEGER.fullmatch(value):
                raise NotIntegerError
            current = int(value)
            if not INT64_MIN <= current <= INT64_MAX:
                raise NotIntegerError

        new = current + delta
        if not INT64_MIN <= new <= INT64_MAX:
            raise IntegerOverflowError             # 아직 아무것도 바꾸지 않았어요

        if found is not None:
            self.buckets[found].fill(key, str(new))
        else:
            self._ensure_capacity(1)
            _, insert_at = self._probe(key)
            self._write(None, insert_at, key, str(new))
        return new

    def mset(self, pairs):
        """(key, value) 목록을 전부 저장해요. (R-42)
        실패할 수 있는 확장 검사를 첫 저장 전에 끝내서, 전부 저장하거나 하나도 저장하지 않아요."""
        self._ensure_capacity(len(pairs))
        for key, value in pairs:
            found, insert_at = self._probe(key)
            self._write(found, insert_at, key, value)

    def mget(self, keys):
        """key 순서대로 value 목록을 돌려줘요. 없는 key는 None이에요. (R-43)"""
        return [self.get(key) for key in keys]

    def get(self, key):
        """value를 돌려줘요. 없으면 None이에요. (R-15, R-16)"""
        found, _ = self._probe(key)
        if found is None:
            return None
        return self.buckets[found].value

    def delete(self, key):
        """지운 개수(1 또는 0)를 돌려줘요. (R-17)"""
        found, _ = self._probe(key)
        if found is None:
            return 0
        self.buckets[found].mark_deleted()
        self.size -= 1
        self.tombstones += 1
        return 1

    def flush(self):
        """모든 데이터를 지우고 초기 상태(버킷 8개)로 되돌려요. 지운 개수를 돌려줘요."""
        removed = self.size
        self.__init__()
        return removed

    def exists(self, key):
        """있으면 1, 없으면 0이에요. (R-18)"""
        found, _ = self._probe(key)
        return 0 if found is None else 1

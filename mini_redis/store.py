"""key-value를 저장하는 해시 테이블. 응답 형식은 모르고, 문제가 생기면 예외를 던져요.

설계: docs/design/phase1/hash-table.md
"""

from enum import Enum

INITIAL_CAPACITY = 8          # R-06
LOAD_FACTOR_LIMIT = 0.75      # R-07
MAX_CAPACITY = 1 << 20        # 약 100만 버킷
MAX_KEY_LEN = 99              # R-23

FNV_OFFSET = 14695981039346656037   # 0xcbf29ce484222325
FNV_PRIME = 1099511628211           # 0x100000001b3
MASK_64 = 0xFFFFFFFFFFFFFFFF


class StoreFullError(Exception):
    """버킷이 MAX_CAPACITY인데 SET이 적재율 0.75를 넘길 때 던져요."""


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

    def set(self, key, value):
        # 넣기 전에 +1로 확인해요. 덮어쓰기도 확인하므로 경계에서는 확장이 한 번 더 일어날 수 있어요. (R-07)
        if (self.size + self.tombstones + 1) / self.capacity > LOAD_FACTOR_LIMIT:
            if self.capacity >= MAX_CAPACITY:
                raise StoreFullError
            self._resize(self.capacity * 2)

        # 확장 뒤에는 홈 버킷이 바뀌므로 반드시 확장 다음에 탐사해요.
        found, insert_at = self._probe(key)
        if found is not None:
            self.buckets[found].fill(key, value)   # R-14
            return

        bucket = self.buckets[insert_at]
        if bucket.state == State.TOMBSTONE:
            self.tombstones -= 1
        bucket.fill(key, value)                    # R-13
        self.size += 1

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

    def exists(self, key):
        """있으면 1, 없으면 0이에요. (R-18)"""
        found, _ = self._probe(key)
        return 0 if found is None else 1

"""key-value를 저장하는 해시 테이블. 응답 형식은 모르고, 문제가 생기면 예외를 던져요.

설계: docs/design/phase1/hash-table.md, docs/design/phase3/atomic-commands.md,
      docs/design/phase4/expiration.md
"""

import math
import re
import time
from enum import Enum

INITIAL_CAPACITY = 8          # R-06
LOAD_FACTOR_LIMIT = 0.75      # R-07
REBUILD_LIMIT = 0.5           # 정리 후 적재율이 이 이하면 같은 크기로 청소해요 (R-67)
MAX_CAPACITY = 1 << 20        # 약 100만 버킷
MAX_KEY_LEN = 99              # R-23
MAX_TTL = 20 * 24 * 60 * 60   # 1,728,000초 (20일) (R-52)

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
    __slots__ = ("state", "key", "key_len", "value", "value_len", "expire_at")

    def __init__(self):
        self.state = State.EMPTY
        self.key = None
        self.key_len = 0
        self.value = None
        self.value_len = 0
        self.expire_at = None   # 만료 시각(clock 기준 초). None이면 만료 없음 (R-56, R-57)

    def fill(self, key, value):
        """key와 value만 채워요. expire_at은 건드리지 않아요. TTL을 바꿀 명령어는 set_ttl을 직접 불러요."""
        self.state = State.OCCUPIED
        self.key = key
        self.key_len = len(key.encode("utf-8"))
        self.value = value
        self.value_len = len(value.encode("utf-8"))

    def set_ttl(self, now, ttl):
        """ttl초 뒤를 만료 시각으로 저장해요. ttl이 None이면 만료를 지워요. (R-53, R-55)"""
        self.expire_at = None if ttl is None else now + ttl

    def is_expired(self, now):
        """now >= expire_at이면 만료예요. (R-59)"""
        return self.expire_at is not None and now >= self.expire_at

    def mark_deleted(self):
        """TOMBSTONE으로 바꾸고 데이터와 만료 시각을 비워요. 이 자리에 새로 쓴 key에 TTL이 따라오지 않아요."""
        self.state = State.TOMBSTONE
        self.key = None
        self.key_len = 0
        self.value = None
        self.value_len = 0
        self.expire_at = None


def fnv1a_64(key):
    """FNV-1a 64bit 해시. Python 정수는 저절로 잘리지 않아서 곱할 때마다 64bit로 잘라요. (R-09)"""
    h = FNV_OFFSET
    for byte in key.encode("utf-8"):
        h ^= byte
        h = (h * FNV_PRIME) & MASK_64
    return h


class HashTable:
    def __init__(self, capacity=INITIAL_CAPACITY, clock=time.monotonic):
        self.capacity = capacity
        self.clock = clock      # 현재 시각(초)을 돌려주는 함수. 테스트는 가짜 시계를 넣어요
        self.size = 0           # OCCUPIED 버킷 수. 아직 정리 안 된 만료 key도 포함해요 (R-19, R-70)
        self.tombstones = 0     # TOMBSTONE 버킷 수. 적재율에 포함해요
        self.buckets = [Bucket() for _ in range(capacity)]

    def _remove(self, bucket):
        """OCCUPIED 버킷을 TOMBSTONE으로 바꾸고 개수를 맞춰요. DEL과 지연 만료가 같이 써요."""
        bucket.mark_deleted()
        self.size -= 1
        self.tombstones += 1

    def _probe(self, key, now=None):
        """(found, insert_at)을 돌려줘요. found는 key가 저장된 위치, 없으면 None이에요. (R-08)
        지나가며 만난 만료 key는 TOMBSTONE으로 바꿔요. EMPTY로 바꾸면 뒤쪽 key의 탐사가 끊겨요. (R-58, R-60)"""
        if now is None:
            now = self.clock()
        i = fnv1a_64(key) % self.capacity
        first_tombstone = None

        for _ in range(self.capacity):
            b = self.buckets[i]
            if b.state == State.EMPTY:
                insert_at = first_tombstone if first_tombstone is not None else i
                return None, insert_at
            if b.state == State.OCCUPIED and b.is_expired(now):
                self._remove(b)                    # 아래 TOMBSTONE 분기로 이어져요
            if b.state == State.TOMBSTONE:
                if first_tombstone is None:
                    first_tombstone = i
            elif b.key == key:
                return i, i
            i = (i + 1) % self.capacity

        return None, first_tombstone

    def _resize(self, new_capacity, now=None):
        """만료되지 않은 OCCUPIED만 새 배열로 옮기고 TOMBSTONE과 만료 key는 버려요. (R-22, R-66)
        new_capacity가 지금과 같으면 같은 크기로 청소해요."""
        if now is None:
            now = self.clock()
        old_buckets = self.buckets

        self.capacity = new_capacity
        self.buckets = [Bucket() for _ in range(new_capacity)]
        self.size = 0
        self.tombstones = 0

        for b in old_buckets:
            if b.state == State.OCCUPIED and not b.is_expired(now):
                _, insert_at = self._probe(b.key, now)
                new_bucket = self.buckets[insert_at]
                new_bucket.fill(b.key, b.value)
                new_bucket.expire_at = b.expire_at  # 남은 시간이 아니라 만료 시각을 그대로 옮겨요 (R-69)
                self.size += 1

    def _count_live(self, now):
        """만료되지 않은 OCCUPIED 버킷 수예요. 확장이 필요할 때만 세서 O(n)이 자주 일어나지 않아요."""
        return sum(1 for b in self.buckets if b.state == State.OCCUPIED and not b.is_expired(now))

    def _ensure_capacity(self, extra, now=None):
        """key를 extra개 새로 넣어도 적재율이 0.75 이하가 되게 정리하거나 확장해요. (R-07, R-66 ~ R-68)
        정리해도 넣을 수 없으면 아무것도 바꾸지 않고 StoreFullError를 던져요."""
        if (self.size + self.tombstones + extra) / self.capacity <= LOAD_FACTOR_LIMIT:
            return
        if now is None:
            now = self.clock()
        # 정리하면 TOMBSTONE과 만료 key가 사라져요. 남는 건 live개예요.
        live = self._count_live(now)
        if (live + extra) / self.capacity <= REBUILD_LIMIT:
            new_capacity = self.capacity                   # 같은 크기로 청소 (R-67)
        else:
            # MSET은 한 번에 여러 개라 2배로 부족할 수 있어요. (R-68)
            new_capacity = self.capacity * 2
            while (live + extra) / new_capacity > LOAD_FACTOR_LIMIT:
                new_capacity *= 2
            if new_capacity > MAX_CAPACITY:
                if (live + extra) / self.capacity > LOAD_FACTOR_LIMIT:
                    raise StoreFullError
                new_capacity = self.capacity               # 키울 수 없으면 청소만 해요
        self._resize(new_capacity, now)

    def _write(self, found, insert_at, key, value):
        """_probe 결과 자리에 쓰고 size, tombstones를 맞춰요. 쓴 버킷의 인덱스를 돌려줘요.
        확장도, TTL 변경도 하지 않아요."""
        if found is not None:
            self.buckets[found].fill(key, value)   # 덮어쓰기: 개수 변화 없음 (R-14)
            return found
        bucket = self.buckets[insert_at]
        if bucket.state == State.TOMBSTONE:
            self.tombstones -= 1
        bucket.fill(key, value)                    # R-13
        self.size += 1
        return insert_at

    # 명령어마다 now를 한 번만 구해서, 한 명령어 안에서 만료 판정 기준이 같아요.

    def set(self, key, value, ttl=None):
        """ttl초 뒤 만료되게 저장해요. ttl이 None이면 기존 TTL을 지워요. (R-51, R-55, R-62)"""
        now = self.clock()
        # 덮어쓰기도 +1로 확인하므로 경계에서는 확장이 한 번 더 일어날 수 있어요. (R-07)
        self._ensure_capacity(1, now)
        # 확장 뒤에는 홈 버킷이 바뀌므로 반드시 확장 다음에 탐사해요.
        found, insert_at = self._probe(key, now)
        i = self._write(found, insert_at, key, value)
        self.buckets[i].set_ttl(now, ttl)

    def getset(self, key, value):
        """저장하고 저장 전 value를 돌려줘요. 없었으면 None이에요. TTL은 지워요. (R-39, R-63)"""
        now = self.clock()
        self._ensure_capacity(1, now)
        found, insert_at = self._probe(key, now)
        old = self.buckets[found].value if found is not None else None
        i = self._write(found, insert_at, key, value)
        self.buckets[i].set_ttl(now, None)
        return old

    def setnx(self, key, value):
        """key가 없을 때만 저장해요. 저장했으면 1, 아니면 0이에요. (R-44)
        새 key라 expire_at이 이미 None이어서 set_ttl을 부르지 않아요. (R-57)"""
        now = self.clock()
        found, _ = self._probe(key, now)
        if found is not None:
            return 0                               # 실패하면 확장도 하지 않아요
        self._ensure_capacity(1, now)
        _, insert_at = self._probe(key, now)       # 확장됐을 수 있어서 다시 탐사해요
        self._write(None, insert_at, key, value)
        return 1

    def setxx(self, key, value):
        """key가 있을 때만 덮어써요. 덮어썼으면 1, 아니면 0이에요. TTL은 지워요. (R-45, R-63)
        개수가 늘지 않아서 확장하지 않아요."""
        now = self.clock()
        found, _ = self._probe(key, now)
        if found is None:
            return 0
        self.buckets[found].fill(key, value)
        self.buckets[found].set_ttl(now, None)
        return 1

    def incr_by(self, key, delta):
        """저장된 정수에 delta를 더해 저장하고 결과를 정수로 돌려줘요. 없는 key는 0으로 봐요. (R-46 ~ R-48)
        fill만 써서 TTL은 그대로예요. (R-64)"""
        now = self.clock()
        found, _ = self._probe(key, now)
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
            self._ensure_capacity(1, now)
            _, insert_at = self._probe(key, now)
            self._write(None, insert_at, key, str(new))
        return new

    def mset(self, pairs):
        """(key, value) 목록을 전부 저장해요. (R-42)
        실패할 수 있는 확장 검사를 첫 저장 전에 끝내서, 전부 저장하거나 하나도 저장하지 않아요.
        key마다 TTL을 지워요. (R-63)"""
        now = self.clock()
        self._ensure_capacity(len(pairs), now)
        for key, value in pairs:
            found, insert_at = self._probe(key, now)
            i = self._write(found, insert_at, key, value)
            self.buckets[i].set_ttl(now, None)

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
        self._remove(self.buckets[found])
        return 1

    def flush(self):
        """모든 데이터를 지우고 초기 상태(버킷 8개)로 되돌려요. 지운 개수를 돌려줘요."""
        removed = self.size
        self.__init__(clock=self.clock)            # 시계를 넘겨야 테스트의 가짜 시계가 유지돼요
        return removed

    def exists(self, key):
        """있으면 1, 없으면 0이에요. (R-18)"""
        found, _ = self._probe(key)
        return 0 if found is None else 1

    def ttl(self, key):
        """남은 만료 시간(초)을 올림해서 돌려줘요. 만료 없음 -1, 없거나 만료된 key -2예요. (R-65)
        올림이라 살아 있는 key는 0으로 보이지 않아요."""
        now = self.clock()
        found, _ = self._probe(key, now)
        if found is None:
            return -2
        expire_at = self.buckets[found].expire_at
        if expire_at is None:
            return -1
        return math.ceil(expire_at - now)

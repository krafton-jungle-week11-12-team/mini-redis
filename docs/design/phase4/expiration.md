# 만료 설계

이 문서를 읽으면 Phase 4에서 key에 보관 기간(TTL)을 붙이고, 만료된 key를 언제 어떻게 지우는지 알 수 있어요. 버킷 필드, `_probe` 변경, 확장·청소 규칙, 명령어별 TTL 처리, dispatcher 변경을 그대로 따라 `mini_redis/store.py`와 `mini_redis/dispatcher.py`를 구현할 수 있어요.

Phase 4 요구사항 명세서는 아직 작성 중이에요([#21](https://github.com/krafton-jungle-week11-12-team/mini-redis/issues/21)). 요구사항 ID가 정해지면 각 절에 붙여요. 해시 테이블 구조는 [해시 테이블 설계](../phase1/hash-table.md)를, 공통 함수(`_ensure_capacity`, `_write`)는 [원자적 명령어 설계](../phase3/atomic-commands.md)를 바탕으로 바꿔요.

## 다루는 범위

| 분류 | 내용 | 이 문서 |
| --- | --- | --- |
| TTL 저장 | `SET key value ttl`, 버킷의 `expire_at` | ✅ |
| 지연 만료 | 탐사 중 만난 만료 key를 `TOMBSTONE`으로 바꿈 | ✅ |
| 확장 전 정리 | 확장 전에 만료 key를 지우고, 필요하면 같은 크기로 청소 | ✅ |
| 명령어별 TTL | 값을 바꾸는 명령어가 TTL을 유지할지 지울지 | ✅ |
| TTL 조회·변경 명령어 | `TTL`, `EXPIRE`, `PERSIST` | 요구사항이 정해지면 다뤄요 |
| 능동 만료 | 접근하지 않아도 주기적으로 지우기 | 다루지 않아요 |

## 결정 사항

| 항목 | 선택 | 이유 |
| --- | --- | --- |
| TTL 지정 방법 | `SET key value ttl` (세 번째 인자) | 실제 Redis의 `SET key value EX 30`보다 옵션 해석이 필요 없어요. |
| TTL 단위·범위 | 초 단위 정수, 1 ~ 1,728,000 (20일) | 0초는 "넣자마자 삭제"라 의미가 없어요. 상한이 없으면 아주 큰 수에서 시각 계산이 의미를 잃어요. |
| TTL 형식 | `[1-9][0-9]{0,6}` 전체 일치 | `int()`는 `" 1"`, `"+1"`, `"1_000"`도 받아들여요. 앞자리 0(`"007"`)도 실제 Redis처럼 거부해요. 7자리 제한으로 아주 긴 숫자를 `int()`로 바꾸지 않아요. |
| 시계 | `time.monotonic`, `HashTable(clock=...)`으로 주입 | 시스템 시간을 바꿔도 만료가 흔들리지 않아요. 테스트는 가짜 시계로 시간을 건너뛰어요. |
| 시각 계산 | 명령어 하나에서 `now`를 한 번만 구해요 | 한 명령어 안에서 만료 판정 기준이 일정해요. |
| 만료 판정 | `now >= expire_at` | TTL 10초면 정확히 10초 뒤부터 없는 key예요. |
| 만료 key 정리 위치 | `_probe` 안에서 `TOMBSTONE`으로 바꿔요 | `_probe`를 쓰는 모든 명령어가 고치지 않아도 만료 key를 없는 key로 봐요. |
| TTL 유지 | INCR·DECR만 유지, 나머지 덮어쓰기는 지움 | 실제 Redis와 같아요. |
| `size`·DBSIZE | 근사값 | 아무도 접근하지 않은 만료 key는 다음 탐사·청소 전까지 `size`에 남아요. 실제 Redis의 DBSIZE도 같아요. |
| 확장 기준 | 기존과 같이 `(size + tombstones + extra) / capacity > 0.75` 하나 | 별도 TOMBSTONE 비율 조건을 두지 않아요. GET이 rehash를 일으키지 않아요. |
| 크기 결정 | 만료를 뺀 실제 key 수로 2배 확장 또는 같은 크기 청소 | TOMBSTONE과 만료 key 때문에 테이블이 끝없이 커지는 문제를 막아요. |

## 자료구조

### Bucket

`expire_at` 필드를 추가하고, TTL을 다루는 메서드 두 개를 추가해요.

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `expire_at` | `float` 또는 `None` | 만료 시각이에요. `clock()`과 같은 기준의 초 단위 값이에요. `None`이면 만료가 없어요. (예: `now`가 `1000.0`일 때 TTL 30초 → `1030.0`) |

```python
class Bucket:
    __slots__ = ("state", "key", "key_len", "value", "value_len", "expire_at")

    def __init__(self):
        self.state = State.EMPTY
        self.key = None
        self.key_len = 0
        self.value = None
        self.value_len = 0
        self.expire_at = None

    def fill(self, key, value):
        """key와 value만 채워요. expire_at은 건드리지 않아요."""
        self.state = State.OCCUPIED
        self.key = key
        self.key_len = len(key.encode("utf-8"))
        self.value = value
        self.value_len = len(value.encode("utf-8"))

    def set_ttl(self, now, ttl):
        """ttl초 뒤를 만료 시각으로 저장해요. ttl이 None이면 만료를 지워요."""
        self.expire_at = None if ttl is None else now + ttl

    def is_expired(self, now):
        return self.expire_at is not None and now >= self.expire_at

    def mark_deleted(self):
        """TOMBSTONE으로 바꾸고 데이터와 만료 시각을 모두 비워요."""
        self.state = State.TOMBSTONE
        self.key = None
        self.key_len = 0
        self.value = None
        self.value_len = 0
        self.expire_at = None
```

- **`fill`은 TTL을 건드리지 않아요.** 값만 바꾸는 INCR이 TTL을 날리는 일이 구조적으로 생기지 않아요. TTL을 바꿔야 하는 명령어는 `set_ttl`을 직접 불러요.
- **`set_ttl`은 `now`를 인자로 받아요.** Bucket이 `time.monotonic()`을 직접 부르면 테스트에서 가짜 시계를 쓸 수 없어요.
- **`OCCUPIED`가 아닌 버킷의 `expire_at`은 항상 `None`이에요.** 새 버킷은 `None`으로 시작하고, `mark_deleted`가 `None`으로 되돌려요. 그래서 빈 자리에 새 key를 `fill`하면 이전 key의 TTL이 따라오지 않아요.

### HashTable

시계를 주입받아요. 상수 두 개를 추가해요.

```python
import time

REBUILD_LIMIT = 0.5             # 정리 후 적재율이 이 이하면 같은 크기로 청소해요
MAX_TTL = 20 * 24 * 60 * 60     # 1,728,000초 (20일)


class HashTable:
    def __init__(self, capacity=INITIAL_CAPACITY, clock=time.monotonic):
        self.capacity = capacity
        self.clock = clock      # 현재 시각(초)을 돌려주는 함수
        self.size = 0           # OCCUPIED 버킷 수. 만료 key도 포함하는 근사값이에요
        self.tombstones = 0
        self.buckets = [Bucket() for _ in range(capacity)]
```

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `clock` | 인자 없는 함수 | 현재 시각을 초 단위 `float`로 돌려줘요. 기본값은 `time.monotonic`이에요. 테스트는 원하는 값을 돌려주는 함수를 넣어요. (예: `HashTable(clock=lambda: 1000.0)`) |

`flush`는 `self.__init__()`을 다시 부르므로 시계를 넘겨줘야 해요. 안 넘기면 테스트의 가짜 시계가 FLUSH 뒤에 사라져요.

```python
def flush(self):
    removed = self.size
    self.__init__(clock=self.clock)
    return removed
```

## 지연 만료: _probe

탐사 중에 만료된 `OCCUPIED` 버킷을 만나면 그 자리에서 `TOMBSTONE`으로 바꿔요. 찾던 key인지와 상관없이 지나가는 길의 만료 key를 모두 바꿔요.

1. `now`가 없으면 `clock()`으로 구해요. 해시 함수로 홈 버킷을 구하고, 처음 만난 `TOMBSTONE` 위치는 없다고 두고 시작해요.
2. 버킷을 차례로 보면서:
   - `EMPTY`이면 → key가 없어요. `(None, 넣을 위치)`를 반환해요. (Phase 1과 같아요)
   - `OCCUPIED`인데 만료됐으면 → `_remove`로 `TOMBSTONE`으로 바꾸고, 아래 `TOMBSTONE` 규칙으로 넘어가요.
   - `TOMBSTONE`이면 → 처음 만난 것이면 위치를 기억해요. 다음 칸으로 가요.
   - 살아 있는 `OCCUPIED`이고 key가 같으면 → `(i, i)`를 반환해요.
3. 한 바퀴를 돌면 `(None, 기억해 둔 TOMBSTONE 위치)`를 반환해요.

```python
def _remove(self, bucket):
    """OCCUPIED 버킷을 TOMBSTONE으로 바꾸고 개수를 맞춰요. DEL과 만료가 같이 써요."""
    bucket.mark_deleted()
    self.size -= 1
    self.tombstones += 1


def _probe(self, key, now=None):
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
            self._remove(b)                 # 아래 TOMBSTONE 분기로 이어져요
        if b.state == State.TOMBSTONE:
            if first_tombstone is None:
                first_tombstone = i
        elif b.key == key:
            return i, i
        i = (i + 1) % self.capacity

    return None, first_tombstone
```

```
TTL 10초로 SET (now = 0)

[2] A(만료 10)   [3] B   [4] EMPTY      GET A, now = 10
 ↓ _probe가 [2]를 TOMBSTONE으로 바꿔요
[2] TOMBSTONE    [3] B   [4] EMPTY      → GET A는 nil, size 1, tombstones 1
```

- **`EMPTY`가 아니라 `TOMBSTONE`으로 바꿔요.** `EMPTY`로 바꾸면 그 뒤에 있는 B를 찾지 못해요. ([TOMBSTONE을 쓰는 이유](../phase1/hash-table.md#tombstone을-쓰는-이유))
- **만료 자리도 새 key가 들어갈 자리가 돼요.** `TOMBSTONE`으로 바꾼 뒤 `first_tombstone`으로 기억하므로 `insert_at`에 자연스럽게 들어가요. 반환값은 Phase 1과 같은 `(found, insert_at)`이에요.
- **적재율은 그대로예요.** `size -= 1`, `tombstones += 1`이라 `size + tombstones`가 변하지 않아요. DEL과 같아요. 그래서 GET을 많이 해도 확장이 앞당겨지지 않아요.
- **GET도 상태를 바꿔요.** 서버가 단일 스레드라 문제없어요. ([원자성을 지키는 방법](../phase3/atomic-commands.md#원자성을-지키는-방법-r-41))
- **탐사 경로가 짧아지지는 않아요.** `TOMBSTONE`도 지나가야 해요. 경로는 아래 확장·청소 때 짧아져요.

### 만료 key는 모든 명령어에서 없는 key예요

모든 명령어가 `_probe`를 거치므로, 만료 key는 `found`가 `None`으로 나와요. 명령어 코드를 따로 고치지 않아도 아래처럼 동작해요.

| 명령어 | 만료된 key일 때 | 없는 key일 때와 같나요? |
| --- | --- | --- |
| GET | nil | ✅ |
| EXISTS | `0` | ✅ |
| DEL | `0` (지운 게 아니라 원래 없는 key예요) | ✅ |
| GETSET | nil을 돌려주고 새 값을 TTL 없이 저장 | ✅ |
| SETNX | `1` (저장 성공) | ✅ |
| SETXX | `0` (저장 안 함) | ✅ |
| INCR·DECR | `0`에서 시작, TTL 없음 | ✅ |
| MGET | 해당 위치 nil | ✅ |

```
> SET session abc 10
> GET session          → "abc"
(10초 뒤)
> GET session          → nil
> EXISTS session       → (integer) 0
> SETNX session xyz    → (integer) 1
```

## 확장 전 정리: _ensure_capacity

### 지금 구조의 문제

Phase 1·3의 `_ensure_capacity`는 `TOMBSTONE`이 많아서 기준을 넘어도 항상 2배로 키워요. 살아 있는 key가 거의 없어도 SET과 DEL(또는 만료)이 반복되면 테이블이 계속 커지다가 `STORE_FULL`이 나요.

```
SET k / DEL k 를 2,000번 반복        → live 0, capacity 1024 (처음 8의 128배)
MAX_CAPACITY 4096에서 계속 반복       → 11,592번째에 STORE_FULL, live 0
```

TTL이 들어오면 만료 key도 `TOMBSTONE`이 되므로 이 상황이 훨씬 자주 생겨요. 아무도 다시 조회하지 않는 만료 key는 `_probe`로도 지워지지 않아서 `size`를 부풀려요.

### 새 규칙

확장 **여부**는 기존과 같은 조건 하나로 정하고, 확장 **크기**를 만료를 뺀 실제 key 수(`live`)로 정해요.

1. `(size + tombstones + extra) / capacity <= 0.75`이면 아무것도 하지 않고 끝내요. (기존과 같아요)
2. `live`를 세요. `OCCUPIED`이면서 만료되지 않은 버킷 수예요. 세기만 하고 아무것도 바꾸지 않아요.
3. `(live + extra) / capacity <= 0.5`이면 → **같은 크기로 청소**해요.
4. 아니면 → 기존처럼 `(live + extra) / 새 크기 <= 0.75`가 될 때까지 2배씩 늘려요.
5. 새 크기가 `MAX_CAPACITY`를 넘으면:
   - `(live + extra) / capacity <= 0.75`이면 → 키울 수는 없지만 청소하면 들어가요. 같은 크기로 청소해요.
   - 아니면 → `StoreFullError`를 던져요. 아직 아무것도 바꾸지 않았어요.
6. `_resize(새 크기, now)`를 불러요.

```python
def _count_live(self, now):
    return sum(1 for b in self.buckets
               if b.state == State.OCCUPIED and not b.is_expired(now))


def _ensure_capacity(self, extra, now=None):
    if (self.size + self.tombstones + extra) / self.capacity <= LOAD_FACTOR_LIMIT:
        return
    if now is None:
        now = self.clock()
    live = self._count_live(now)
    if (live + extra) / self.capacity <= REBUILD_LIMIT:
        new_capacity = self.capacity                     # 같은 크기로 청소
    else:
        new_capacity = self.capacity * 2
        while (live + extra) / new_capacity > LOAD_FACTOR_LIMIT:
            new_capacity *= 2
        if new_capacity > MAX_CAPACITY:
            if (live + extra) / self.capacity > LOAD_FACTOR_LIMIT:
                raise StoreFullError
            new_capacity = self.capacity                 # 키울 수 없으면 청소만
    self._resize(new_capacity, now)
```

| 상황 (버킷 8개, SET 1개) | `size + tombstones` | `live` | 결과 |
| --- | --- | --- | --- |
| key 6개, 만료 없음 | 6 | 6 | (6+1)/8 > 0.5 → 16으로 확장 |
| key 6개 중 3개 만료 | 6 | 3 | (3+1)/8 = 0.5 → 8 그대로 청소, 만료 key 3개 제거 |
| key 1개 + TOMBSTONE 5개 | 6 | 1 | (1+1)/8 ≤ 0.5 → 8 그대로 청소, TOMBSTONE 제거 |

- **같은 크기 기준이 0.5인 이유**: 청소 뒤 적재율이 0.5 이하라서, 다음 청소까지 최소 `capacity / 4`번은 새 key를 넣을 수 있어요. O(n) 청소가 연달아 일어나지 않아서 분할 상환하면 삽입당 O(1)이에요. 0.5 ~ 0.75 사이면 2배로 키워서 적재율을 0.375 이하로 낮춰요.
- **`MAX_CAPACITY`에서의 청소**: 0.5 ~ 0.75 사이에서는 청소 뒤에도 여유가 적어서 청소가 자주 일어날 수 있어요. 저장소가 거의 찬 상황이라 `STORE_FULL`보다 낫다고 보고 감수해요.
- **`live`를 세는 비용은 O(n)이에요.** 확장 기준을 넘었을 때만 세고, 어차피 뒤이은 `_resize`도 O(n)이에요.
- **`now`는 선택 인자예요.** 명령어는 자기가 구한 `now`를 넘기고, 기존 테스트처럼 `_ensure_capacity(7)`만 불러도 동작해요.

### _resize

`OCCUPIED`이면서 만료되지 않은 버킷만 옮겨요. `TOMBSTONE`과 만료 key는 버려요.

```python
def _resize(self, new_capacity, now):
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
            new_bucket.expire_at = b.expire_at      # 남은 시간이 아니라 만료 시각을 그대로 옮겨요
            self.size += 1
```

- **`expire_at`을 그대로 옮겨요.** `fill`은 TTL을 건드리지 않으므로 직접 복사해요. 빠뜨리면 확장할 때마다 모든 TTL이 사라져요.
- 청소가 끝나면 `size`가 실제 key 수와 같아지고 `tombstones`는 0이 돼요. `size`가 정확해지는 시점이에요.

## 명령어별 TTL 처리

### _write

쓴 버킷의 인덱스를 돌려주게 바꿔요. 호출하는 쪽에서 그 버킷에 `set_ttl`을 불러요. TTL은 건드리지 않아요.

```python
def _write(self, found, insert_at, key, value):
    if found is not None:
        self.buckets[found].fill(key, value)
        return found
    bucket = self.buckets[insert_at]
    if bucket.state == State.TOMBSTONE:
        self.tombstones -= 1
    bucket.fill(key, value)
    self.size += 1
    return insert_at
```

### 표

TTL을 지우는 명령어는 `set_ttl(now, None)`을 **직접** 불러요. "덮어쓰면 TTL이 지워진다"는 규칙이 `fill` 안에 숨지 않고 명령어 코드에 드러나서, 이 표와 코드를 한 줄씩 맞춰 볼 수 있어요.

| 명령어 | `fill` | `set_ttl` | TTL 결과 |
| --- | --- | --- | --- |
| `SET k v` | O | `set_ttl(now, None)` | 지워요 |
| `SET k v 30` | O | `set_ttl(now, 30)` | 30초 |
| GETSET | O | `set_ttl(now, None)` | 지워요 |
| SETXX (성공) | O | `set_ttl(now, None)` | 지워요 |
| MSET | O | key마다 `set_ttl(now, None)` | 지워요 |
| SETNX (성공) | O | 부르지 않아요 | 없음 (새 key라 `expire_at`이 이미 `None`) |
| INCR·DECR (기존 key) | O | **부르지 않아요** | **유지** |
| INCR·DECR (새 key) | O | 부르지 않아요 | 없음 |

```
> SET views 10 60
> INCR views           → (integer) 11      # TTL 60초 유지
> SET views 0          → "OK"              # TTL 지워짐
```

### 바뀌는 명령어

명령어마다 처음에 `now = self.clock()`을 한 번 구해서 `_ensure_capacity`, `_probe`에 넘겨요. 실행 순서는 [Phase 3](../phase3/atomic-commands.md#명령어별-실행-순서)와 같고, 표시한 줄만 바뀌어요.

```python
def set(self, key, value, ttl=None):
    now = self.clock()
    self._ensure_capacity(1, now)
    found, insert_at = self._probe(key, now)
    i = self._write(found, insert_at, key, value)
    self.buckets[i].set_ttl(now, ttl)                # 추가: None이면 TTL을 지워요


def getset(self, key, value):
    now = self.clock()
    self._ensure_capacity(1, now)
    found, insert_at = self._probe(key, now)
    old = self.buckets[found].value if found is not None else None
    i = self._write(found, insert_at, key, value)
    self.buckets[i].set_ttl(now, None)               # 추가
    return old


def setxx(self, key, value):
    now = self.clock()
    found, _ = self._probe(key, now)
    if found is None:
        return 0
    self.buckets[found].fill(key, value)
    self.buckets[found].set_ttl(now, None)           # 추가
    return 1


def mset(self, pairs):
    now = self.clock()
    self._ensure_capacity(len(pairs), now)
    for key, value in pairs:
        found, insert_at = self._probe(key, now)
        i = self._write(found, insert_at, key, value)
        self.buckets[i].set_ttl(now, None)           # 추가


def delete(self, key):
    found, _ = self._probe(key)
    if found is None:
        return 0
    self._remove(self.buckets[found])                # mark_deleted + 개수 조정을 함수로
    return 1
```

SETNX와 INCR·DECR은 `now`를 구해서 `_ensure_capacity`, `_probe`에 넘기는 것 말고는 바뀌지 않아요. GET, EXISTS, MGET은 바뀌지 않아요. `_probe`가 알아서 `now`를 구해요.

## size는 근사값이에요

`size`(DBSIZE, INFO)는 아직 정리되지 않은 만료 key를 포함해요.

```
> SET a 1 10
> SET b 2
(10초 뒤, a를 아무도 조회하지 않음)
> DBSIZE               → (integer) 2       # a가 아직 OCCUPIED로 남아 있어요
> GET a                → nil               # 이때 TOMBSTONE으로 바뀌어요
> DBSIZE               → (integer) 1
```

- 정확하게 세려면 DBSIZE마다 전체를 훑어야 해서 O(n)이 돼요. 실제 Redis의 DBSIZE도 지워지지 않은 만료 key를 포함해요.
- `size`가 정확해지는 시점은 만료 key가 `_probe`로 지워질 때와 `_resize`가 끝났을 때예요.
- 테스트에서 DBSIZE를 확인할 때는 이 점을 기대값에 반영해요.

## 오류 코드

[오류 코드](../phase1/hash-table.md#오류-코드)에 하나를 추가해요. 응답 형식은 같아요.

| 코드 | HTTP 상태 | 언제 | 검사 위치 |
| --- | --- | --- | --- |
| `INVALID_TTL` | 400 | SET의 세 번째 인자가 1 ~ 1,728,000 사이의 정수 형식이 아닐 때 | `dispatcher.py` |

| 입력 | 결과 |
| --- | --- |
| `"30"`, `"1"`, `"1728000"` | 저장 |
| `"0"`, `"-1"`, `"1728001"` | `INVALID_TTL` |
| `"007"`, `" 1"`, `"+1"`, `"1.5"`, `"abc"`, `"99999999999999"` | `INVALID_TTL` |
| `30` (JSON 숫자) | `WRONG_TYPE`. 인자는 모두 문자열이에요. (R-11, R-25) |

`STORE_FULL`은 이제 청소해도 자리가 없을 때만 나요. 만료 key와 `TOMBSTONE`만 많은 경우에는 나지 않아요.

## dispatcher 연결

### SET 인자 개수

SET의 인자 개수를 2에서 2 ~ 3으로 바꿔요. 세 번째 인자는 key가 아니므로 `keys`는 그대로 `FIRST`예요.

```python
"SET":    Command(cmd_set, 2, 3, FIRST),
```

### TTL 검사

Phase 1 설계에서 "숫자 인자를 받는 명령어가 생기면 그 명령어만 따로 검사한다"고 했던 부분이에요. ([dispatcher 연결](../phase1/hash-table.md#dispatcher-연결)) `execute`의 공통 검사(1 ~ 4번)를 통과한 뒤 `cmd_set`에서 검사해요. 검사가 저장보다 먼저라서, 실패하면 아무것도 저장하지 않아요.

```python
import re

from mini_redis.store import MAX_TTL

_TTL = re.compile(r"[1-9][0-9]{0,6}")       # 1 ~ 9999999, 앞자리 0 없음


class InvalidTtlError(Exception):
    """SET의 TTL 인자가 형식이나 범위에 맞지 않을 때 던져요."""


def parse_ttl(arg):
    if not _TTL.fullmatch(arg) or int(arg) > MAX_TTL:
        raise InvalidTtlError
    return int(arg)


def cmd_set(args):
    ttl = parse_ttl(args[2]) if len(args) == 3 else None
    store.set(args[0], args[1], ttl)
    return ok_response("OK")
```

`execute`의 예외 처리에 한 줄을 추가해요.

```python
    except InvalidTtlError:
        return 400, error_response("INVALID_TTL", f"TTL은 1 ~ {MAX_TTL} 사이의 정수예요")
```

`InvalidTtlError`는 입력값 검사라서 `store.py`가 아니라 `dispatcher.py`에 둬요. `MAX_TTL`은 `MAX_KEY_LEN`처럼 `store.py`에 두고 가져와요.

### 성공 응답

| 명령어 | 인자 개수 | 성공 응답 `result` |
| --- | --- | --- |
| `SET` | 2 ~ 3 | `"OK"` |

## 클라이언트 · CLI

[클라이언트 · CLI 설계](../phase2/client.md)의 `set`에 `ttl`을 추가해요.

| 메서드 | 보내는 명령어 | 반환값 |
| --- | --- | --- |
| `set(key, value, ttl=None)` | `SET key value` 또는 `SET key value ttl` | `"OK"` |

```python
def set(self, key, value, ttl=None):
    if ttl is None:
        return self.execute("SET", key, value)
    return self.execute("SET", key, value, str(ttl))     # 30 → "30"
```

CLI는 입력을 모두 문자열로 보내므로 바꾸지 않아요. `SET session abc 30`을 그대로 입력하면 돼요.

## 기존 테스트에 미치는 영향

이 문서의 코드를 `store.py`, `dispatcher.py`에 붙여 기존 테스트 141개를 돌리면 140개가 통과해요.

| 케이스 | 바뀌는 점 |
| --- | --- |
| VAL-02 (`SET key1 val1 val2`) | `WRONG_ARGS` → `INVALID_TTL`. 세 번째 인자를 TTL로 읽어요. 인자 개수 오류는 `SET key1 val1 30 x`(4개)로 바꿔서 확인해요. |
| EXP-04, ENS-03 (TOMBSTONE 포함 확장) | 그대로 통과해요. `live`가 5라서 (5+1)/8 > 0.5 → 16으로 확장돼요. |
| ENS-05, MST-08 (`STORE_FULL`) | 그대로 통과해요. 청소해도 0.75를 넘어서 예외가 나요. |

## 다음 설계로 넘기는 것

- **TTL·EXPIRE·PERSIST 명령어**: 요구사항(#21)에 들어가면 다뤄요. `remaining = expire_at - now`로 남은 시간을 구하고, 실제 Redis는 key 없음을 `-2`, 만료 없음을 `-1`로 응답해요. EXPIRE·PERSIST는 `_probe` 뒤 `set_ttl`만 부르면 돼요.
- **능동 만료**: 실제 Redis는 TTL이 있는 key 몇 개를 주기적으로 골라 지워요. 이 설계는 단일 스레드 HTTP 서버라 주기 작업이 없어서, 그 역할을 확장 전 정리가 대신해요.
- **영속성 (Phase 6)**: `time.monotonic`은 프로세스가 다시 시작되면 기준이 바뀌어요. 저장한 데이터를 다시 읽을 때 TTL을 이어 가려면 `time.time` 기준 시각으로 저장하는 방법을 검토해요.

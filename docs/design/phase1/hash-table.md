# 해시 테이블 설계

이 문서를 읽으면 mini-redis가 key-value를 어떻게 저장하고 찾는지 알 수 있어요. 버킷 구조, 해시 함수, 탐사 규칙, 확장 조건, 명령어별 실행 순서를 그대로 따라 `mini_redis/store.py`를 구현할 수 있어요.

요구사항은 [Phase 1 요구사항 명세서](../../requirements/phase1/phase1_requirement.md)를 기준으로 해요.

## 전체 흐름

```
클라이언트 → server.py: 본문 크기·JSON 형식 검사
          → dispatcher.py: 명령어·인자 개수·입력값 검사
          → store.py: 해시 함수 → _probe(key) → 명령 수행
          → dispatcher.py: 응답 dict 생성 → server.py: JSON 응답
```

- `server.py`는 HTTP만 다뤄요. 요청 본문이 1MB를 넘으면 `413 VALUE_TOO_LARGE`를 반환해요. (R-24)
- `dispatcher.py`는 입력값을 검사하고 `store.py`를 불러요. 응답 형식(`ok`, `result`, `error`)은 이 계층에서 만들어요.
- `store.py`는 응답 형식을 몰라요. 문제가 생기면 예외를 던지고, `dispatcher.py`가 오류 응답으로 바꿔요.

## 자료구조

### State

버킷의 상태예요. (R-21)

| 값 | 뜻 |
| --- | --- |
| `EMPTY` | 한 번도 쓰지 않은 칸이에요. 탐사는 여기서 멈춰요. |
| `OCCUPIED` | key-value가 저장된 칸이에요. |
| `TOMBSTONE` | 삭제된 칸이에요. 비어 있지만 탐사는 멈추지 않고 지나가요. |

### Bucket

해시 테이블의 한 칸이에요. (R-20)

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `state` | `State` | 칸의 상태예요. 처음에는 `EMPTY`예요. |
| `key` | `str` | 저장된 key예요. 충돌이 나면 여러 key가 같은 홈 버킷을 가지므로, 탐사할 때 이 값으로 같은 key인지 비교해요. (예: `"kiwi"`) |
| `key_len` | `int` | key의 UTF-8 byte 길이예요. 최대 99예요. (R-23) (예: `"kiwi"` → `4`) |
| `value` | `str` | 저장된 value예요. 빈 문자열 `""`도 저장할 수 있어요. (R-12) |
| `value_len` | `int` | value의 UTF-8 byte 길이예요. (예: `"green"` → `5`) |
| `expire_at` | `float` 또는 `None` | 만료 시각이에요. `time.monotonic()` 기준 초 단위예요. `None`이면 만료되지 않아요. |

남은 시간(ttl) 대신 만료 시각(`expire_at`)을 저장해요. 그러면 매초 값을 줄일 필요 없이, 조회할 때 `now >= expire_at`만 비교하면 돼요. `time.monotonic()`을 쓰면 시스템 시계가 바뀌어도 만료 시각이 틀어지지 않아요.

```python
from enum import Enum


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
        self.expire_at = None

    def fill(self, key, value, expire_at=None):
        """새로 넣거나 덮어쓸 때 모든 필드를 한 번에 채워요."""
        self.state = State.OCCUPIED
        self.key = key
        self.key_len = len(key.encode("utf-8"))
        self.value = value
        self.value_len = len(value.encode("utf-8"))
        self.expire_at = expire_at

    def mark_deleted(self):
        """TOMBSTONE으로 바꾸고 데이터를 비워요."""
        self.state = State.TOMBSTONE
        self.key = None
        self.key_len = 0
        self.value = None
        self.value_len = 0
        self.expire_at = None

    def is_expired(self, now):
        return self.expire_at is not None and now >= self.expire_at
```

`__slots__`를 쓰면 버킷마다 `__dict__`가 생기지 않아서 메모리를 아낄 수 있어요.

### HashTable

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `capacity` | `int` | 버킷 수예요. 처음에는 8이고(R-06), 항상 2의 거듭제곱이에요. |
| `size` | `int` | `OCCUPIED` 버킷 수예요. DBSIZE가 이 값을 반환해요. (R-19) |
| `tombstones` | `int` | `TOMBSTONE` 버킷 수예요. 적재율을 계산할 때 써요. |
| `buckets` | `list[Bucket]` | 버킷 배열이에요. |

```python
INITIAL_CAPACITY = 8          # R-06
LOAD_FACTOR_LIMIT = 0.75      # R-07
MAX_CAPACITY = 1 << 20        # 약 100만 버킷
MAX_KEY_LEN = 99              # R-23


class HashTable:
    def __init__(self, capacity=INITIAL_CAPACITY):
        self.capacity = capacity
        self.size = 0
        self.tombstones = 0
        self.buckets = [Bucket() for _ in range(capacity)]
```

## 해시 함수: FNV-1a (64bit)

key를 홈 버킷 인덱스로 바꿔요. (R-09, R-10)

1. key를 UTF-8 byte로 바꿔요. 아스키 대신 UTF-8을 쓰면 한글 key도 처리할 수 있고, `key_len`과 기준이 같아져요.
2. `h`를 `FNV_OFFSET`으로 시작해요.
3. byte마다 `h`와 XOR한 뒤 `FNV_PRIME`을 곱해요. 곱한 결과는 64bit로 잘라요.
4. `h % capacity`로 0 ~ capacity-1 범위의 인덱스를 만들어요.

Python 정수는 크기 제한이 없어서, C의 `unsigned long long`처럼 저절로 잘리지 않아요. 그래서 곱할 때마다 `& MASK_64`로 직접 잘라요. Python 내장 `hash()`는 실행할 때마다 문자열 해시값이 바뀌어서(`PYTHONHASHSEED`) 테스트를 재현하기 어려우므로 쓰지 않아요.

```python
FNV_OFFSET = 14695981039346656037   # 0xcbf29ce484222325
FNV_PRIME = 1099511628211           # 0x100000001b3
MASK_64 = 0xFFFFFFFFFFFFFFFF


def fnv1a_64(key):
    h = FNV_OFFSET
    for byte in key.encode("utf-8"):
        h ^= byte
        h = (h * FNV_PRIME) & MASK_64
    return h
```

## 충돌 처리: 선형 탐사

key가 이미 다른 key가 있는 칸으로 변환되면(collision), 다음 칸으로 한 칸씩 이동하며 자리를 찾아요. (R-08)

### TOMBSTONE을 쓰는 이유

삭제한 칸을 `EMPTY`로 바꾸면 탐사 경로가 끊겨요. A, B, C가 모두 2번으로 해시돼서 2, 3, 4번에 저장된 상태에서 B를 삭제한 경우를 볼게요.

```
EMPTY로 바꾸면:      [2] A   [3] EMPTY       [4] C
GET C: [2] A 아님 → [3] EMPTY → "없음"으로 멈춤 ❌

TOMBSTONE으로 바꾸면: [2] A   [3] TOMBSTONE   [4] C
GET C: [2] A 아님 → [3] 지나감 → [4] C 찾음 ✅
```

### wrap-around

마지막 칸 다음은 0번으로 돌아가요.

```python
i = (i + 1) % self.capacity
```

적재율을 0.75 이하로 유지하므로 테이블에는 항상 `EMPTY`가 25% 이상 남아 있어요. 그래서 탐사는 한 바퀴를 다 돌기 전에 반드시 `EMPTY`를 만나요. 안전장치로 탐사 횟수를 `capacity`로 제한해요.

## _probe

key의 홈 버킷부터 `EMPTY`를 만날 때까지 탐사해서, key가 저장된 위치와 새로 넣을 위치를 찾아 줘요. SET, GET, DEL, EXISTS가 모두 이 함수를 불러요. 탐사 규칙이 한 곳에만 있어서, 규칙을 고칠 때도 이 함수만 바꾸면 돼요.

**반환값**: `(found, insert_at)` 튜플이에요.

| 이름 | 뜻 | 쓰는 명령어 |
| --- | --- | --- |
| `found` | key가 이미 저장된 버킷의 인덱스예요. 없으면 `None`이에요. | SET, GET, DEL, EXISTS |
| `insert_at` | key를 새로 넣을 버킷의 인덱스예요. key를 찾았으면 `found`와 같아요. | SET |

**동작 순서**

1. 해시 함수로 key를 홈 버킷 인덱스로 바꿔요. 처음 만난 `TOMBSTONE`의 위치는 아직 없다고 두고 시작해요.
2. 홈 버킷부터 한 칸씩 탐사해요. 마지막 칸 다음은 0번으로 돌아가고, 최대 한 바퀴까지만 봐요.
   - `EMPTY`이면 → key가 없다는 뜻이에요. `(None, 넣을 위치)`를 반환하고 끝내요. 넣을 위치는 기억해 둔 `TOMBSTONE`이 있으면 그 위치이고, 없으면 지금 `EMPTY` 위치예요.
   - `TOMBSTONE`이면 → 처음 만난 것이라면 위치를 기억해 둬요. 그다음 칸으로 넘어가요.
   - `OCCUPIED`이고 key가 같으면 → `(그 위치, 그 위치)`를 반환하고 끝내요.
   - `OCCUPIED`이고 key가 다르면 → 다음 칸으로 넘어가요.
3. 한 바퀴를 다 돌았는데 `EMPTY`도 key도 못 찾았으면 `(None, 기억해 둔 TOMBSTONE 위치)`를 반환해요. 적재율을 0.75 이하로 유지하면 이 경우는 일어나지 않아요.

```python
def _probe(self, key):
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
```

## 확장

### 확장 조건

SET에서 새 key를 넣기 **전에** 확인해요. (R-07)

```python
(self.size + self.tombstones + 1) / self.capacity > LOAD_FACTOR_LIMIT
```

- **`TOMBSTONE`도 같이 세요.** `TOMBSTONE`도 탐사 경로를 막고 있어서, `OCCUPIED`만 세면 SET과 DEL이 반복될 때 테이블이 `TOMBSTONE`으로 가득 차도 확장되지 않아요.
- **넣기 전에 `+1`로 확인해요.** 넣은 뒤에 확인하면 넣는 순간 이미 0.75를 넘어요. 넣기 전에 확인하면 적재율이 항상 0.75 이하로 유지돼요.
- **SET에서만 확인해요.** `size + tombstones`가 늘어나는 경우는 새 key를 넣을 때뿐이에요. DEL은 `OCCUPIED`를 `TOMBSTONE`으로 바꾸므로 합계가 그대로예요.
- `+1` 확인은 기존 key를 덮어쓸 때도 실행돼서, 경계에서는 필요 없는 확장이 한 번 일어날 수 있어요. 코드를 단순하게 유지하려고 이 비용은 감수해요.

### 최대 크기

`MAX_CAPACITY`는 `1 << 20`(약 100만 버킷)이에요. 적재율 0.75를 적용하면 key를 약 78만 개까지 저장할 수 있어요.

확장 조건을 만족했는데 `capacity`가 이미 `MAX_CAPACITY`이면, 확장하지 않고 `StoreFullError`를 던져요. `dispatcher.py`가 이 예외를 받아 `STORE_FULL` 오류로 응답해요. 실제 Redis가 `maxmemory`를 넘었을 때 OOM 오류를 내는 것과 같은 방식이에요.

```python
class StoreFullError(Exception):
    pass
```

### _resize

1. 크기가 `capacity * 2`인 새 버킷 배열을 만들어요.
2. 기존 버킷 중 `OCCUPIED`이고 만료되지 않은 것만 새 배열로 옮겨요. 새 `capacity`로 홈 버킷을 다시 계산해서 `_probe`의 `insert_at`에 넣어요. `TOMBSTONE`과 만료된 key는 버려요. (R-22)
3. `size`는 옮긴 개수로, `tombstones`는 0으로 맞춰요.

새 배열에는 중복 key도 `TOMBSTONE`도 없어서, `_probe`가 반환한 `insert_at`에 바로 넣으면 돼요.

```python
def _resize(self, new_capacity):
    old_buckets = self.buckets
    now = time.monotonic()

    self.capacity = new_capacity
    self.buckets = [Bucket() for _ in range(new_capacity)]
    self.size = 0
    self.tombstones = 0

    for b in old_buckets:
        if b.state == State.OCCUPIED and not b.is_expired(now):
            _, insert_at = self._probe(b.key)
            self.buckets[insert_at].fill(b.key, b.value, b.expire_at)
            self.size += 1
```

## 입력값 검사

`dispatcher.py`에서 저장소를 보기 전에 검사해요.

| 조건 | 응답 | 근거 |
| --- | --- | --- |
| key가 문자열이 아님 (`null` 포함) | 오류 `WRONG_TYPE` | R-25 |
| key의 UTF-8 길이가 99byte 초과 | 오류 `KEY_TOO_LONG` | R-23 |
| SET에서 value가 문자열이 아님 (`null` 포함) | 오류 `WRONG_TYPE` | R-11, R-25 |
| 요청 본문이 1MB 초과 | 오류 `VALUE_TOO_LARGE` (`server.py`에서 검사) | R-24 |

다음 경우는 오류가 아니에요. 요청은 올바르고 데이터가 없을 뿐이에요.

| 조건 | 응답 | 근거 |
| --- | --- | --- |
| GET한 key가 없음 | nil (`ok: true`, `result: null`) | R-16 |
| GET한 key가 만료됐거나 삭제됨 | nil | R-11 비고 |
| DEL한 key가 없음 | `0` | R-17 |

SET에서 value로 `null`을 받지 않으므로, GET의 `null`은 항상 "없음"이라는 뜻만 가져요.

## 명령어별 실행 순서

### SET (`SET kiwi green`)

1. key와 value가 문자열인지, key가 99byte 이하인지 검사해요. 아니면 오류를 반환하고 끝내요. (R-23, R-25)
2. `(size + tombstones + 1) / capacity > 0.75`이면 테이블을 2배로 확장해요. (R-07) 이미 `MAX_CAPACITY`이면 `STORE_FULL` 오류를 반환하고 끝내요.
3. `_probe(kiwi)`를 실행해서 `(found, insert_at)`을 받아요. 확장 뒤에는 홈 버킷이 바뀌므로, 반드시 2번 다음에 실행해요.
4. `found`가 있으면 → 그 버킷을 `fill`로 덮어쓰고 6번으로 가요. value, `value_len`, `expire_at`이 함께 바뀌어요. (R-14)
5. `found`가 없으면 → `insert_at` 버킷을 `fill`로 채워서 `OCCUPIED`로 바꿔요. 그 자리가 `TOMBSTONE`이었으면 `tombstones -= 1`을 해요. 마지막으로 `size += 1`을 해요.
6. `OK`를 반환해요.

### GET (`GET kiwi`)

1. key가 문자열인지, 99byte 이하인지 검사해요. 아니면 오류를 반환하고 끝내요. (R-23, R-25)
2. `_probe(kiwi)`를 실행해서 `found`를 받아요.
3. `found`가 없으면 → nil을 반환해요. (R-16)
4. `found`가 있지만 만료됐으면 → `mark_deleted`로 `TOMBSTONE`으로 바꾸고 `size -= 1`, `tombstones += 1`을 해요. nil을 반환해요.
5. 그 외에는 → 그 버킷의 value를 반환해요. (R-15)

### DEL (`DEL kiwi`)

1. key가 문자열인지, 99byte 이하인지 검사해요. 아니면 오류를 반환하고 끝내요. (R-23, R-25)
2. `_probe(kiwi)`를 실행해서 `found`를 받아요.
3. `found`가 없으면 → `0`을 반환해요.
4. `found`가 있으면 → `mark_deleted`로 `TOMBSTONE`으로 바꾸고 `size -= 1`, `tombstones += 1`을 해요.
5. `1`을 반환해요. 만료된 key였다면 4번처럼 정리만 하고 `0`을 반환해요. (R-17)

### EXISTS (`EXISTS kiwi`)

1. key가 문자열인지, 99byte 이하인지 검사해요. 아니면 오류를 반환하고 끝내요. (R-23, R-25)
2. `_probe(kiwi)`를 실행해서 `found`를 받아요.
3. `found`가 없으면 → `0`을 반환해요.
4. `found`가 있지만 만료됐으면 → GET 4번처럼 정리하고 `0`을 반환해요.
5. 그 외에는 → `1`을 반환해요. (R-18)

### DBSIZE

1. `size`를 반환해요. (R-19) `_probe`는 부르지 않아요.

만료됐지만 아직 조회되지 않은 key는 `OCCUPIED`로 남아 있어서 `size`에 포함돼요. 만료는 조회할 때 확인하는 방식(lazy expiration)이라 생기는 차이예요.

## dispatcher 연결

1. SET, GET, DEL, EXISTS, DBSIZE를 `COMMANDS`에 인자 개수와 함께 등록해요.

   | 명령어 | 인자 개수 | 성공 응답 `result` |
   | --- | --- | --- |
   | `SET` | 2 | `"OK"` |
   | `GET` | 1 | value 또는 `null` |
   | `DEL` | 1 | `1` 또는 `0` |
   | `EXISTS` | 1 | `1` 또는 `0` |
   | `DBSIZE` | 0 | 저장된 key 개수 |

2. 명령어 함수가 입력값 오류를 반환할 수 있게, 명령어 함수는 `(HTTP 상태 코드, 응답 dict)`를 반환해요. `execute`의 마지막 줄 `return 200, func(args)`를 `return func(args)`로 바꾸고, `cmd_ping`도 `(200, ok_response("PONG"))`을 반환하게 고쳐요.
3. SET에서 `StoreFullError`가 나면 오류 응답 `STORE_FULL`로 바꿔요.

## 결정이 필요한 것

- **`expire_at`을 설정하는 명령어**: 요구사항에 `EXPIRE`나 `SET key value EX 초` 같은 명령어가 없어서, Phase 1에서는 `expire_at`이 항상 `None`이에요. 만료 확인 흐름은 이 문서대로 먼저 구현해 두고, TTL 명령어를 Phase 1에 넣을지는 따로 정해요.
- **`STORE_FULL`, `WRONG_TYPE`, `KEY_TOO_LONG`의 HTTP 상태 코드**: 입력값 오류는 기존 오류처럼 `400`을 제안해요. `STORE_FULL`은 서버 쪽 한계라서 `507 Insufficient Storage`를 제안해요.

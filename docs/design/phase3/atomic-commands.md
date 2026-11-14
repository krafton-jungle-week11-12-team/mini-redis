# 원자적 명령어 설계

이 문서를 읽으면 Phase 3에서 추가하는 명령어가 어떤 순서로 실행되고, 왜 중간에 다른 요청이 끼어들 수 없는지 알 수 있어요. 공통 함수(`_ensure_capacity`, `_write`), 명령어별 실행 순서, dispatcher 변경을 그대로 따라 `mini_redis/store.py`와 `mini_redis/dispatcher.py`를 구현할 수 있어요.

요구사항은 [Phase 3 요구사항 명세서](../../requirements/phase3/phase3_requirement.md)를 기준으로 해요. 해시 테이블 구조와 `_probe`는 [해시 테이블 설계](../phase1/hash-table.md)를 그대로 써요.

## 다루는 범위

| 분류 | 명령어 | 요구사항 | 이 문서 |
| --- | --- | --- | --- |
| 원자성 | - | R-41 | ✅ |
| 값 교체 | `GETSET` | R-39 | ✅ |
| 조건부 SET | `SETNX`, `SETXX` | R-44, R-45 | ✅ |
| 카운터 | `INCR`, `DECR` | R-46 ~ R-48 | ✅ |
| 일괄 처리 | `MSET`, `MGET` | R-42, R-43 | ✅ |
| 트랜잭션 | `EXEC` (클라이언트 `multi()` → `exec()`) | R-49 | [트랜잭션 설계](transaction.md)에서 다뤄요 |
| 트랜잭션 | WATCH | R-50 | optional이라 [트랜잭션 설계](transaction.md#다음-설계로-넘기는-것)에 방향만 적었어요 |
| 스크립트 | - | R-40 | 후순위라 다루지 않아요 |

## 원자성을 지키는 방법 (R-41)

```
요청 A ──→ [ execute(A) 전체 실행 ] ──→ 응답 A
요청 B ──────────────── 기다림 ──────→ [ execute(B) ] ──→ 응답 B
```

- 서버는 `http.server.HTTPServer`라 스레드가 하나예요. 요청 하나의 `execute`가 끝나야 다음 요청을 읽어요. 그래서 lock이 필요 없어요.
- **명령어 하나는 `store.py` 메서드 하나로 끝나요.** 예를 들어 GETSET은 `store.get` → `store.set`을 dispatcher에서 따로 부르지 않고, `store.getset` 안에서 탐사 한 번으로 읽고 써요. 단일 스레드라 따로 불러도 결과는 같지만, 한 메서드에 모아 두면 "이 명령어는 이 함수 하나"라고 바로 읽혀요.
- `ThreadingHTTPServer`로 바꾸면 이 전제가 깨져요. 바꿀 때는 `execute` 전체를 lock으로 감싸야 해요.

## 결정 사항

| 항목 | 선택 | 이유 |
| --- | --- | --- |
| GET·NX·XX | SET 옵션 대신 별도 명령어 `GETSET`, `SETNX`, `SETXX` | 옵션을 해석하지 않아도 돼요. `SETXX`는 실제 Redis에 없어서 직접 정의해요. |
| 확장 검사 | `_ensure_capacity(extra)`로 분리 | MSET은 key 여러 개를 넣기 전에 한 번에 확인해야 해요. SET도 같은 함수를 `extra=1`로 불러요. |
| 조건 검사와 확장 순서 | 조건을 먼저 보고, 저장이 확실할 때만 확장 | SETNX가 실패하는데 확장만 일어나지 않게 해요. |
| INCR·DECR 응답 | 정수 (`11`) | DEL·EXISTS처럼 정수예요. 저장은 문자열 `"11"`로 해요. |
| 정수 판정 | `re.fullmatch(r"-?[0-9]+", value)` | `int()`는 `" 1"`, `"+1"`, `"1_000"`도 받아들여요. `str.isdigit()`는 `"²"`도 숫자로 봐요. |
| 정수 범위 | -2^63 ~ 2^63-1 | 실제 Redis와 같아요. Python `int`는 크기 제한이 없어서 직접 검사해요. |
| MSET·MGET 최대 개수 | key 20개 | 한 요청이 서버를 오래 붙잡지 않게 해요. |

## 공통 함수

### _ensure_capacity(extra)

key를 `extra`개 새로 넣어도 적재율이 0.75 이하인지 확인하고, 넘으면 확장해요. Phase 1 SET에 있던 `+1` 확인을 함수로 뺀 거예요.

1. `(size + tombstones + extra) / capacity <= 0.75`이면 아무것도 하지 않고 끝내요.
2. 새 크기를 `capacity * 2`로 잡아요. 확장하면 `TOMBSTONE`이 사라지므로, `(size + extra) / 새 크기 <= 0.75`가 될 때까지 2배씩 늘려요. MSET은 한 번에 20개까지 들어오므로 한 번 2배로는 부족할 수 있어요.
3. 새 크기가 `MAX_CAPACITY`를 넘으면 `StoreFullError`를 던져요. 아직 아무것도 바꾸지 않았어요.
4. `_resize(새 크기)`를 불러요.

```python
def _ensure_capacity(self, extra):
    if (self.size + self.tombstones + extra) / self.capacity <= LOAD_FACTOR_LIMIT:
        return
    new_capacity = self.capacity * 2
    while (self.size + extra) / new_capacity > LOAD_FACTOR_LIMIT:
        new_capacity *= 2
    if new_capacity > MAX_CAPACITY:
        raise StoreFullError
    self._resize(new_capacity)
```

`extra=1`이면 Phase 1의 동작과 같아요. 2배 한 번으로 항상 충분하고, `capacity`가 이미 `MAX_CAPACITY`일 때만 `StoreFullError`가 나요. 그래서 Phase 1 확장 테스트(EXP)는 그대로 통과해야 해요.

### _write(found, insert_at, key, value)

`_probe` 결과를 받아 버킷에 쓰고 `size`, `tombstones`를 맞춰요. Phase 1 SET의 4~5번 단계를 함수로 뺀 거예요.

```python
def _write(self, found, insert_at, key, value):
    if found is not None:
        self.buckets[found].fill(key, value)        # 덮어쓰기: 개수 변화 없음
        return
    bucket = self.buckets[insert_at]
    if bucket.state == State.TOMBSTONE:
        self.tombstones -= 1
    bucket.fill(key, value)
    self.size += 1
```

### SET 정리

두 함수를 쓰면 SET은 이렇게 줄어요. 동작은 Phase 1과 같아요.

```python
def set(self, key, value):
    self._ensure_capacity(1)                  # 확장 뒤에는 홈 버킷이 바뀌므로
    found, insert_at = self._probe(key)       # 반드시 확장 다음에 탐사해요
    self._write(found, insert_at, key, value)
```

## 명령어별 실행 순서

dispatcher의 입력값 검사(명령어, 인자 개수, 문자열, key 길이)는 [dispatcher 연결](#dispatcher-연결)에서 한 번에 해요. 아래 순서는 검사를 통과한 뒤부터예요.

### GETSET (`GETSET name kim`)

저장하면서 저장 **전** 값을 돌려줘요. (R-39)

1. `_ensure_capacity(1)`을 불러요. key가 이미 있어도 확인해요. SET과 같은 기준이에요.
2. `_probe(name)`으로 `(found, insert_at)`을 받아요.
3. `found`가 있으면 그 버킷의 value를 이전 값으로 기억해요. 없으면 이전 값은 `None`이에요.
4. `_write`로 저장해요.
5. 3번의 이전 값을 반환해요.

```
> SET name lee
> GETSET name kim     → "lee"
> GET name            → "kim"
> GETSET new hello    → nil
```

```python
def getset(self, key, value):
    self._ensure_capacity(1)
    found, insert_at = self._probe(key)
    old = self.buckets[found].value if found is not None else None
    self._write(found, insert_at, key, value)
    return old
```

### SETNX (`SETNX user:1 lee`)

key가 없을 때만 저장해요. (R-44)

1. `_probe(user:1)`로 `found`를 받아요.
2. `found`가 있으면 → 저장하지 않고 `0`을 반환해요. 확장도 하지 않아요.
3. `_ensure_capacity(1)`을 불러요. 새 key를 넣는 게 확실하므로 이제 확인해요.
4. 확장됐을 수 있으므로 `_probe`를 다시 불러 `insert_at`을 받아요.
5. `_write`로 저장하고 `1`을 반환해요.

```
> SETNX user:1 lee    → (integer) 1
> SETNX user:1 kim    → (integer) 0
> GET user:1          → "lee"
```

```python
def setnx(self, key, value):
    found, _ = self._probe(key)
    if found is not None:
        return 0
    self._ensure_capacity(1)
    _, insert_at = self._probe(key)
    self._write(None, insert_at, key, value)
    return 1
```

새 key를 넣을 때는 탐사를 두 번 해요. 확장이 일어났을 때만 다시 탐사하는 방법도 있지만, 분기를 줄이려고 항상 다시 탐사해요.

### SETXX (`SETXX user:3 lee`)

key가 있을 때만 저장해요. (R-45) 실제 Redis에는 없는 명령어로, `SET key value XX`와 같은 동작이에요.

1. `_probe(user:3)`로 `found`를 받아요.
2. `found`가 없으면 → 저장하지 않고 `0`을 반환해요.
3. `found` 버킷을 덮어쓰고 `1`을 반환해요.

덮어쓰기만 하므로 `size + tombstones`가 늘지 않아요. 그래서 `_ensure_capacity`를 부르지 않아요. 저장소가 가득 차도(`STORE_FULL`) SETXX는 성공해요.

```
> SETXX user:3 lee    → (integer) 0     # user:3이 없음
> SET user:3 park
> SETXX user:3 lee    → (integer) 1
```

```python
def setxx(self, key, value):
    found, _ = self._probe(key)
    if found is None:
        return 0
    self.buckets[found].fill(key, value)
    return 1
```

### INCR / DECR (`INCR views`)

저장된 정수에 1을 더하거나 빼요. (R-46 ~ R-48) 둘 다 `incr_by(key, delta)` 하나로 처리하고, INCR은 `delta=1`, DECR은 `delta=-1`로 불러요.

1. `_probe(views)`로 `found`를 받아요.
2. `found`가 없으면 → 현재 값을 `0`으로 봐요. 카운터를 SET 없이 바로 쓸 수 있게 해요.
3. `found`가 있으면 → value가 정수 형식(`-?[0-9]+`)인지 확인해요. 아니면 `NotIntegerError`를 던져요. 맞으면 `int`로 바꿔요. 형식이 맞아도 범위(-2^63 ~ 2^63-1)를 넘으면 정수가 아니라고 봐요.
4. `delta`를 더해요.
5. 결과가 범위를 넘으면 `IntegerOverflowError`를 던져요. 아직 아무것도 바꾸지 않았어요.
6. 저장해요. 결과는 문자열(`str(new)`)로 저장해요.
   - `found`가 있으면 → 그 버킷을 덮어써요. 확장은 필요 없어요.
   - `found`가 없으면 → `_ensure_capacity(1)` → `_probe`를 다시 불러 `insert_at`에 `_write`해요.
7. 결과를 정수로 반환해요.

```
> INCR views          → (integer) 1      # views가 없어서 0 + 1
> INCR views          → (integer) 2
> DECR views          → (integer) 1
> GET views           → "1"              # 저장은 문자열
> SET name kim
> INCR name           → (error) NOT_INTEGER
> SET big 9223372036854775807
> INCR big            → (error) INTEGER_OVERFLOW
```

```python
import re

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1
_INTEGER = re.compile(r"-?[0-9]+")


class NotIntegerError(Exception):
    """INCR·DECR 대상 value가 정수가 아닐 때 던져요."""


class IntegerOverflowError(Exception):
    """INCR·DECR 결과가 64비트 정수 범위를 넘을 때 던져요."""


def incr_by(self, key, delta):
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
        raise IntegerOverflowError

    if found is not None:
        self.buckets[found].fill(key, str(new))
    else:
        self._ensure_capacity(1)
        _, insert_at = self._probe(key)
        self._write(None, insert_at, key, str(new))
    return new
```

`re.match(r"^-?[0-9]+$")`는 쓰지 않아요. `$`는 끝의 줄바꿈 앞에서도 맞아서 `"1\n"`을 정수로 봐요. `fullmatch`는 문자열 전체가 맞아야 해요. `\d` 대신 `[0-9]`를 쓰는 이유도 같아요. `\d`는 아라비아 숫자 `"٣"` 같은 다른 문자도 숫자로 봐요.

### MSET (`MSET a 1 b 2 c 3`)

여러 key-value를 한 번에 저장해요. 전부 저장하거나 하나도 저장하지 않아요. (R-42)

1. dispatcher에서 인자 개수가 짝수인지, key가 20개 이하인지, 모든 key·value가 문자열인지, 모든 key가 99byte 이하인지 검사해요. 하나라도 틀리면 오류를 반환하고 끝내요. 아직 아무것도 저장하지 않았어요.
2. `_ensure_capacity(쌍 개수)`를 불러요. 넣을 자리를 한 번에 확보해요. 자리가 없으면 `StoreFullError`가 나고, 역시 아무것도 저장하지 않았어요.
3. 쌍마다 `_probe(key)` → `_write`를 해요. 2번에서 자리를 미리 확보해서 중간에 확장이 일어나지 않아요.
4. `OK`를 반환해요.

```
> MSET a 1 b 2 c 3    → "OK"
> MSET a 1 b          → (error) WRONG_ARGS     # 짝수가 아님, 아무것도 저장 안 함
```

```python
def mset(self, pairs):
    self._ensure_capacity(len(pairs))
    for key, value in pairs:
        found, insert_at = self._probe(key)
        self._write(found, insert_at, key, value)
```

- **전부 아니면 전무가 되는 이유**: 실패할 수 있는 지점(입력값 검사, `StoreFullError`)이 모두 첫 저장 **전**에 있어요. 저장을 시작한 뒤에는 실패할 일이 없어요.
- **이미 있는 key도 새 key로 세요.** 몇 개가 덮어쓰기인지 미리 알려면 탐사를 한 번 더 해야 해요. SET의 `+1` 확인처럼, 필요 없는 확장이 일어날 수 있는 비용은 감수해요.
- **같은 key가 여러 번 오면** 앞에서부터 차례로 저장하므로 마지막 값이 남아요. (`MSET a 1 a 2` → `GET a`는 `"2"`)

### MGET (`MGET a b c d`)

여러 key의 value를 한 번에 조회해요. (R-43)

1. dispatcher에서 key가 1 ~ 20개인지, 모두 문자열이고 99byte 이하인지 검사해요.
2. key마다 `get(key)`를 불러 결과를 목록에 담아요. 없는 key는 `None`이에요.
3. 목록을 반환해요. 순서는 요청한 key 순서와 같아요.

```
> MSET a 1 b 2 c 3
> MGET a b c d
1) "1"
2) "2"
3) "3"
4) (nil)
```

```python
def mget(self, keys):
    return [self.get(key) for key in keys]
```

## 오류 코드

Phase 1 [오류 코드](../phase1/hash-table.md#오류-코드)에 두 개를 추가해요. 응답 형식은 같아요.

| 코드 | HTTP 상태 | 언제 | 검사 위치 | 근거 |
| --- | --- | --- | --- | --- |
| `NOT_INTEGER` | 400 | INCR·DECR 대상 value가 정수 형식이 아니거나 64비트 범위를 넘을 때 | `store.py`가 `NotIntegerError`를 던지고 `dispatcher.py`가 변환 | R-46 |
| `INTEGER_OVERFLOW` | 400 | INCR·DECR 결과가 64비트 범위를 넘을 때 | `store.py`가 `IntegerOverflowError`를 던지고 `dispatcher.py`가 변환 | R-46 |

기존 코드도 새 명령어에서 이렇게 쓰여요.

| 코드 | 새 명령어에서 언제 |
| --- | --- |
| `WRONG_ARGS` | MSET 인자 개수가 홀수이거나, MSET·MGET의 key가 20개를 넘을 때 |
| `WRONG_TYPE`, `KEY_TOO_LONG` | MSET·MGET에서 key 하나라도 조건에 맞지 않을 때. 첫 번째 key만이 아니라 모든 key를 검사해요 |
| `STORE_FULL` | GETSET, SETNX(새 key), INCR·DECR(새 key), MSET에서 확장할 수 없을 때. SETXX에서는 나지 않아요 |

## dispatcher 연결

### 명령어 테이블

MSET과 MGET은 인자 개수가 바뀌고, key가 첫 번째 인자에만 있지 않아요. 그래서 `COMMANDS`의 값을 `(함수, 인자 개수)`에서 아래 네 가지로 바꿔요.

| 필드 | 뜻 |
| --- | --- |
| `func` | 실행할 함수예요. |
| `min_args`, `max_args` | 인자 개수의 범위예요. 고정이면 같은 값을 넣어요. |
| `keys` | 인자 중 key가 있는 위치예요. 이 위치의 인자만 99byte 검사를 해요. |

```python
from collections import namedtuple

Command = namedtuple("Command", "func min_args max_args keys")

FIRST = slice(0, 1)          # 첫 번째 인자만 key (Phase 1 명령어)
ALL = slice(None)            # 모든 인자가 key (MGET)
PAIRS = slice(0, None, 2)    # 0, 2, 4번째 인자가 key (MSET)

MAX_BATCH = 20               # MSET·MGET 한 번에 다루는 key 수

COMMANDS = {
    "PING":   Command(cmd_ping, 0, 0, FIRST),
    "SET":    Command(cmd_set, 2, 2, FIRST),
    "GET":    Command(cmd_get, 1, 1, FIRST),
    # ... DEL, EXISTS, DBSIZE, INFO, FLUSH도 같은 방식
    "GETSET": Command(cmd_getset, 2, 2, FIRST),
    "SETNX":  Command(cmd_setnx, 2, 2, FIRST),
    "SETXX":  Command(cmd_setxx, 2, 2, FIRST),
    "INCR":   Command(cmd_incr, 1, 1, FIRST),
    "DECR":   Command(cmd_decr, 1, 1, FIRST),
    "MSET":   Command(cmd_mset, 2, MAX_BATCH * 2, PAIRS),
    "MGET":   Command(cmd_mget, 1, MAX_BATCH, ALL),
}
```

인자가 없는 명령어(PING, DBSIZE)는 `args[FIRST]`가 빈 목록이라 key 검사를 그냥 통과해요.

### 성공 응답

| 명령어 | 인자 개수 | 성공 응답 `result` |
| --- | --- | --- |
| `GETSET` | 2 | 이전 value 또는 `null` |
| `SETNX` | 2 | `1` 또는 `0` |
| `SETXX` | 2 | `1` 또는 `0` |
| `INCR` | 1 | 더한 뒤의 정수 |
| `DECR` | 1 | 뺀 뒤의 정수 |
| `MSET` | 2 ~ 40 (짝수) | `"OK"` |
| `MGET` | 1 ~ 20 | value 또는 `null`의 배열 |

### execute

검사 순서는 Phase 1과 같고, 2번과 4번만 바뀌어요.

```python
def execute(command, args):
    name = command.upper()
    if name not in COMMANDS:                                        # 1. 명령어
        return 400, error_response("UNKNOWN_COMMAND", f"{command}는 지원하지 않는 명령어예요")

    spec = COMMANDS[name]
    if not spec.min_args <= len(args) <= spec.max_args:             # 2. 인자 개수 (범위)
        return 400, error_response("WRONG_ARGS", f"{name}의 인자 개수가 맞지 않아요")
    if spec.keys is PAIRS and len(args) % 2:                        #    MSET은 짝수
        return 400, error_response("WRONG_ARGS", f"{name}은 key와 value를 짝지어 보내야 해요")

    if any(not isinstance(a, str) for a in args):                   # 3. 문자열 (R-11, R-25)
        return 400, error_response("WRONG_TYPE", "key와 value는 문자열이어야 해요")
    if any(len(k.encode("utf-8")) > MAX_KEY_LEN for k in args[spec.keys]):   # 4. 모든 key 길이 (R-23)
        return 400, error_response("KEY_TOO_LONG", f"key는 최대 {MAX_KEY_LEN}byte예요")

    try:
        return 200, spec.func(args)                                 # 5. 실행
    except StoreFullError:
        return 507, error_response("STORE_FULL", "저장소가 가득 찼어요")
    except NotIntegerError:
        return 400, error_response("NOT_INTEGER", "value가 정수가 아니에요")
    except IntegerOverflowError:
        return 400, error_response("INTEGER_OVERFLOW", "정수 범위를 넘어요")
```

### 명령어 함수

```python
def cmd_getset(args):
    return ok_response(store.getset(args[0], args[1]))    # 이전 값, 없으면 None


def cmd_setnx(args):
    return ok_response(store.setnx(args[0], args[1]))     # 1 또는 0


def cmd_setxx(args):
    return ok_response(store.setxx(args[0], args[1]))     # 1 또는 0


def cmd_incr(args):
    return ok_response(store.incr_by(args[0], 1))


def cmd_decr(args):
    return ok_response(store.incr_by(args[0], -1))


def cmd_mset(args):
    store.mset(list(zip(args[0::2], args[1::2])))
    return ok_response("OK")


def cmd_mget(args):
    return ok_response(store.mget(args))
```

## 클라이언트 · CLI

[클라이언트 · CLI 설계](../phase2/client.md)에 아래를 추가해요. 모두 `execute`를 부르기만 해요.

| 메서드 | 보내는 명령어 | 반환값 |
| --- | --- | --- |
| `getset(key, value)` | `GETSET key value` | 이전 value, 없으면 `None` |
| `setnx(key, value)` | `SETNX key value` | `1` 또는 `0` |
| `setxx(key, value)` | `SETXX key value` | `1` 또는 `0` |
| `incr(key)` | `INCR key` | 정수 |
| `decr(key)` | `DECR key` | 정수 |
| `mset(mapping)` | `MSET k1 v1 k2 v2 ...` | `"OK"`. `{"a": "1", "b": "2"}`처럼 dict로 받아요 |
| `mget(*keys)` | `MGET k1 k2 ...` | value 또는 `None`의 list |

CLI의 `format_result`는 list를 처리하지 않아서 지금은 `['1', None]`처럼 출력돼요. list면 항목마다 번호를 붙이고, 각 항목은 지금 규칙(`(nil)`, 따옴표 문자열)대로 바꿔요.

```
1) "1"
2) (nil)
```

## 다음 설계로 넘기는 것

- **트랜잭션 (R-49, R-50)**: [트랜잭션 설계](transaction.md)에서 다뤄요. 이 문서의 명령어 함수를 그대로 다시 써요.
- **스크립트 (R-40)**: Lua를 실행하려면 외부 패키지가 필요해서 후순위예요.

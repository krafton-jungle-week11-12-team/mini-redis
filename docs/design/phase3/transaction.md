# 트랜잭션 설계

이 문서를 읽으면 여러 명령어를 묶어 한 번에 실행하는 트랜잭션이 클라이언트와 서버에서 어떻게 동작하는지 알 수 있어요. 클라이언트의 MULTI → EXEC 흐름, 서버가 받는 배열 형식, 검사와 실행 순서, 실패했을 때의 동작을 그대로 따라 `mini_redis/client.py`, `mini_redis/cli.py`, `mini_redis/dispatcher.py`를 구현할 수 있어요.

요구사항은 [Phase 3 요구사항 명세서](../../requirements/phase3/phase3_requirement.md)의 R-49를 기준으로 해요. 묶이는 명령어 하나하나의 동작은 [원자적 명령어 설계](atomic-commands.md)를 따라요.

## 전체 흐름

```
클라이언트                                   서버
  multi()          → 큐 만들기 (요청 없음)
  set("a", "1")    → 큐에 쌓기 (요청 없음)
  incr("a")        → 큐에 쌓기 (요청 없음)
  exec()           → POST /command ───────→  EXEC: 전부 검사 → 차례로 실행
                   ← [결과1, 결과2] ←──────   결과 배열 응답
```

- **MULTI는 클라이언트에만 있어요.** 서버는 MULTI를 몰라요. 클라이언트가 명령어를 모아 두었다가 `exec()`에서 요청 하나로 보내요.
- **서버는 EXEC 하나만 받아요.** `args`에 명령어 배열을 담아 보내요.
- 서버가 단일 스레드라, EXEC 요청 하나를 처리하는 동안 다른 요청은 끼어들 수 없어요. 그래서 묶인 명령어 전체가 원자적으로 실행돼요. (R-41, R-49)

## 결정 사항

| 항목 | 선택 | 이유 |
| --- | --- | --- |
| MULTI의 위치 | 클라이언트 | 서버가 HTTP/1.0이라 요청마다 연결이 끊겨요. MULTI → … → EXEC를 요청 여러 번으로 보내면 서버는 누가 묶는 중인지 기억할 수 없어요. |
| 서버 요청 형식 | `EXEC` + 명령어 배열 | 요청 하나에 모두 담겨 있어서 서버가 상태를 기억할 필요가 없어요. |
| 검사 실패 | 하나라도 틀리면 **하나도 실행하지 않음** (`EXEC_ABORTED`) | 명령어를 모두 받은 뒤에 실행하므로 실행 전에 전부 검사할 수 있어요. 실제 Redis도 큐에 넣을 때 오류가 나면 EXEC 전체를 취소해요. |
| 실행 중 오류 | 그 명령어만 오류, **나머지는 계속 실행**, 되돌리지 않음 | 실제 Redis와 같아요. 되돌리려면 실행 전 상태를 저장해 둬야 해서 구조가 복잡해져요. 실행 중 오류는 `NOT_INTEGER`, `INTEGER_OVERFLOW`, `STORE_FULL`뿐이에요. |
| 최대 개수 | 명령어 20개 | MSET·MGET의 최대 key 수와 같아요. 요청 하나가 서버를 오래 붙잡지 않게 해요. |
| EXEC 안의 EXEC | 금지 | 중첩하면 검사와 오류 위치가 복잡해지고, 얻는 것이 없어요. |
| WATCH (R-50) | 이번 설계에서 제외 | optional 요구사항이에요. [다음 설계로 넘기는 것](#다음-설계로-넘기는-것)을 참고해요. |

## 서버

### 요청

```json
{
  "command": "EXEC",
  "args": [
    ["SET", "a", "1"],
    ["INCR", "a"],
    ["GET", "a"]
  ]
}
```

- `args`의 각 항목은 `[명령어 이름, 인자1, 인자2, ...]` 배열이에요. 일반 요청의 `command`와 `args`를 배열 하나로 합친 모양이에요.
- 요청 본문 1MB 제한은 그대로예요. (R-24)

### 응답

검사를 통과하면 HTTP 200과 함께 명령어별 응답을 배열로 돌려줘요. 각 항목은 일반 명령어 응답과 같은 `{ok, result, error}` 구조예요. (R-03)

```json
{
  "ok": true,
  "result": [
    {"ok": true, "result": "OK", "error": null},
    {"ok": true, "result": 2, "error": null},
    {"ok": true, "result": "2", "error": null}
  ],
  "error": null
}
```

실행 중 오류가 난 명령어는 그 항목만 오류예요. 바깥 응답은 그대로 `ok: true`예요.

```json
{
  "ok": true,
  "result": [
    {"ok": true, "result": "OK", "error": null},
    {"ok": false, "result": null, "error": {"code": "NOT_INTEGER", "message": "value가 정수가 아니에요"}},
    {"ok": true, "result": "OK", "error": null}
  ],
  "error": null
}
```

### 실행 순서 (`EXEC [["SET","a","1"], ["INCR","a"]]`)

1. 명령어가 1 ~ 20개인지 확인해요. 아니면 `WRONG_ARGS`를 반환하고 끝내요.
2. **모든 명령어를 먼저 검사해요.** 하나라도 틀리면 `EXEC_ABORTED`를 반환하고 끝내요. 아직 아무것도 실행하지 않았어요.
   - 항목이 `[문자열, ...]` 배열인지 확인해요.
   - 명령어 이름이 `EXEC`이면 중첩이라 거부해요.
   - 일반 요청과 같은 검사(명령어, 인자 개수, 문자열, key 길이)를 해요. 오류 메시지에 몇 번째 명령어인지와 원래 오류 코드를 담아요.
3. 명령어를 차례로 실행해요. 실행 중 오류가 나면 그 결과를 오류 응답으로 담고 다음 명령어로 넘어가요.
4. 결과 배열을 담아 200으로 반환해요.

```
> EXEC [["SET","a","1"], ["INCR"]]
→ 400 EXEC_ABORTED "2번째 명령어: WRONG_ARGS INCR의 인자 개수가 맞지 않아요"   # SET도 실행 안 됨

> EXEC [["SET","a","x"], ["INCR","a"], ["SET","b","1"]]
→ 200 [OK, (error) NOT_INTEGER, OK]                                          # a는 "x", b는 "1"로 남음
```

### 되돌리지 않는 경우

실행 중 오류가 나도 앞에서 실행한 명령어는 그대로 남아요.

| 상황 | 결과 |
| --- | --- |
| INCR 대상이 정수가 아님 | 그 INCR만 `NOT_INTEGER`. 앞뒤 명령어는 실행돼요. |
| INCR 결과가 범위를 넘음 | 그 INCR만 `INTEGER_OVERFLOW`. |
| 중간에 저장소가 가득 참 | 그 명령어부터 `STORE_FULL`. 앞에서 저장한 값은 남아요. |

이 오류들은 대부분 쓰는 쪽이 잘못된 값을 다룰 때 나요. 되돌리기를 지원하려면 명령어마다 실행 전 값을 기록해 두는 장치(undo log)가 필요해서, 실제 Redis처럼 지원하지 않아요.

### dispatcher 연결

지금의 `execute`를 **검사**(`check`)와 **실행**(`run`)으로 나눠요. EXEC는 같은 두 함수를 명령어마다 불러요. 그래서 검사 규칙이 한 곳에만 있어요.

```python
MAX_TX = 20                  # EXEC 한 번에 묶는 명령어 수


def check(command, args):
    """검사를 통과하면 None, 실패하면 (HTTP 상태 코드, 오류 응답)을 돌려줘요."""
    # 원자적 명령어 설계의 execute 1 ~ 4번 검사를 그대로 옮겨요.
    # (명령어, 인자 개수, MSET 짝수, 문자열, 모든 key 길이)


def run(command, args):
    """검사를 통과한 명령어를 실행하고 (HTTP 상태 코드, 응답)을 돌려줘요."""
    spec = COMMANDS[command.upper()]
    try:
        return 200, spec.func(args)
    except StoreFullError:
        return 507, error_response("STORE_FULL", "저장소가 가득 찼어요")
    except NotIntegerError:
        return 400, error_response("NOT_INTEGER", "value가 정수가 아니에요")
    except IntegerOverflowError:
        return 400, error_response("INTEGER_OVERFLOW", "정수 범위를 넘어요")


def execute(command, args):
    """(HTTP 상태 코드, 응답 dict)를 돌려줘요."""
    if command.upper() == "EXEC":
        return execute_transaction(args)
    return check(command, args) or run(command, args)


def execute_transaction(commands):
    if not 1 <= len(commands) <= MAX_TX:                              # 1. 개수
        return 400, error_response("WRONG_ARGS", f"EXEC은 명령어 1 ~ {MAX_TX}개를 받아요")

    for i, item in enumerate(commands, 1):                            # 2. 전부 먼저 검사
        if not (isinstance(item, list) and item and isinstance(item[0], str)):
            return 400, error_response("EXEC_ABORTED", f'{i}번째 명령어는 ["이름", 인자...] 배열이어야 해요')
        if item[0].upper() == "EXEC":
            return 400, error_response("EXEC_ABORTED", f"{i}번째 명령어: EXEC 안에 EXEC를 넣을 수 없어요")
        failed = check(item[0], item[1:])
        if failed:
            error = failed[1]["error"]
            return 400, error_response("EXEC_ABORTED", f"{i}번째 명령어: {error['code']} {error['message']}")

    results = [run(item[0], item[1:])[1] for item in commands]        # 3. 차례로 실행
    return 200, ok_response(results)                                  # 4. 결과 배열
```

- 일반 요청에서는 `args`가 모두 문자열이어야 해요. EXEC의 `args`는 배열의 배열이라 `check`를 거치면 `WRONG_TYPE`이 나요. 그래서 EXEC는 `check`보다 먼저 나눠요.
- `server.py`는 이미 `args`가 배열인지 확인해요. 바꿀 것이 없어요.
- `run`이 돌려주는 HTTP 상태 코드는 EXEC 안에서는 쓰지 않아요. 바깥 응답은 항상 200이에요.

## 오류 코드

[원자적 명령어 설계의 오류 코드](atomic-commands.md#오류-코드)에 하나를 추가해요.

| 코드 | HTTP 상태 | 언제 | 검사 위치 | 근거 |
| --- | --- | --- | --- | --- |
| `EXEC_ABORTED` | 400 | EXEC의 명령어 중 하나라도 형식이 틀리거나 검사에 실패했을 때. 아무것도 실행하지 않아요 | `dispatcher.py` | R-49 |

EXEC의 명령어 개수가 0개이거나 20개를 넘으면 기존 `WRONG_ARGS`를 써요.

## 클라이언트

### 메서드

| 메서드 | 하는 일 | 반환값 |
| --- | --- | --- |
| `MiniRedis.multi()` | 명령어를 모을 `Transaction`을 만들어요. 요청은 보내지 않아요. | `Transaction` |
| `Transaction.set(...)` 등 | 명령어를 큐에 쌓아요. `MiniRedis`의 명령어 메서드와 이름·인자가 같아요. | `Transaction` 자신 (이어서 부를 수 있게) |
| `Transaction.execute(command, *args)` | 범용 메서드도 큐에 쌓아요. (R-28) | `Transaction` 자신 |
| `Transaction.exec()` | 쌓인 명령어를 EXEC로 보내고 큐를 비워요. | 결과 list |
| `Transaction.discard()` | 큐를 비워요. 요청은 보내지 않아요. | `None` |

```python
r = MiniRedis()

tx = r.multi()
tx.set("a", "1").incr("a").get("a")
tx.exec()            # ["OK", 2, "2"]
```

### 명령어 메서드 나누기

`MiniRedis`와 `Transaction`이 같은 명령어 메서드(`set`, `incr`, ...)를 가져야 해요. 그래서 명령어 메서드를 `Commands`로 빼고 둘이 같이 물려받아요. 명령어 메서드는 지금처럼 `self.execute`를 부르기만 해요. `execute`가 무엇을 하는지만 달라요.

```python
class Commands:
    """명령어 메서드 모음. self.execute가 무엇을 하는지는 물려받는 클래스가 정해요."""
    def set(self, key, value):
        return self.execute("SET", key, value)
    def incr(self, key):
        return self.execute("INCR", key)
    # ... 나머지 명령어 메서드


class MiniRedis(Commands):
    def execute(self, command, *args):     # 지금 코드 그대로: 서버에 보내고 result 반환
        ...

    def multi(self):
        return Transaction(self)


class Transaction(Commands):
    def __init__(self, client):
        self.client = client
        self.commands = []

    def execute(self, command, *args):     # 보내지 않고 쌓기만 해요
        self.commands.append([command, *args])
        return self

    def exec(self):
        commands, self.commands = self.commands, []    # 성공·실패와 관계없이 큐를 비워요
        if not commands:
            return []                                  # 쌓인 게 없으면 요청하지 않아요
        results = self.client.execute("EXEC", *commands)
        return [r["result"] if r["ok"] else CommandError(r["error"]["code"], r["error"]["message"], None)
                for r in results]

    def discard(self):
        self.commands = []
```

### exec()의 결과와 예외

| 상황 | 동작 |
| --- | --- |
| 모두 성공 | 각 명령어의 `result`를 담은 list를 반환해요. |
| 일부 명령어가 실행 중 오류 | 예외를 던지지 않아요. list의 그 자리에 `CommandError` 객체가 들어 있어요. 나머지는 실행된 결과예요. |
| 검사 실패 (`EXEC_ABORTED`, `WRONG_ARGS`) | `CommandError`를 던져요. 아무것도 실행되지 않았어요. |
| 연결 실패, 시간 초과 | 일반 요청과 같이 `ServerUnavailableError`, `RequestTimeoutError`를 던져요. |

실행 중 오류를 예외로 던지면, 이미 실행된 다른 명령어의 결과를 받을 수 없어요. 그래서 list 안에 담아요. 쓰는 쪽은 `isinstance(x, CommandError)`로 확인해요. 시간 초과가 나면 서버에서 실행됐는지 알 수 없어요. 일반 요청과 같은 한계예요.

## CLI

redis-cli처럼 `MULTI`를 입력하면 큐 모드로 들어가요. 큐 모드에서는 프롬프트가 `mini-redis(TX)> `로 바뀌어요.

```
mini-redis> MULTI
OK
mini-redis(TX)> SET a 1
QUEUED
mini-redis(TX)> INCR a
QUEUED
mini-redis(TX)> EXEC
1) "OK"
2) (integer) 2
mini-redis>
```

| 입력 | 일반 모드 | 큐 모드 |
| --- | --- | --- |
| `MULTI` | `client.multi()`로 큐를 만들고 `OK` 출력 | `(error) MULTI 안에서 MULTI를 쓸 수 없어요` |
| `EXEC` | `(error) MULTI 없이 EXEC를 쓸 수 없어요` | `exec()` 결과를 번호를 붙여 출력하고 일반 모드로 돌아가요 |
| `DISCARD` | `(error) MULTI 없이 DISCARD를 쓸 수 없어요` | 큐를 비우고 `OK` 출력, 일반 모드로 돌아가요 |
| 그 밖의 명령어 | 지금처럼 바로 실행 | 큐에 쌓고 `QUEUED` 출력 |
| `exit`, Ctrl+C | 종료 | 쌓인 명령어는 버리고 종료 |

- `MULTI`, `EXEC`, `DISCARD`는 대소문자를 구분하지 않아요.
- 큐에 쌓을 때는 명령어를 검사하지 않아요. Phase 2에서 정한 대로 검사는 서버에 맡겨요. 틀린 명령어가 있으면 `EXEC`에서 `(error) EXEC_ABORTED ...`가 출력돼요.
- `EXEC` 결과에서 `CommandError` 항목은 `(error) 코드 메시지`로 출력해요. 다른 항목은 지금의 `format_result` 규칙을 따라요.
- `EXEC`가 오류로 끝나도 일반 모드로 돌아가요.

## 다음 설계로 넘기는 것

- **WATCH (R-50, optional)**: 서버가 연결 상태를 기억하지 않으므로, Redis처럼 `WATCH key`를 먼저 보내 두는 방식은 쓸 수 없어요. 대신 key마다 버전 번호를 두고(SET·DEL 등으로 바뀔 때마다 +1), 클라이언트가 확인한 버전을 EXEC 요청에 함께 보내는 방식을 검토해요. 서버는 EXEC 검사 단계에서 버전을 비교하고, 다르면 아무것도 실행하지 않아요.

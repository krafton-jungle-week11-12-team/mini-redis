# 클라이언트 · CLI 설계

이 문서를 읽으면 Python 클라이언트와 CLI가 서버에 어떻게 요청을 보내고 결과를 돌려주는지 알 수 있어요. 클래스·메서드·예외 구조와 CLI의 입력·출력 규칙을 그대로 따라 `mini_redis/client.py`와 `mini_redis/cli.py`를 구현할 수 있어요.

요구사항은 [Phase 2 요구사항 명세서](../../requirements/phase2/phase2_requirement.md)를 기준으로 해요. 서버는 바꾸지 않아요.

## 전체 흐름

```
사람 → cli.py: 입력 받기, 자르기 ─┐
                                  ├→ client.py: JSON 요청 → server.py (Phase 1 그대로)
웹 서버 등 Python 코드 ───────────┘   응답의 ok 확인 → result 반환 또는 예외
       ← cli.py: 결과 출력
```

- `client.py`는 HTTP 통신과 응답 해석만 맡아요. 화면 출력은 하지 않아요.
- `cli.py`는 입력과 출력만 맡아요. HTTP 요청은 직접 만들지 않고 `client.py`를 불러요.
- 둘 다 같은 Python 프로세스 안에서 실행돼요. 클라이언트를 따로 켜 두지 않아요.

## 결정 사항

| 항목 | 선택 | 이유 |
| --- | --- | --- |
| HTTP 라이브러리 | 표준 라이브러리 `urllib.request` | 서버처럼 표준 라이브러리만 써서, 사용하는 쪽에서 `pip install` 없이 바로 쓸 수 있어요. `requests`는 테스트용(`requirements-dev.txt`)으로만 남겨요. |
| 연결 방식 | 요청마다 새로 연결 | 서버가 HTTP/1.0으로 요청마다 연결을 끊어요. 연결을 재사용할 수 없어요. |
| 입력값 검사 | 서버에 맡김 (요청 본문 크기만 예외) | 규칙(key 길이, 문자열 여부)을 한 곳에서만 관리해요. 서버가 돌려준 오류 코드를 그대로 예외로 바꿔요. |
| `DEL` 메서드 이름 | `delete` | `del`은 Python 예약어라 메서드 이름으로 쓸 수 없어요. |
| `EXISTS` 반환값 | 서버 값 그대로 `1` / `0` | R-29. `bool`로 바꾸지 않아요. |
| 제한 시간 기본값 | 5초 | R-32 |

## 클라이언트 (`mini_redis/client.py`)

### MiniRedis

```python
class MiniRedis:
    def __init__(self, host="127.0.0.1", port=6380, timeout=5.0):   # R-26, R-32
        self.url = f"http://{host}:{port}/command"
        self.timeout = timeout
```

객체를 만들 때는 주소만 저장해요. 서버에 연결하지 않아서, 서버가 꺼져 있어도 객체는 만들어져요. 연결 실패는 첫 요청에서 알 수 있어요.

### execute: 범용 메서드 (R-28)

```python
def execute(self, command, *args):
    """명령어 이름과 인자를 그대로 서버에 보내고 result를 돌려줘요."""
```

1. `{"command": command, "args": list(args)}`를 JSON으로 만들고 UTF-8로 바꿔요.
2. 본문이 1MB를 넘으면 요청을 보내지 않고 `CommandError("VALUE_TOO_LARGE", ...)`를 던져요. ([요청 본문 크기 검사](#요청-본문-크기-검사) 참고)
3. `POST /command`로 보내요. `Content-Type: application/json`, `timeout=self.timeout`
4. 응답을 해석해요.

| 상황 | urllib 동작 | 클라이언트 동작 | 근거 |
| --- | --- | --- | --- |
| 200 응답 | 정상 반환 | `result`를 반환해요. GET에 값이 없으면 `None`이에요. | R-29 |
| 4xx, 5xx 응답 | `HTTPError` 발생. 본문은 `e.read()`로 읽을 수 있어요. | 본문의 `error.code`, `error.message`로 `CommandError`를 던져요. | R-30 |
| 응답 본문이 JSON이 아니거나 `error`가 없음 | - | `MiniRedisError("서버 응답을 해석할 수 없어요")`를 던져요. | - |
| 서버가 꺼져 있음, 주소가 틀림 | `URLError` (`reason`이 `ConnectionRefusedError` 등) | `ServerUnavailableError`를 던져요. | R-31 |
| 제한 시간 초과 | 연결 중이면 `URLError(reason=TimeoutError)`, 응답을 읽는 중이면 `TimeoutError` | `RequestTimeoutError`를 던져요. | R-32 |

`URLError`는 `reason`이 `TimeoutError`인지 먼저 확인해요. 아니면 연결 실패로 처리해요.

### 명령어 메서드 (R-27)

모두 `execute`를 부르기만 해요.

| 메서드 | 보내는 명령어 | 반환값 |
| --- | --- | --- |
| `ping()` | `PING` | `"PONG"` |
| `set(key, value)` | `SET key value` | `"OK"` |
| `get(key)` | `GET key` | value, 없으면 `None` |
| `delete(key)` | `DEL key` | `1` 또는 `0` |
| `exists(key)` | `EXISTS key` | `1` 또는 `0` |
| `dbsize()` | `DBSIZE` | 저장된 key 개수 |
| `info()` | `INFO` | `{"size", "capacity", "tombstones"}` dict |

서버에 명령어가 추가되면 여기에도 메서드를 추가해요. 추가하기 전에도 `execute("새명령어", ...)`로 바로 쓸 수 있어요.

### 예외

```
MiniRedisError                 모든 클라이언트 예외의 부모
├── CommandError               서버가 오류 응답을 줌. code, message, status 속성 (R-30)
├── ServerUnavailableError     서버에 연결할 수 없음 (R-31)
└── RequestTimeoutError        제한 시간 안에 응답이 없음 (R-32)
```

- 쓰는 쪽은 `except MiniRedisError`로 한 번에 잡거나, 필요한 것만 골라 잡아요.
- 파이썬 내장 `ConnectionError`, `TimeoutError`와 이름이 겹치지 않게 지었어요.

```python
try:
    r.set("k" * 100, "v")
except CommandError as e:
    print(e.code)      # "KEY_TOO_LONG"
    print(e.status)    # 400
```

### 요청 본문 크기 검사

서버는 1MB가 넘는 본문을 받으면 본문을 읽지 않고 `413 VALUE_TOO_LARGE`를 보낸 뒤 연결을 끊어요. 이때 클라이언트는 아직 본문을 보내는 중이라 413 응답을 읽지 못하고 `ConnectionResetError`를 받아요. 그대로 두면 "서버에 연결할 수 없음"으로 잘못 알려줘요.

그래서 클라이언트가 보내기 전에 본문 크기를 직접 확인하고, 서버와 같은 오류 코드 `VALUE_TOO_LARGE`로 `CommandError`를 던져요. 기준값은 `server.py`의 `MAX_BODY_BYTES`를 그대로 가져와 써요. `status`는 서버와 같은 `413`이에요.

## CLI (`mini_redis/cli.py`)

### 실행 (R-33)

```bash
python -m mini_redis.cli                          # 127.0.0.1:6380
python -m mini_redis.cli --host 192.168.0.5 --port 6380
```

옵션은 `argparse`로 읽고, 기본값은 서버 실행 옵션과 같아요. 시작할 때 서버에 연결을 확인하지 않아요. 서버가 꺼져 있으면 첫 명령어에서 오류를 출력해요.

### 입력 처리

```
mini-redis> SET msg "hello world"
```

1. 프롬프트 `mini-redis> `로 한 줄을 읽어요.
2. `shlex.split`으로 잘라요. 공백으로 나누고, 따옴표로 감싼 부분은 하나로 묶어요. (R-34, R-35) → `["SET", "msg", "hello world"]`
3. 빈 줄이면 아무것도 하지 않고 다음 입력을 받아요.
4. 첫 단어가 `exit` 또는 `quit`(대소문자 무관)이면 종료해요. (R-38)
5. 나머지는 `client.execute(첫 단어, *나머지)`로 보내요. 명령어 이름은 입력한 그대로 보내요. 대소문자는 서버가 구분하지 않아요.

| 상황 | 동작 | 근거 |
| --- | --- | --- |
| 따옴표가 닫히지 않음 (`shlex`의 `ValueError`) | `(error) 따옴표가 닫히지 않았어요`를 출력하고 다음 입력 | R-37 |
| Ctrl+C (`KeyboardInterrupt`), Ctrl+D (`EOFError`) | 줄을 바꾸고 종료 | R-38 |

### 출력 형식 (R-36)

| 결과 | 출력 | 예시 |
| --- | --- | --- |
| `None` | `(nil)` | `GET nothing` → `(nil)` |
| 문자열 | 큰따옴표로 감싸서 | `GET hello` → `"world"` |
| 정수 | `(integer) 숫자` | `EXISTS hello` → `(integer) 1` |
| dict | 한 줄에 `key: value` 하나씩 | `INFO` → `size: 1` / `capacity: 8` / `tombstones: 0` |
| `CommandError` | `(error) 코드 메시지` | `(error) WRONG_ARGS GET은 인자 1개가 필요해요` |
| `ServerUnavailableError`, `RequestTimeoutError` | `(error) 메시지` | `(error) 192.168.0.5:6380 서버에 연결할 수 없어요` |

- 문자열은 구분 없이 모두 큰따옴표로 감싸요. `SET`의 `"OK"`와 값이 `OK`인 `GET` 결과를 서버 응답만으로는 구분할 수 없어서, 규칙을 하나로 통일했어요.
- 오류를 출력한 뒤에도 종료하지 않고 다음 입력을 받아요. (R-37) 서버가 다시 켜지면 같은 CLI에서 이어서 쓸 수 있어요.

### 테스트하기 쉽게 나누기

```python
def parse_line(line):                 # 입력 한 줄 → ["SET", "msg", "hello world"] (빈 줄이면 [])
def format_result(result):            # 결과 값 → 출력할 문자열
def repl(client, input=input, output=print):   # 입력 반복. 테스트에서는 input, output을 바꿔 넣어요
def main():                           # argparse → MiniRedis 생성 → repl 실행
```

`parse_line`과 `format_result`는 서버 없이 테스트할 수 있어요. `repl`은 입력 목록을 넣고 출력 목록을 확인하는 방식으로 테스트해요.

## 요구사항 대응표

| 요구사항 | 설계 위치 |
| --- | --- |
| R-26 | [MiniRedis](#miniredis) |
| R-27 | [명령어 메서드](#명령어-메서드-r-27) |
| R-28 | [execute](#execute-범용-메서드-r-28) |
| R-29, R-30, R-31, R-32 | [execute](#execute-범용-메서드-r-28)의 응답 해석 표, [예외](#예외) |
| R-33 | [실행](#실행-r-33) |
| R-34, R-35, R-37, R-38 | [입력 처리](#입력-처리) |
| R-36, R-37 | [출력 형식](#출력-형식-r-36) |

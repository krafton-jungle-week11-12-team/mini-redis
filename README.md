# mini-Redis

HTTP로 명령을 주고받는 작은 Redis예요. 이 문서를 읽으면 mini-Redis 서버를 켜고, 같은 Wi-Fi의 다른 PC에서 `curl`로 `SET`/`GET` 같은 명령을 보낼 수 있어요. 서버를 여는 사람은 1번, 접속하는 사람은 2번부터 읽어요.

## 1. 서버 여는 사람

### Python 설치

Python 3.10 이상이 필요해요. 먼저 설치되어 있는지 확인해요.

```bash
python3 --version   # Windows는 python --version
```

버전이 3.10보다 낮거나 명령어를 찾을 수 없다면 Python을 설치해요.

| OS | 설치 방법 |
| --- | --- |
| macOS | `brew install python@3.12` |
| Ubuntu | `sudo apt install python3 python3-venv` |
| Windows | [python.org](https://www.python.org/downloads/)에서 설치 (설치 화면에서 "Add python.exe to PATH" 체크) |

### 가상환경 만들기

서버는 표준 라이브러리만 써서 이 단계를 건너뛰어도 실행돼요. 테스트를 돌리려면 필요해요.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows는 .venv\Scripts\activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt`는 테스트에 필요한 패키지(pytest, requests)예요. 가상환경을 활성화하면 아래 명령어에서 `python`이 `.venv`의 Python을 가리켜요.

### 서버 켜기

```bash
python -m mini_redis --host 0.0.0.0   # 다른 PC 접속 허용, Ctrl+C로 종료
```

- `--host`를 빼면 `127.0.0.1`로 켜져서 내 PC에서만 접속돼요.
- 포트는 기본 6380이에요. 바꾸려면 `--port 8100`처럼 지정해요.
  - 6379는 Docker나 brew로 띄운 진짜 Redis가 자주 쓰고, macOS에서 7000은 AirPlay 수신 모드가 써서 피했어요.
  - 포트가 사용 중이라고 나오면 어떤 프로그램이 쓰는지 확인해요. macOS는 `lsof -i :6380`, Windows는 `netstat -ano | findstr :6380`이에요.
- 내 IP를 확인해서 사용하는 사람에게 알려줘요.
  - macOS: `ipconfig getifaddr en0`
  - Windows: `ipconfig` → **무선 LAN 어댑터 Wi-Fi**의 IPv4 주소 (`vEthernet (WSL)` 항목은 아니에요)
- 인증 기능이 없어서 같은 네트워크의 누구나 데이터를 읽고 지울 수 있어요. 다 쓰면 서버를 꺼 주세요.

## 2. 서버 사용하는 사람

- 서버와 **같은 Wi-Fi**에 연결해요.
- 서버 IP를 받아서 아래 명령어의 `<서버 IP>` 자리에 넣어요.
- 명령은 `curl`로 `POST /command`에 JSON을 보내요.
  - Windows PowerShell 5.1에서는 `curl`이 `Invoke-WebRequest`의 별칭이라 요청이 실패할 수 있어요. `curl` 대신 `curl.exe`로 입력해요.

## 3. 연결 확인

```bash
curl -m 5 http://<서버 IP>:6380/health
```

응답이 오지 않고 `Connection timed out`이 나면 아래를 순서대로 확인해요.

1. 서버를 `--host 0.0.0.0`으로 켰나요?
2. 두 PC의 IP 앞부분이 같나요? (예: `172.21.69.x`) 다르면 서로 다른 네트워크예요.
3. 서버 PC의 방화벽이 막고 있지 않나요? 네트워크를 **개인**으로 바꾸는 것만으로는 안 될 수 있어요.
   - 가장 빠른 방법: 테스트하는 동안만 방화벽을 꺼요. 끝나면 꼭 다시 켜요.
     - Windows: 설정 → 개인 정보 및 보안 → Windows 보안 → 방화벽 및 네트워크 보호 → **개인 네트워크** → Microsoft Defender 방화벽 **끔**
     - macOS: 시스템 설정 → 네트워크 → 방화벽 **끔**
   - 방화벽을 켠 채로 쓰려면, Windows는 관리자 PowerShell에서 6380 포트만 열어요.
     ```powershell
     New-NetFirewallRule -DisplayName "mini-redis 6380" -Direction Inbound -Protocol TCP -LocalPort 6380 -Action Allow -Profile Private
     ```
   - macOS: 시스템 설정 → 네트워크 → 방화벽에서 Python의 들어오는 연결을 허용해요.
4. 그래도 안 되면 Wi-Fi가 기기끼리 통신을 막는 경우예요. 휴대폰 핫스팟에 둘 다 연결해서 다시 해봐요.

`ping`은 확인용으로 쓰지 않아요. Windows는 방화벽이 기본으로 ping을 막아서, 서버 연결이 되는데도 ping은 실패할 수 있어요.

## 4. 헬스체크

서버가 살아 있는지 확인해요.

```bash
curl http://<서버 IP>:6380/health
# {"ok": true, "result": "PONG", "error": null}
```

## 5. 명령어

요청 형식은 항상 같아요. 명령어 이름과 인자를 **따로** 넣어요.

```json
{"command": "SET", "args": ["key", "value"]}
```

- `command`: 실행할 명령어 이름이에요. 문자열로 입력해요. 대소문자는 구분하지 않아요. (예: `"SET"`)
- `args`: 명령어에 넘길 인자 목록이에요. 문자열 배열로 입력하고, 생략하면 빈 배열로 처리해요. (예: `["key", "value"]`)

### 기본 명령어

| 명령어 | args | 결과 |
| --- | --- | --- |
| `PING` | `[]` | `"PONG"` |
| `SET` | `["key", "value"]` | `"OK"` (같은 key면 덮어써요) |
| `GET` | `["key"]` | value, 없으면 `null` |
| `DEL` | `["key"]` | 지웠으면 `1`, 없으면 `0` |
| `EXISTS` | `["key"]` | 있으면 `1`, 없으면 `0` |
| `DBSIZE` | `[]` | 저장된 key 개수 |

### 디버깅 명령어

해시 테이블 상태를 확인하거나 테스트 중에 저장소를 비울 때 써요.

| 명령어 | args | 결과 |
| --- | --- | --- |
| `INFO` | `[]` | 저장소 상태 `{"size", "capacity", "tombstones"}` |
| `FLUSH` | `[]` | 모든 데이터를 지우고 지운 개수를 돌려줘요. 버킷 수도 처음(8개)으로 돌아가요 |

`INFO` 결과의 각 값은 아래와 같아요.

- `size`: 저장된 key 개수예요. `DBSIZE`와 같아요.
- `capacity`: 해시 테이블의 버킷 수예요. 처음엔 8이고, 가득 차기 전에 늘어나요.
- `tombstones`: `DEL`로 지운 뒤 남아 있는 삭제 표시 버킷 수예요. 테이블이 커지면 0으로 정리돼요.

> ⚠️ `FLUSH`는 서버의 모든 데이터를 지워요. 같은 서버를 쓰는 다른 사람의 데이터도 지워지니, 쓰기 전에 알려 주세요.

### 응답과 오류

응답은 모두 `{ok, result, error}` 형식이고, 실패하면 `error`에 `code`와 `message`가 담겨요.

| error.code | HTTP | 언제 |
| --- | --- | --- |
| `INVALID_REQUEST` | 400 | JSON이 아니거나, `command`가 없거나, `args`가 배열이 아닐 때 |
| `UNKNOWN_COMMAND` | 400 | 지원하지 않는 명령어일 때 |
| `WRONG_ARGS` | 400 | 인자 개수가 맞지 않을 때 |
| `WRONG_TYPE` | 400 | key나 value가 문자열이 아닐 때 (`null` 포함) |
| `KEY_TOO_LONG` | 400 | key의 UTF-8 길이가 99byte를 넘을 때 |
| `VALUE_TOO_LARGE` | 413 | 요청 본문이 1MB를 넘을 때 |
| `NOT_FOUND` | 404 | `/command`, `/health`가 아닌 경로일 때 |
| `STORE_FULL` | 507 | 저장소가 최대 크기에 도달해 더 저장할 수 없을 때 |

## 6. 사용 예시

```bash
curl -X POST http://<서버 IP>:6380/command -d '{"command": "SET", "args": ["hello", "world"]}'
# {"ok": true, "result": "OK", "error": null}

curl -X POST http://<서버 IP>:6380/command -d '{"command": "GET", "args": ["hello"]}'
# {"ok": true, "result": "world", "error": null}

curl -X POST http://<서버 IP>:6380/command -d '{"command": "EXISTS", "args": ["hello"]}'
# {"ok": true, "result": 1, "error": null}

curl -X POST http://<서버 IP>:6380/command -d '{"command": "DEL", "args": ["hello"]}'
# {"ok": true, "result": 1, "error": null}

curl -X POST http://<서버 IP>:6380/command -d '{"command": "DBSIZE", "args": []}'
# {"ok": true, "result": 0, "error": null}

# 디버깅 명령어
curl -X POST http://<서버 IP>:6380/command -d '{"command": "INFO", "args": []}'
# {"ok": true, "result": {"size": 0, "capacity": 8, "tombstones": 1}, "error": null}

curl -X POST http://<서버 IP>:6380/command -d '{"command": "FLUSH", "args": []}'
# {"ok": true, "result": 0, "error": null}   ← 지운 key 개수. 버킷 수와 tombstone도 처음으로 돌아가요
```

자주 하는 실수예요.

```bash
# ✗ 명령어와 인자를 한 문자열에 넣음 → UNKNOWN_COMMAND
-d '{"command": "SET hello world", "args": []}'

# ✗ 따옴표가 둥근 따옴표(“ ”)로 바뀜 → INVALID_REQUEST
#   Slack이나 메모 앱에서 복사하면 자주 바뀌어요. 코드 블록으로 공유해요.

# ✓ 이렇게 보내요
-d '{"command": "SET", "args": ["hello", "world"]}'
```

macOS 터미널에서 응답 끝에 붙는 `%`는 줄바꿈이 없다는 표시예요. 응답의 일부가 아니에요.

## 7. CLI로 쓰기

curl 대신 짧은 명령어로 쓸 수 있어요. 이 저장소 코드가 있는 PC에서 실행해요. CLI는 쓰는 동안만 실행하면 되지만, 접속할 **서버는 켜져 있어야 해요**.

```bash
python -m mini_redis.cli --host <서버 IP>     # --port를 빼면 6380
```

- CLI의 `--host`는 **접속할 서버의 IP**예요. 이 명령어로 내 서버가 다른 사람에게 열리지는 않아요.
- 다른 사람이 내 서버를 쓰게 하려면 서버를 `python -m mini_redis --host 0.0.0.0`으로 켜요. ([1. 서버 여는 사람](#1-서버-여는-사람) 참고)
- 내 PC에서 혼자 쓸 때는 한 터미널에서 `python -m mini_redis`로 서버를 켜고, 다른 터미널에서 `--host` 없이 `python -m mini_redis.cli`를 실행해요.

```
mini-redis> SET msg "hello world"
"OK"
mini-redis> GET msg
"hello world"
mini-redis> GET nothing
(nil)
mini-redis> EXISTS msg
(integer) 1
mini-redis> GET
(error) WRONG_ARGS GET은 인자 1개가 필요해요
mini-redis> exit
```

- 공백이 들어간 값은 따옴표로 감싸요.
- 오류가 나도 CLI는 끝나지 않아요. `exit`, `quit`, Ctrl+C, Ctrl+D로 끝내요.

## 8. Python 코드에서 쓰기

웹 서버 같은 Python 코드에서 쓸 때는 클라이언트를 `import`해요. 표준 라이브러리만 써서 따로 설치할 패키지가 없어요.

```python
from mini_redis.client import MiniRedis, CommandError

r = MiniRedis("<서버 IP>", 6380, timeout=5.0)   # timeout은 초 단위, 기본 5초
r.set("hello", "world")   # "OK"
r.get("hello")            # "world", 없으면 None
r.delete("hello")         # 1 (del은 Python 예약어라 delete예요)
r.exists("hello")         # 0
r.dbsize()                # 0

try:
    r.set("k" * 100, "v")
except CommandError as e:
    print(e.code)         # "KEY_TOO_LONG"
```

| 예외 | 언제 |
| --- | --- |
| `CommandError` | 서버가 오류 응답을 줬을 때. `code`, `message`, `status`가 담겨요 |
| `ServerUnavailableError` | 서버가 꺼져 있거나 주소가 틀렸을 때 |
| `RequestTimeoutError` | 제한 시간 안에 응답이 없을 때 |

세 예외 모두 `MiniRedisError`의 자식이라 한 번에 잡을 수도 있어요.

디버깅 명령어는 `r.info()`, `r.flush()`로 불러요. 목록에 없는 명령어는 `r.execute(command, *args)`로 보낼 수 있어요. `command`는 명령어 이름 문자열이고, `args`는 배열이 아니라 인자를 하나씩 따로 넘겨요. (예: `r.execute("SET", "hello", "world")`)

## 테스트

가상환경을 활성화하고 패키지를 설치한 상태에서 실행해요([가상환경 만들기](#가상환경-만들기) 참고).

```bash
pytest
```

# mini-Redis

## 요구사항
https://docs.google.com/spreadsheets/d/17CQ6UBq5Ho2LWllgFnT6q9Qj7cRPsojm0ODdX4UTb_8/edit?gid=0#gid=0

## 준비

### 1. Python 3.10 이상 설치

먼저 설치되어 있는지 확인해요.

```bash
python3 --version   # Windows는 python --version
```

버전이 3.10보다 낮거나 명령어를 찾을 수 없다면 Python을 설치해요.

| OS | 설치 방법 |
| --- | --- |
| macOS | `brew install python@3.12` |
| Ubuntu | `sudo apt install python3 python3-venv` |
| Windows | [python.org](https://www.python.org/downloads/)에서 설치 (설치 화면에서 "Add python.exe to PATH" 체크) |

### 2. 가상환경 만들고 패키지 설치

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows는 .venv\Scripts\activate
pip install -r requirements-dev.txt
```

서버는 표준 라이브러리만 사용해서 이 단계를 건너뛰어도 실행돼요. `requirements-dev.txt`는 테스트에 필요한 패키지(pytest, requests)예요.

가상환경을 활성화하면 아래 명령어에서 `python`이 `.venv`의 Python을 가리켜요.

## 서버 실행

```bash
python -m mini_redis                 # 127.0.0.1:6380에서 대기, Ctrl+C로 종료
python -m mini_redis --port 8100     # 포트 변경
python -m mini_redis --host 0.0.0.0  # 같은 네트워크의 다른 PC에서 접속 허용 (인증이 없으니 주의)
```

서버가 떠 있는지 먼저 헬스체크로 확인해요.

```bash
curl 127.0.0.1:6380/health
```

기본 포트는 6380이에요. 6379는 Docker나 brew로 띄운 진짜 Redis가 자주 쓰고, macOS에서 7000은 AirPlay 수신 모드가 써요. 포트가 사용 중이라고 나오면 `lsof -i :포트번호`로 어떤 프로그램이 쓰는지 확인해요.

## 요청과 응답

명령어는 `POST /command`에 JSON으로 보내요.

- `command`: 실행할 명령어 이름이에요. 문자열로 입력해요. 대소문자는 구분하지 않아요. (예: `"PING"`)
- `args`: 명령어에 넘길 인자 목록이에요. 배열로 입력하고, 생략하면 빈 배열로 처리해요. (예: `["key", "value"]`)

모든 응답은 `{ok, result, error}` 형식이에요.

- `ok`: 명령이 성공했는지 나타내요. `true` 또는 `false`예요.
- `result`: 성공했을 때의 결과 값이에요. 실패하면 `null`이에요. (예: `"PONG"`)
- `error`: 실패했을 때의 오류 정보예요. 성공하면 `null`이고, 실패하면 `code`와 `message`를 가진 객체예요.

```bash
curl -X POST 127.0.0.1:6380/command -d '{"command": "PING", "args": []}'
# {"ok": true, "result": "PONG", "error": null}

curl -X POST 127.0.0.1:6380/command -d '{"command": "FOO", "args": []}'
# {"ok": false, "result": null, "error": {"code": "UNKNOWN_COMMAND", "message": "FOO는 지원하지 않는 명령어예요"}}

curl 127.0.0.1:6380/health
```

`error.code`는 아래 중 하나예요.

| code | HTTP | 언제 |
| --- | --- | --- |
| `INVALID_REQUEST` | 400 | JSON이 아니거나, `command`가 없거나, `args`가 배열이 아닐 때 |
| `UNKNOWN_COMMAND` | 400 | 지원하지 않는 명령어일 때 |
| `WRONG_ARGS` | 400 | 인자 개수가 맞지 않을 때 |
| `VALUE_TOO_LARGE` | 413 | 요청 본문이 1MB를 넘을 때 |
| `NOT_FOUND` | 404 | `/command`, `/health`가 아닌 경로일 때 |

## 다른 PC에서 접속하기

같은 Wi-Fi에 있는 PC에서 접속할 수 있어요. 인증 기능이 없어서 같은 네트워크의 누구나 데이터를 읽고 지울 수 있으니, 확인이 끝나면 서버를 꺼 주세요.

1. 서버 PC에서 외부 접속을 받도록 켜요.
   ```bash
   python -m mini_redis --host 0.0.0.0
   ```
   macOS에서 네트워크 연결을 허용할지 물으면 허용해요.
2. 서버 PC의 IP를 확인해요. macOS는 `ipconfig getifaddr en0`, Windows는 `ipconfig`의 IPv4 주소예요.
3. 다른 PC에서 서버 IP로 요청해요.
   ```bash
   # macOS, Linux, PowerShell 7.3 이상
   curl -X POST http://<서버 IP>:6380/command -d '{"command": "PING", "args": []}'
   ```
   ```powershell
   # Windows PowerShell 5.1 (따옴표 처리 방식이 달라서 curl 대신 사용)
   $body = @{ command = "PING"; args = @() } | ConvertTo-Json
   Invoke-RestMethod -Method Post -Uri http://<서버 IP>:6380/command -Body $body
   ```

`INVALID_REQUEST`가 오면 따옴표가 둥근 따옴표(`“ ”`, `‘ ’`)로 바뀌지 않았는지 확인해요. Slack이나 메모 앱에서 명령어를 복사하면 자주 바뀌어요. 명령어는 코드 블록에 넣어 공유해요.

## 테스트

가상환경을 활성화하고 패키지를 설치한 상태에서 실행해요([준비](#준비) 참고).

```bash
pytest
```

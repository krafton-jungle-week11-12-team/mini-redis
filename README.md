# mini-Redis

HTTP로 명령을 주고받는 작은 Redis예요.

## 1. 서버 여는 사람

Python 3.10 이상만 있으면 돼요. 서버는 표준 라이브러리만 써요.

```bash
python -m mini_redis --host 0.0.0.0   # 다른 PC 접속 허용, Ctrl+C로 종료
```

- `--host`를 빼면 `127.0.0.1`로 켜져서 내 PC에서만 접속돼요.
- 포트는 기본 6380이에요. 바꾸려면 `--port 8100`처럼 지정해요.
- 내 IP를 확인해서 사용하는 사람에게 알려줘요.
  - macOS: `ipconfig getifaddr en0`
  - Windows: `ipconfig` → **무선 LAN 어댑터 Wi-Fi**의 IPv4 주소 (`vEthernet (WSL)` 항목은 아니에요)
- 인증 기능이 없어서 같은 네트워크의 누구나 데이터를 읽고 지울 수 있어요. 다 쓰면 서버를 꺼 주세요.

## 2. 서버 사용하는 사람

- 서버와 **같은 Wi-Fi**에 연결해요.
- 서버 IP를 받아서 아래 명령어의 `<서버 IP>` 자리에 넣어요.
- 명령은 `curl`로 `POST /command`에 JSON을 보내요.

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

| 명령어 | args | 결과 |
| --- | --- | --- |
| `PING` | `[]` | `"PONG"` |
| `SET` | `["key", "value"]` | `"OK"` (같은 key면 덮어써요) |
| `GET` | `["key"]` | value, 없으면 `null` |
| `DEL` | `["key"]` | 지웠으면 `1`, 없으면 `0` |
| `EXISTS` | `["key"]` | 있으면 `1`, 없으면 `0` |
| `DBSIZE` | `[]` | 저장된 key 개수 |
| `INFO` | `[]` | 저장소 상태 `{"size", "capacity", "tombstones"}` |

`INFO` 결과의 각 값은 아래와 같아요.

- `size`: 저장된 key 개수예요. `DBSIZE`와 같아요.
- `capacity`: 해시 테이블의 버킷 수예요. 처음엔 8이고, 가득 차기 전에 늘어나요.
- `tombstones`: `DEL`로 지운 뒤 남아 있는 삭제 표시 버킷 수예요. 테이블이 커지면 0으로 정리돼요.

명령어 이름은 대소문자를 구분하지 않아요. 응답은 모두 `{ok, result, error}` 형식이고, 실패하면 `error`에 `code`와 `message`가 담겨요.

| error.code | 언제 |
| --- | --- |
| `INVALID_REQUEST` | JSON 형식이 틀렸을 때 |
| `UNKNOWN_COMMAND` | 없는 명령어일 때 |
| `WRONG_ARGS` | 인자 개수가 틀렸을 때 |

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

curl -X POST http://<서버 IP>:6380/command -d '{"command": "INFO", "args": []}'
# {"ok": true, "result": {"size": 0, "capacity": 8, "tombstones": 1}, "error": null}
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

## 테스트

```bash
pip install -r requirements-dev.txt
pytest
```

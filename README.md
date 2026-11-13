# mini-Redis

## 요구사항
https://docs.google.com/spreadsheets/d/17CQ6UBq5Ho2LWllgFnT6q9Qj7cRPsojm0ODdX4UTb_8/edit?gid=0#gid=0

## 서버 실행

Python 3.10 이상이 필요해요. 서버는 표준 라이브러리만 써서 따로 설치할 패키지가 없어요.

```bash
python -m mini_redis                 # 127.0.0.1:6380에서 대기, Ctrl+C로 종료
python -m mini_redis --port 8100     # 포트 변경
python -m mini_redis --host 0.0.0.0  # 같은 네트워크의 다른 PC에서 접속 허용 (인증이 없으니 주의)
```

기본 포트는 6380이에요. 6379는 Docker나 brew로 띄운 진짜 Redis가 자주 쓰고, macOS에서 7000은 AirPlay 수신 모드가 써요. 포트가 사용 중이라고 나오면 `lsof -i :포트번호`로 어떤 프로그램이 쓰는지 확인해요.

명령어는 `POST /command`에 JSON으로 보내요. 모든 응답은 `{ok, result, error}` 형식이에요.

```bash
curl -X POST 127.0.0.1:6380/command -d '{"command": "PING", "args": []}'
# {"ok": true, "result": "PONG", "error": null}

curl 127.0.0.1:6380/health
```

## 테스트

```bash
pip install -r requirements-dev.txt
pytest
```

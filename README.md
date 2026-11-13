# mini-Redis

## 요구사항
https://docs.google.com/spreadsheets/d/17CQ6UBq5Ho2LWllgFnT6q9Qj7cRPsojm0ODdX4UTb_8/edit?gid=0#gid=0

## 서버 실행

Python 3.10 이상이 필요해요. 서버는 표준 라이브러리만 써서 따로 설치할 패키지가 없어요.

```bash
python -m mini_redis                 # 127.0.0.1:6379에서 대기, Ctrl+C로 종료
python -m mini_redis --port 7000     # 포트 변경
python -m mini_redis --host 0.0.0.0  # 같은 네트워크의 다른 PC에서 접속 허용 (인증이 없으니 주의)
```

명령어는 `POST /command`에 JSON으로 보내요. 모든 응답은 `{ok, result, error}` 형식이에요.

```bash
curl -X POST localhost:6379/command -d '{"command": "PING", "args": []}'
# {"ok": true, "result": "PONG", "error": null}

curl localhost:6379/health
```

## 테스트

```bash
pip install -r requirements-dev.txt
pytest
```

"""mini-redis 서버에 HTTP 요청을 보내는 Python 클라이언트. 표준 라이브러리만 써요.

    from mini_redis.client import MiniRedis
    r = MiniRedis("127.0.0.1", 6380)
    r.set("hello", "world")   # "OK"
    r.get("hello")            # "world"
"""

import json
import socket
import urllib.error
import urllib.request

from mini_redis.server import MAX_BODY_BYTES

# Python 3.9 이하에서는 socket.timeout이 TimeoutError의 자식이 아니라서 둘 다 잡아요.
TIMEOUT_ERRORS = (TimeoutError, socket.timeout)


class MiniRedisError(Exception):
    """모든 클라이언트 예외의 부모예요."""


class CommandError(MiniRedisError):
    """서버가 오류 응답을 줬어요. (R-30)"""

    def __init__(self, code, message, status):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class ServerUnavailableError(MiniRedisError):
    """서버에 연결할 수 없어요. (R-31)"""


class RequestTimeoutError(MiniRedisError):
    """제한 시간 안에 응답이 없어요. (R-32)"""


class MiniRedis:
    def __init__(self, host="127.0.0.1", port=6380, timeout=5.0):   # R-26, R-32
        self.address = f"{host}:{port}"
        self.url = f"http://{self.address}/command"
        self.timeout = timeout

    def execute(self, command, *args):
        """명령어 이름과 인자를 그대로 서버에 보내고 result를 돌려줘요. (R-28)"""
        body = json.dumps({"command": command, "args": list(args)}).encode("utf-8")
        # 서버는 1MB가 넘으면 본문을 읽지 않고 연결을 끊어서, 보내기 전에 직접 확인해요.
        if len(body) > MAX_BODY_BYTES:
            raise CommandError("VALUE_TOO_LARGE", "요청이 너무 커요", 413)

        request = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as res:
                payload = self._parse(res.read())
        except urllib.error.HTTPError as e:              # 4xx, 5xx: 본문에 오류 정보가 있어요
            payload = self._parse(e.read())
            error = payload.get("error") or {}
            if "code" not in error:
                raise MiniRedisError("서버 응답을 해석할 수 없어요")
            raise CommandError(error["code"], error.get("message", ""), e.code)
        except urllib.error.URLError as e:               # HTTPError의 부모라 뒤에서 잡아요
            if isinstance(e.reason, TIMEOUT_ERRORS):
                raise RequestTimeoutError(f"{self.address} 서버가 {self.timeout}초 안에 응답하지 않았어요")
            raise ServerUnavailableError(f"{self.address} 서버에 연결할 수 없어요 ({e.reason})")
        except TIMEOUT_ERRORS:                           # 응답을 읽는 중에 시간 초과
            raise RequestTimeoutError(f"{self.address} 서버가 {self.timeout}초 안에 응답하지 않았어요")
        except ConnectionError as e:                     # 연결 후 끊김
            raise ServerUnavailableError(f"{self.address} 서버와 연결이 끊겼어요 ({e})")

        return payload.get("result")                     # R-29

    @staticmethod
    def _parse(raw):
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MiniRedisError("서버 응답을 해석할 수 없어요")
        if not isinstance(payload, dict):
            raise MiniRedisError("서버 응답을 해석할 수 없어요")
        return payload

    # 명령어 메서드 (R-27). 모두 execute를 부르기만 해요.
    def ping(self):
        return self.execute("PING")

    def set(self, key, value):
        return self.execute("SET", key, value)

    def get(self, key):
        return self.execute("GET", key)

    def delete(self, key):              # del은 Python 예약어예요
        return self.execute("DEL", key)

    def exists(self, key):
        return self.execute("EXISTS", key)

    def dbsize(self):
        return self.execute("DBSIZE")

    def info(self):
        return self.execute("INFO")

    def flush(self):
        return self.execute("FLUSH")

    def getset(self, key, value):
        return self.execute("GETSET", key, value)

    def setnx(self, key, value):
        return self.execute("SETNX", key, value)

    def setxx(self, key, value):
        return self.execute("SETXX", key, value)

    def incr(self, key):
        return self.execute("INCR", key)

    def decr(self, key):
        return self.execute("DECR", key)

    def mset(self, mapping):
        """{"a": "1", "b": "2"} → MSET a 1 b 2"""
        args = [x for pair in mapping.items() for x in pair]
        return self.execute("MSET", *args)

    def mget(self, *keys):
        return self.execute("MGET", *keys)

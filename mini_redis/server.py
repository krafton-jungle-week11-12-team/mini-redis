"""HTTP 요청을 받아 dispatcher에 넘기고, 결과를 JSON으로 돌려주는 계층."""

import json
import signal
from http.server import BaseHTTPRequestHandler, HTTPServer

from mini_redis.dispatcher import execute, error_response

MAX_BODY_BYTES = 1024 * 1024  # 요청 본문 최대 1MB (R-24)


class CommandHandler(BaseHTTPRequestHandler):
    # 기본값 HTTP/1.0 유지: 요청마다 연결을 끊어서 단일 스레드가 막히지 않게 해요.

    def do_GET(self):
        if self.path == "/health":  # R-02: 서버 생존 확인
            self._send(200, {"ok": True, "result": "PONG", "error": None})
        else:
            self._send(404, error_response("NOT_FOUND", f"{self.path} 경로는 없어요"))

    def do_POST(self):
        if self.path != "/command":
            self._send(404, error_response("NOT_FOUND", f"{self.path} 경로는 없어요"))
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._send(413, error_response("VALUE_TOO_LARGE", "요청이 너무 커요"))
            return

        try:
            body = json.loads(self.rfile.read(length))
            command = body["command"]
            args = body.get("args", [])
            if not isinstance(command, str) or not isinstance(args, list):
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._send(400, error_response(
                "INVALID_REQUEST", '{"command": "SET", "args": ["key", "value"]} 형식으로 보내 주세요'))
            return

        status, payload = execute(command, args)
        self._send(status, payload)

    def _send(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        if self.server.verbose:
            super().log_message(format, *args)


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def run(host="127.0.0.1", port=6380, verbose=False):
    signal.signal(signal.SIGTERM, _raise_interrupt)  # kill, systemd 종료도 Ctrl+C처럼 처리
    try:
        server = HTTPServer((host, port), CommandHandler)  # 단일 스레드
    except OSError as e:
        raise SystemExit(f"{host}:{port} 에서 서버를 켤 수 없어요 ({e.strerror}). "
                         f"이미 켜진 서버가 있는지 확인하거나 --port로 다른 포트를 지정해 주세요.")
    server.verbose = verbose
    print(f"mini-redis 서버가 http://{host}:{port} 에서 대기 중이에요 (종료: Ctrl+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()  # R-01: 포트를 정리하고 종료
        print("mini-redis 서버를 종료했어요")

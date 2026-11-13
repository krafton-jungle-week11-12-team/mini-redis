"""기본 서버 동작 테스트 (R-01 ~ R-04). 테스트마다 빈 포트에 서버를 띄우고 끝나면 내려요."""

import socket
import subprocess
import sys
import time

import pytest
import requests


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def base_url():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "mini_redis", "--port", str(port)])
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            requests.get(f"{url}/health", timeout=0.2)
            break
        except requests.ConnectionError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(timeout=5)


def command(url, body):
    return requests.post(f"{url}/command", json=body, timeout=2)


def test_health(base_url):
    res = requests.get(f"{base_url}/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True, "result": "PONG", "error": None}


def test_ping_ignores_case(base_url):
    res = command(base_url, {"command": "ping", "args": []})
    assert res.json()["result"] == "PONG"


@pytest.mark.parametrize("body, code", [
    ({"command": "FOO", "args": []}, "UNKNOWN_COMMAND"),
    ({"command": "PING", "args": ["x"]}, "WRONG_ARGS"),
    ({"args": []}, "INVALID_REQUEST"),
    ({"command": "PING", "args": "x"}, "INVALID_REQUEST"),
])
def test_invalid_command(base_url, body, code):
    res = command(base_url, body)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == code


def test_invalid_json(base_url):
    res = requests.post(f"{base_url}/command", data="SET a 1")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_path(base_url):
    res = requests.get(f"{base_url}/nope")
    assert res.status_code == 404


def test_same_response_shape(base_url):
    ok = command(base_url, {"command": "PING", "args": []}).json()
    err = command(base_url, {"command": "FOO", "args": []}).json()
    assert ok.keys() == err.keys() == {"ok", "result", "error"}

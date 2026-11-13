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


MAX_BODY_BYTES = 1024 * 1024


def _set_body_of_size(size):
    """본문 전체가 정확히 size byte가 되도록 value 길이를 맞춘 SET 요청 본문이에요."""
    prefix = '{"command": "SET", "args": ["key1", "'
    suffix = '"]}'
    value = "a" * (size - len(prefix) - len(suffix))
    body = (prefix + value + suffix).encode("utf-8")
    assert len(body) == size
    return body


def _post_raw(url, body):
    return requests.post(f"{url}/command", data=body,
                         headers={"Content-Type": "application/json"}, timeout=5)


def test_val10_body_up_to_1mb_allowed(base_url):
    res = _post_raw(base_url, _set_body_of_size(MAX_BODY_BYTES))
    assert res.status_code == 200
    assert res.json()["result"] == "OK"


def test_val11_body_over_1mb_rejected(base_url):
    res = _post_raw(base_url, _set_body_of_size(MAX_BODY_BYTES + 1))
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "VALUE_TOO_LARGE"

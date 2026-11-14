"""여러 테스트 파일이 같이 쓰는 fixture예요."""

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


@pytest.fixture
def unused_port():
    """아무도 쓰지 않는 포트예요. 서버가 꺼져 있는 상황을 만들 때 써요."""
    return _free_port()

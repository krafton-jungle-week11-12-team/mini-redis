"""클라이언트 테스트 (CLT). 테스트마다 빈 포트에 서버를 띄우고 MiniRedis로 요청해요.
케이스 ID는 docs/test-cases/phase2/test-cases.md를 따라요."""

import pytest

from mini_redis.client import CommandError, MiniRedis, ServerUnavailableError


@pytest.fixture
def client(base_url):
    port = int(base_url.rsplit(":", 1)[1])
    return MiniRedis("127.0.0.1", port)


def test_clt01_set_then_get(client):
    assert client.set("k", "v") == "OK"
    assert client.get("k") == "v"


def test_clt02_get_missing_key_returns_none(client):
    assert client.get("nothing") is None


def test_clt03_error_response_raises_command_error(client):
    with pytest.raises(CommandError) as e:
        client.execute("GET")          # 인자 없음
    assert e.value.code == "WRONG_ARGS"
    assert e.value.status == 400


def test_clt04_server_down_raises_server_unavailable(unused_port):
    client = MiniRedis("127.0.0.1", unused_port)
    with pytest.raises(ServerUnavailableError):
        client.ping()

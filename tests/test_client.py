"""클라이언트 테스트 (CLT). 테스트마다 빈 포트에 서버를 띄우고 MiniRedis로 요청해요.
케이스 ID는 docs/test-cases/phase2/test-cases.md와 phase3/test-cases.md(CLT-08), phase4/test-cases.md(CLT-09)를 따라요."""

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


def test_clt08_mset_takes_dict_and_mget_returns_list(client):
    assert client.mset({"a": "1", "b": "2"}) == "OK"
    assert client.mget("a", "b", "c") == ["1", "2", None]


def test_clt09_set_with_ttl_and_ttl(client):
    assert client.set("k", "v", ttl=30) == "OK"     # 30을 "30"으로 보내요
    assert client.ttl("k") == 30                    # 남은 시간을 올림해서 1초 안에는 30이에요

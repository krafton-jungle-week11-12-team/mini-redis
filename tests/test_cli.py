"""CLI 테스트 (CMD). 서버 없이 함수만 불러요.
케이스 ID는 docs/test-cases/phase2/test-cases.md와 phase3/test-cases.md(CMD-06)를 따라요."""

import pytest

from mini_redis.cli import format_result, parse_line, repl
from mini_redis.client import CommandError


class FakeClient:
    """GET은 오류, PING은 PONG을 돌려주는 가짜 클라이언트예요."""

    def execute(self, command, *args):
        if command.upper() == "GET":
            raise CommandError("WRONG_ARGS", "GET은 인자 1개가 필요해요", 400)
        if command.upper() == "PING":
            return "PONG"
        raise AssertionError(f"예상하지 못한 명령어: {command}")


def test_cmd01_quoted_value_is_one_arg():
    assert parse_line('SET msg "hello world"') == ["SET", "msg", "hello world"]


@pytest.mark.parametrize("result, expected", [
    (None, "(nil)"),
    ("v", '"v"'),
    (1, "(integer) 1"),
])
def test_cmd02_format_result(result, expected):
    assert format_result(result) == expected


def test_cmd03_error_then_continue_then_exit():
    lines = iter(["GET", "PING", "exit"])
    out = []

    repl(FakeClient(), input=lambda prompt="": next(lines), output=out.append)

    assert out[0].startswith("(error) WRONG_ARGS")
    assert out[1] == '"PONG"'
    assert len(out) == 2                # exit 뒤에는 아무것도 출력하지 않고 끝나요


def test_cmd06_format_list_result_with_numbers():
    assert format_result(["1", None]) == '1) "1"\n2) (nil)'

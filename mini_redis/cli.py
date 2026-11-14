"""`python -m mini_redis.cli` 로 실행하는 대화형 CLI. HTTP 요청은 client.py에 맡겨요.

    $ python -m mini_redis.cli --host 127.0.0.1 --port 6380
    mini-redis> SET msg "hello world"
    "OK"
"""

import argparse
import json
import shlex

from mini_redis.client import CommandError, MiniRedis, MiniRedisError

PROMPT = "mini-redis> "
EXIT_WORDS = {"exit", "quit"}


def parse_line(line):
    """입력 한 줄을 명령어와 인자로 잘라요. 따옴표로 감싼 부분은 하나로 묶어요. (R-34, R-35)"""
    return shlex.split(line)


def format_result(result):
    """결과 값을 사람이 읽기 쉬운 문자열로 바꿔요. (R-36)"""
    if result is None:
        return "(nil)"
    if isinstance(result, bool):        # bool은 int의 자식이라 먼저 걸러요
        return json.dumps(result)
    if isinstance(result, int):
        return f"(integer) {result}"
    if isinstance(result, str):
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, dict):
        return "\n".join(f"{k}: {v}" for k, v in result.items())
    return str(result)


def repl(client, input=input, output=print):
    """입력을 반복해서 받아 실행해요. 오류가 나도 끝나지 않아요. (R-37)"""
    while True:
        try:
            line = input(PROMPT)
        except (EOFError, KeyboardInterrupt):           # Ctrl+D, Ctrl+C (R-38)
            output("")
            return

        try:
            words = parse_line(line)
        except ValueError:
            output("(error) 따옴표가 닫히지 않았어요")
            continue
        if not words:
            continue
        if words[0].lower() in EXIT_WORDS:              # R-38
            return

        try:
            output(format_result(client.execute(words[0], *words[1:])))
        except CommandError as e:
            output(f"(error) {e.code} {e.message}")
        except MiniRedisError as e:                     # 연결 실패, 시간 초과
            output(f"(error) {e}")


def main():
    parser = argparse.ArgumentParser(description="mini-redis CLI")
    parser.add_argument("--host", default="127.0.0.1", help="접속할 서버 주소")   # R-33
    parser.add_argument("--port", type=int, default=6380, help="접속할 서버 포트")
    args = parser.parse_args()
    repl(MiniRedis(args.host, args.port))


if __name__ == "__main__":
    main()

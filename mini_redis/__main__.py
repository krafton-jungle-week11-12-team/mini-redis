"""`python -m mini_redis` 로 서버를 켜는 진입점."""

import argparse

from mini_redis.server import run


def main():
    parser = argparse.ArgumentParser(description="mini-redis 서버")
    parser.add_argument("--host", default="127.0.0.1", help="외부 접속을 받으려면 0.0.0.0")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--verbose", action="store_true", help="요청 로그 출력")
    args = parser.parse_args()
    run(args.host, args.port, args.verbose)


if __name__ == "__main__":
    main()

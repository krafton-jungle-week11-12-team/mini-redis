"""명령어 이름을 보고 알맞은 함수를 실행하는 계층. HTTP를 몰라도 테스트할 수 있어요."""

import re
from collections import namedtuple

from mini_redis.store import (
    MAX_KEY_LEN,
    MAX_TTL,
    HashTable,
    IntegerOverflowError,
    NotIntegerError,
    StoreFullError,
)

store = HashTable()

# int()는 " 1", "+1", "1_000"도 받아들여서 직접 정해요. 앞자리 0("007")도 거부하고,
# 7자리 제한으로 아주 긴 숫자를 int()로 바꾸지 않아요. (R-52)
_TTL = re.compile(r"[1-9][0-9]{0,6}")


class InvalidTtlError(Exception):
    """SET의 TTL 인자가 형식이나 범위에 맞지 않을 때 던져요."""


def parse_ttl(arg):
    if not _TTL.fullmatch(arg) or int(arg) > MAX_TTL:
        raise InvalidTtlError
    return int(arg)


def ok_response(result):
    return {"ok": True, "result": result, "error": None}


def error_response(code, message):
    return {"ok": False, "result": None, "error": {"code": code, "message": message}}


def cmd_ping(args):
    return ok_response("PONG")


def cmd_set(args):
    ttl = parse_ttl(args[2]) if len(args) == 3 else None   # 저장 전에 검사해서 실패하면 저장 안 해요
    store.set(args[0], args[1], ttl)
    return ok_response("OK")


def cmd_get(args):
    return ok_response(store.get(args[0]))      # 없으면 None → null


def cmd_del(args):
    return ok_response(store.delete(args[0]))   # 1 또는 0


def cmd_exists(args):
    return ok_response(store.exists(args[0]))   # 1 또는 0


def cmd_ttl(args):
    return ok_response(store.ttl(args[0]))      # 남은 초, 만료 없음 -1, key 없음 -2


def cmd_dbsize(args):
    return ok_response(store.size)


def cmd_flush(args):
    return ok_response(store.flush())           # 지운 개수


def cmd_info(args):
    return ok_response({"size": store.size, "capacity": store.capacity, "tombstones": store.tombstones})


def cmd_getset(args):
    return ok_response(store.getset(args[0], args[1]))    # 이전 값, 없으면 None


def cmd_setnx(args):
    return ok_response(store.setnx(args[0], args[1]))     # 1 또는 0


def cmd_setxx(args):
    return ok_response(store.setxx(args[0], args[1]))     # 1 또는 0


def cmd_incr(args):
    return ok_response(store.incr_by(args[0], 1))


def cmd_decr(args):
    return ok_response(store.incr_by(args[0], -1))


def cmd_mset(args):
    store.mset(list(zip(args[0::2], args[1::2])))
    return ok_response("OK")


def cmd_mget(args):
    return ok_response(store.mget(args))


# 명령어 테이블: 이름 -> Command(함수, 최소 인자 수, 최대 인자 수, key 위치)
# key 위치에 있는 인자만 99byte 검사를 해요.
Command = namedtuple("Command", "func min_args max_args keys")

FIRST = slice(0, 1)          # 첫 번째 인자만 key. 인자가 없으면 빈 목록이라 검사를 그냥 통과해요
ALL = slice(None)            # 모든 인자가 key (MGET)
PAIRS = slice(0, None, 2)    # 0, 2, 4번째 인자가 key (MSET)

MAX_BATCH = 20               # MSET·MGET 한 번에 다루는 key 수

COMMANDS = {
    "PING":   Command(cmd_ping, 0, 0, FIRST),
    "SET":    Command(cmd_set, 2, 3, FIRST),    # 세 번째 인자는 TTL(초)이라 key가 아니에요
    "GET":    Command(cmd_get, 1, 1, FIRST),
    "DEL":    Command(cmd_del, 1, 1, FIRST),
    "EXISTS": Command(cmd_exists, 1, 1, FIRST),
    "DBSIZE": Command(cmd_dbsize, 0, 0, FIRST),
    "INFO":   Command(cmd_info, 0, 0, FIRST),
    "FLUSH":  Command(cmd_flush, 0, 0, FIRST),
    "GETSET": Command(cmd_getset, 2, 2, FIRST),
    "SETNX":  Command(cmd_setnx, 2, 2, FIRST),
    "SETXX":  Command(cmd_setxx, 2, 2, FIRST),
    "INCR":   Command(cmd_incr, 1, 1, FIRST),
    "DECR":   Command(cmd_decr, 1, 1, FIRST),
    "MSET":   Command(cmd_mset, 2, MAX_BATCH * 2, PAIRS),
    "MGET":   Command(cmd_mget, 1, MAX_BATCH, ALL),
    "TTL":    Command(cmd_ttl, 1, 1, FIRST),
}


def execute(command, args):
    """(HTTP 상태 코드, 응답 dict)를 돌려줘요.

    서버가 스레드 하나라서 execute 하나가 끝나야 다음 요청을 처리해요. 그래서 명령어 하나는
    중간에 다른 요청이 끼어들지 않아요. (R-41) ThreadingHTTPServer로 바꾸면 lock이 필요해요.
    """
    name = command.upper()
    if name not in COMMANDS:                                        # 1. 명령어
        return 400, error_response("UNKNOWN_COMMAND", f"{command}는 지원하지 않는 명령어예요")

    spec = COMMANDS[name]
    if not spec.min_args <= len(args) <= spec.max_args:             # 2. 인자 개수 (범위)
        return 400, error_response("WRONG_ARGS", f"{name}의 인자 개수가 맞지 않아요")
    if spec.keys is PAIRS and len(args) % 2:                        #    MSET은 짝수
        return 400, error_response("WRONG_ARGS", f"{name}은 key와 value를 짝지어 보내야 해요")

    if any(not isinstance(a, str) for a in args):                   # 3. 문자열 (R-11, R-25)
        return 400, error_response("WRONG_TYPE", "key와 value는 문자열이어야 해요")
    if any(len(k.encode("utf-8")) > MAX_KEY_LEN for k in args[spec.keys]):   # 4. 모든 key 길이 (R-23)
        return 400, error_response("KEY_TOO_LONG", f"key는 최대 {MAX_KEY_LEN}byte예요")

    try:
        return 200, spec.func(args)                                 # 5. 실행
    except InvalidTtlError:
        return 400, error_response("INVALID_TTL", f"TTL은 1 ~ {MAX_TTL} 사이의 정수예요")
    except StoreFullError:
        return 507, error_response("STORE_FULL", "저장소가 가득 찼어요")
    except NotIntegerError:
        return 400, error_response("NOT_INTEGER", "value가 정수가 아니에요")
    except IntegerOverflowError:
        return 400, error_response("INTEGER_OVERFLOW", "정수 범위를 넘어요")

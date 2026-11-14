"""명령어 이름을 보고 알맞은 함수를 실행하는 계층. HTTP를 몰라도 테스트할 수 있어요."""

from mini_redis.store import MAX_KEY_LEN, HashTable, StoreFullError

store = HashTable()


def ok_response(result):
    return {"ok": True, "result": result, "error": None}


def error_response(code, message):
    return {"ok": False, "result": None, "error": {"code": code, "message": message}}


def cmd_ping(args):
    return ok_response("PONG")


def cmd_set(args):
    store.set(args[0], args[1])
    return ok_response("OK")


def cmd_get(args):
    return ok_response(store.get(args[0]))      # 없으면 None → null


def cmd_del(args):
    return ok_response(store.delete(args[0]))   # 1 또는 0


def cmd_exists(args):
    return ok_response(store.exists(args[0]))   # 1 또는 0


def cmd_dbsize(args):
    return ok_response(store.size)


def cmd_flush(args):
    return ok_response(store.flush())           # 지운 개수


def cmd_info(args):
    return ok_response({"size": store.size, "capacity": store.capacity, "tombstones": store.tombstones})


# 명령어 테이블: 이름 -> (함수, 인자 개수)
COMMANDS = {
    "PING": (cmd_ping, 0),
    "SET": (cmd_set, 2),
    "GET": (cmd_get, 1),
    "DEL": (cmd_del, 1),
    "EXISTS": (cmd_exists, 1),
    "DBSIZE": (cmd_dbsize, 0),
    "INFO": (cmd_info, 0),
    "FLUSH": (cmd_flush, 0),
}


def execute(command, args):
    """(HTTP 상태 코드, 응답 dict)를 돌려줘요."""
    name = command.upper()
    if name not in COMMANDS:                                    # 1. 명령어
        return 400, error_response("UNKNOWN_COMMAND", f"{command}는 지원하지 않는 명령어예요")

    func, arity = COMMANDS[name]
    if len(args) != arity:                                      # 2. 인자 개수
        return 400, error_response("WRONG_ARGS", f"{name}은 인자 {arity}개가 필요해요")

    # Phase 1 명령어는 인자가 모두 문자열이고, 인자가 있으면 첫 번째가 key예요.
    if any(not isinstance(a, str) for a in args):               # 3. 문자열 (R-11, R-25)
        return 400, error_response("WRONG_TYPE", "key와 value는 문자열이어야 해요")
    if args and len(args[0].encode("utf-8")) > MAX_KEY_LEN:     # 4. key 길이 (R-23)
        return 400, error_response("KEY_TOO_LONG", f"key는 최대 {MAX_KEY_LEN}byte예요")

    try:
        return 200, func(args)                                  # 5. 실행
    except StoreFullError:
        return 507, error_response("STORE_FULL", "저장소가 가득 찼어요")

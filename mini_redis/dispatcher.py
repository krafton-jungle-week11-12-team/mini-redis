"""명령어 이름을 보고 알맞은 함수를 실행하는 계층. HTTP를 몰라도 테스트할 수 있어요."""


def ok_response(result):
    return {"ok": True, "result": result, "error": None}


def error_response(code, message):
    return {"ok": False, "result": None, "error": {"code": code, "message": message}}


def cmd_ping(args):
    return ok_response("PONG")


# 명령어 테이블: 이름 -> (함수, 인자 개수)
# 해시 테이블(store.py)이 준비되면 SET/GET/DEL/EXISTS/DBSIZE를 여기에 추가해요.
COMMANDS = {
    "PING": (cmd_ping, 0),
}


def execute(command, args):
    """(HTTP 상태 코드, 응답 dict)를 돌려줘요."""
    name = command.upper()
    if name not in COMMANDS:
        return 400, error_response("UNKNOWN_COMMAND", f"{command}는 지원하지 않는 명령어예요")

    func, arity = COMMANDS[name]
    if len(args) != arity:
        return 400, error_response("WRONG_ARGS", f"{name}은 인자 {arity}개가 필요해요")

    return 200, func(args)

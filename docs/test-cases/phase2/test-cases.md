# Phase 2 테스트 케이스

이 문서를 읽으면 Phase 2 클라이언트와 CLI를 어떤 케이스로 테스트하는지 확인할 수 있어요. 각 케이스의 준비·실행·기대 결과를 그대로 따라 테스트 코드를 작성할 수 있어요.

동작 기준은 [클라이언트 · CLI 설계](../../design/phase2/client.md)와 [Phase 2 요구사항 명세서](../../requirements/phase2/phase2_requirement.md)예요. 비고의 `R-xx`는 요구사항 번호예요.

## 한눈에 보기

- 전체 12개 중 **작성 전 7개**, **범위 밖 5개**예요.
- 클라이언트와 CLI는 서버 기능을 감싸는 도구라서, 요청을 제대로 보내고 응답을 제대로 바꾸는지만 확인해요. 명령어 하나하나의 동작은 Phase 1 테스트가 검증해요.
- 범위 밖은 이번 테스트에서 다루지 않는 케이스예요. 재현 비용이 크거나 다른 케이스로 충분히 확인되는 것들이에요.

## 테스트 방식

| 접두어 | 대상 | 방식 | 파일 |
| --- | --- | --- | --- |
| `CLT` | 클라이언트 | 테스트마다 빈 포트에 서버를 띄우고 `MiniRedis`로 요청해요. `tests/test_server.py`의 서버 fixture를 같이 써요. | `tests/test_client.py` |
| `CMD` | CLI | 서버 없이 `parse_line`, `format_result`, `repl` 함수를 바로 불러요. `repl`에는 가짜 클라이언트를 넣어요. | `tests/test_cli.py` |

## 클라이언트

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| CLT-01 | 저장 후 조회 | 서버 실행 | `set("k", "v")` → `get("k")` | `"OK"` → `"v"` | 작성 전 | R-26, R-27, R-29 |
| CLT-02 | 없는 key 조회 | 서버 실행 | `get("nothing")` | `None` | 작성 전 | R-29 |
| CLT-03 | 서버 오류 응답을 예외로 바꿈 | 서버 실행 | `execute("GET")` (인자 없음) | `CommandError`, `code == "WRONG_ARGS"`, `status == 400` | 작성 전 | R-28, R-30 |
| CLT-04 | 서버가 꺼져 있음 | 아무도 쓰지 않는 포트 | `ping()` | `ServerUnavailableError` | 작성 전 | R-31 |
| CLT-05 | 제한 시간 초과 | — | — | `RequestTimeoutError` | 범위 밖 | R-32. 응답이 늦는 서버를 따로 만들어야 해요 |
| CLT-06 | 요청 본문 1MB 초과 | — | — | `CommandError`, `code == "VALUE_TOO_LARGE"` | 범위 밖 | 1MB가 넘는 데이터를 만들어야 해서 무거워요. 코드 리뷰로 확인해요 |
| CLT-07 | 명령어 메서드별 동작 | — | — | — | 범위 밖 | `delete`, `exists`, `dbsize`, `info`, `flush`는 `execute`를 부르기만 해요. CLT-01, CLT-03으로 충분해요 |

## CLI

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| CMD-01 | 따옴표로 감싼 값을 하나로 자름 | — | `parse_line('SET msg "hello world"')` | `["SET", "msg", "hello world"]` | 작성 전 | R-34, R-35 |
| CMD-02 | 결과를 읽기 쉬운 형태로 출력 | — | `format_result(None)`, `format_result("v")`, `format_result(1)` | `(nil)`, `"v"`, `(integer) 1` | 작성 전 | R-36 |
| CMD-03 | 오류가 나도 계속 받고, exit로 종료 | 가짜 클라이언트: `GET`은 `CommandError("WRONG_ARGS", ...)`, `PING`은 `"PONG"` | `repl`에 입력 `["GET", "PING", "exit"]` | 출력 `(error) WRONG_ARGS ...` → `"PONG"`, `repl`이 정상 종료 | 작성 전 | R-37, R-38 |
| CMD-04 | Ctrl+C, Ctrl+D로 종료 | — | — | — | 범위 밖 | R-38. 직접 실행해서 확인해요 |
| CMD-05 | dict 결과 출력 (INFO) | — | — | — | 범위 밖 | 필요하면 CMD-02에 추가해요 |

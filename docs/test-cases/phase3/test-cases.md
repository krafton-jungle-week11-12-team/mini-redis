# Phase 3 테스트 케이스

이 문서를 읽으면 Phase 3에서 추가한 원자적 명령어(GETSET, SETNX, SETXX, INCR, DECR, MSET, MGET)와 공통 함수가 어떤 상황에서 어떻게 동작해야 하는지 케이스별로 확인할 수 있어요. 각 케이스의 준비·실행·기대 결과를 그대로 따라 테스트 코드를 작성할 수 있어요.

동작 기준은 [원자적 명령어 설계](../../design/phase3/atomic-commands.md)와 [Phase 3 요구사항 명세서](../../requirements/phase3/phase3_requirement.md)예요. 비고의 `R-xx`는 요구사항 번호예요.

## 한눈에 보기

- 전체 51개 중 **작성 완료 46개**, **작성 전 5개**예요.
- 작성 전 5개(MST-03, MST-06 ~ MST-08, MGT-05)는 MSET·MGET의 "전부 아니면 전무"와 "모든 key 검사"를 확인하는 케이스예요.
- 명령어마다 정상 동작과 함께 **확장이 언제 일어나고 언제 일어나지 않는지**를 확인해요. 조건을 먼저 보고 저장이 확실할 때만 확장하는 것이 Phase 3 설계의 핵심이라서예요.
- 트랜잭션(R-49, R-50)과 스크립트(R-40)는 설계가 아직 없어서 이 문서에서 다루지 않아요.

## 테스트 방식

| 접두어 | 대상 | 방식 | 파일 |
| --- | --- | --- | --- |
| `MST` `MGT` `GTS` `SNX` `SXX` `INC` `DEC` `ARG` | 명령어 | HTTP 없이 `dispatcher.execute`를 바로 불러요. 테스트마다 빈 저장소로 시작해요. | `tests/test_dispatcher.py` |
| `ENS` `WRT` `REG` | 공통 함수 | `HashTable`의 `_ensure_capacity`, `_write`를 바로 불러요. 해시값은 Phase 1의 `fix_hash` fixture로 고정해요. | `tests/test_store.py` |
| `ATM` | 원자성 | 빈 포트에 서버를 띄우고 여러 스레드에서 `MiniRedis`로 요청해요. | `tests/test_server.py` |
| `CLT` | 클라이언트 | Phase 2와 같이 서버를 띄우고 `MiniRedis`로 요청해요. | `tests/test_client.py` |
| `CMD` | CLI | 서버 없이 `format_result`를 바로 불러요. | `tests/test_cli.py` |

## 표기법

`fill N`, `col N`, `A → B`, `CODE (status)`, `tombstones`, `dbsize`, `capacity`는 [Phase 1 표기법](../phase1/test-cases.md#표기법)과 같아요. 따로 적지 않으면 버킷은 처음 크기인 8칸(`capacity == 8`)에서 시작해요. Phase 3에서 새로 쓰는 표기는 아래와 같아요.

| 표기 | 뜻 | 예시 |
| --- | --- | --- |
| `info` | INFO 결과의 `size`, `capacity`, `tombstones`를 확인해요. | `info` → `capacity == 16` |
| `key1 (hash 1)` | `key1`의 홈 버킷을 1번으로 고정해요. | `_write(None, 1, key1, val1)` |
| `INT64_MAX`, `INT64_MIN` | 64비트 정수의 최댓값 `"9223372036854775807"`, 최솟값 `"-9223372036854775808"`을 문자열로 저장해요. | `set key1 INT64_MAX` |
| `INT64_MAX+1` | `"9223372036854775808"`. 정수 형식이지만 범위 밖이에요. | `set key1 INT64_MAX+1` |
| `MAX_CAPACITY` | 버킷 수 상한 `1 << 20`이에요. | `_ensure_capacity(MAX_CAPACITY)` |
| `("k" × 100)` | `"k"`를 100번 이어 붙인 100byte key예요. | `mget key1 ("k" × 100)` |
| `MAX_CAPACITY`를 8로 patch | `monkeypatch`로 `store.MAX_CAPACITY`를 8로 바꿔 더 확장할 수 없게 만들어요. | MST-08 |
| `key1 … key21` | `key1`부터 `key21`까지 21개를 차례로 넣어요. | `mget key1 … key21` |
| `A / B / C` | 같은 기대 결과를 갖는 입력 여러 개예요. 각각 따로 실행해요. | `set key1 " 1" / "+1"` |

## MSET

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| MST-01 | 여러 key를 한 번에 저장 | — | mset key1 val1 key2 val2 → get key1 → get key2 | OK → val1 → val2 | 작성 완료 | R-42 |
| MST-02 | 넣을 개수만큼 미리 확장 | fill 6 | mset key7 val7 key8 val8 key9 val9 → info | size == 9, tombstones == 0, capacity == 16 | 작성 완료 | R-42. `_ensure_capacity(3)`을 한 번 불러서 (6 + 3) / 8 > 0.75 → 16으로 확장해요. 저장 중간에는 확장하지 않아요 |
| MST-03 | 인자 개수가 홀수면 아무것도 저장 안 함 | — | mset key1 val1 key2 → dbsize | WRONG_ARGS (400), 0 | 작성 전 | R-42. key와 value가 짝이 맞는지 저장 전에 검사해요 |
| MST-04 | 기존 key는 덮어씀 | set key1 old | mset key1 new key2 val2 → get key1 → dbsize | new, 2 | 작성 완료 | R-42, R-14 |
| MST-05 | 같은 key가 여러 번 오면 마지막 값 | — | mset key1 a key1 b → get key1 → dbsize | b, 1 | 작성 완료 | R-42. 앞에서부터 차례로 저장해요 |
| MST-06 | 뒤쪽 key가 99byte를 넘으면 아무것도 저장 안 함 | — | mset key1 val1 ("k" × 100) val2 → dbsize | KEY_TOO_LONG (400), 0 | 작성 전 | R-42, R-23. 첫 번째 key만이 아니라 모든 key를 검사해요 |
| MST-07 | 뒤쪽 value가 문자열이 아니면 아무것도 저장 안 함 | — | mset key1 val1 key2 123 → dbsize | WRONG_TYPE (400), 0 | 작성 전 | R-42, R-25 |
| MST-08 | 확장할 수 없으면 아무것도 저장 안 함 | `MAX_CAPACITY`를 8로 patch → fill 3 | mset key4 val4 key5 val5 key6 val6 key7 val7 → dbsize → get key4 | STORE_FULL (507), 3, nil | 작성 전 | R-42. (3 + 4) / 8 > 0.75인데 16은 상한을 넘어요. 저장 전에 `_ensure_capacity`가 실패해요 |
| MST-09 | key 20개 초과 | — | mset key1 val1 … key21 val21 | WRONG_ARGS (400) | 작성 완료 | R-42. 인자 42개 > `max_args` 40 (`MAX_BATCH * 2`) |

## MGET

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| MGT-01 | 여러 key를 한 번에 조회 | fill 3 | mget key1 key2 key3 | [val1, val2, val3] | 작성 완료 | R-43 |
| MGT-02 | 없는 key는 nil | fill 3 | mget key1 key2 key4 | [val1, val2, nil] | 작성 완료 | R-43 |
| MGT-03 | 요청한 순서 그대로, 중복 허용 | fill 2 | mget key2 key1 key2 | [val2, val1, val2] | 작성 완료 | R-43 |
| MGT-04 | key 20개 초과 | — | mget key1 … key21 | WRONG_ARGS (400) | 작성 완료 | R-43. 인자 21개 > `max_args` 20 (`MAX_BATCH`) |
| MGT-05 | 뒤쪽 key가 99byte를 넘으면 오류 | — | mget key1 ("k" × 100) | KEY_TOO_LONG (400) | 작성 전 | R-43, R-23. 모든 key를 검사해요 |

## GETSET

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| GTS-01 | 없는 key면 nil을 반환하고 저장 | — | getset key1 val1 → get key1 | nil → val1 | 작성 완료 | R-39 |
| GTS-02 | 저장 전 값을 반환 | set key1 0 | getset key1 1 → get key1 | "0" → "1" | 작성 완료 | R-39 |
| GTS-03 | 경계에서 확장 | fill 6 | getset key7 val7 → info | nil, capacity == 16 | 작성 완료 | R-39. 탐사 전에 `_ensure_capacity(1)`을 먼저 불러요 |

## SETNX

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| SNX-01 | 없는 key면 저장 | — | setnx key1 val1 → get key1 | 1 → val1 | 작성 완료 | R-44 |
| SNX-02 | 있는 key면 저장 안 함 | set key1 val1 | setnx key1 val2 → get key1 | 0 → val1 | 작성 완료 | R-44 |
| SNX-03 | 실패하면 확장하지 않음 | fill 6 | setnx key6 x → info | 0, capacity == 8 | 작성 완료 | R-44. 조건을 먼저 보고 저장이 확실할 때만 확장해요. 같은 상황에서 SET은 확장해요 (Phase 1 EXP-03) |
| SNX-04 | 새 key는 경계에서 확장 후 저장 | fill 6 | setnx key7 val7 → get key7 → info | 1 → val7, capacity == 16 | 작성 완료 | R-44. 확장 뒤 `_probe`를 다시 불러서 바뀐 자리에 저장해요 |

## SETXX

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| SXX-01 | 없는 key면 저장 안 함 | — | setxx key1 val1 → get key1 → dbsize | 0 → nil → 0 | 작성 완료 | R-45 |
| SXX-02 | 있는 key면 덮어씀 | set key1 val1 | setxx key1 val2 → get key1 | 1 → val2 | 작성 완료 | R-45 |
| SXX-03 | 경계에서도 확장하지 않음 | fill 6 | setxx key6 new → info | 1, capacity == 8 | 작성 완료 | R-45. 덮어쓰기만 해서 `_ensure_capacity`를 부르지 않아요 |

## INCR

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| INC-01 | 정수에 1을 더함 | set key1 1 | incr key1 → get key1 | 2 → "2" | 작성 완료 | R-47. 응답은 정수, 저장은 문자열이에요 |
| INC-02 | 없는 key는 0으로 봄 | — | incr key1 → get key1 | 1 → "1" | 작성 완료 | R-47 |
| INC-03 | 음수도 계산 | set key1 -5 | incr key1 | -4 | 작성 완료 | R-47 |
| INC-04 | 정수가 아니면 오류, 값은 그대로 | set key1 string | incr key1 → get key1 | NOT_INTEGER (400) → string | 작성 완료 | R-46 |
| INC-05 | 정수 형식이 아닌 값 | set key1 " 1" / "+1" / "1_000" / "1\n" / "1.5" / "" | incr key1 | NOT_INTEGER (400) | 작성 완료 | R-46. `re.fullmatch(r"-?[0-9]+")`로 판정해요. `int()`는 `" 1"`, `"+1"`, `"1_000"`을 받아들이고, `$`는 `"1\n"`을 통과시켜요 |
| INC-06 | 결과가 범위를 넘으면 오류, 값은 그대로 | set key1 INT64_MAX | incr key1 → get key1 | INTEGER_OVERFLOW (400) → INT64_MAX | 작성 완료 | R-46. 범위 검사는 저장 전에 해요 |
| INC-07 | 저장된 값이 이미 범위 밖 | set key1 INT64_MAX+1 | incr key1 | NOT_INTEGER (400) | 작성 완료 | R-46. 형식이 맞아도 범위 밖이면 정수가 아니라고 봐요 |
| INC-08 | 새 key는 경계에서 확장 | fill 6 | incr counter → info | 1, capacity == 16 | 작성 완료 | R-47 |
| INC-09 | 기존 key는 경계에서도 확장하지 않음 | fill 5 → set num 1 | incr num → info | 2, capacity == 8 | 작성 완료 | R-47. 기존 버킷을 덮어쓰기만 해요. 같은 상황에서 SET은 확장해요 (Phase 1 EXP-03) |

## DECR

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| DEC-01 | 정수에서 1을 뺌 | set key1 1 | decr key1 → get key1 | 0 → "0" | 작성 완료 | R-48 |
| DEC-02 | 없는 key는 0으로 봄 | — | decr key1 | -1 | 작성 완료 | R-48 |
| DEC-03 | 정수가 아니면 오류 | set key1 string | decr key1 | NOT_INTEGER (400) | 작성 완료 | R-46, R-48 |
| DEC-04 | 결과가 범위를 넘으면 오류 | set key1 INT64_MIN | decr key1 | INTEGER_OVERFLOW (400) | 작성 완료 | R-46, R-48 |

INCR과 DECR은 `incr_by(key, delta)` 하나를 함께 써요. 그래서 DECR은 부호가 반대인 경우만 확인하고, 정수 형식 판정이나 확장 동작은 INC 케이스로 확인해요.

## _ensure_capacity

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| ENS-01 | 75% 이하면 확장 안 함 | — | _ensure_capacity(6) → info | capacity == 8 | 작성 완료 | 6 / 8 = 0.75 |
| ENS-02 | 75% 초과면 확장 | — | _ensure_capacity(7) → info | capacity == 16 | 작성 완료 | 7 / 8 > 0.75 |
| ENS-03 | tombstone도 세고, 확장하면 tombstone 제거 | fill 6 → del key1 | _ensure_capacity(1) → info | capacity == 16, tombstones == 0, size == 5 | 작성 완료 | R-07, R-22. (5 + 1 + 1) / 8 > 0.75 |
| ENS-04 | 2배로 부족하면 여러 번 늘림 | — | _ensure_capacity(20) → info | capacity == 32 | 작성 완료 | 20 / 16 > 0.75라서 한 번 더 늘려요. 20 / 32 ≤ 0.75 |
| ENS-05 | MAX_CAPACITY를 넘으면 오류, 아무것도 안 바뀜 | fill 3 | _ensure_capacity(MAX_CAPACITY) → info | StoreFullError, capacity == 8, size == 3 | 작성 완료 | 크기를 먼저 계산하고 `_resize` 전에 오류를 던져요 |

## _write

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| WRT-01 | EMPTY 자리에 새로 씀 | key1 (hash 1) | _write(None, 1, key1, val1) → get key1 → info | val1, size == 1, tombstones == 0, capacity == 8 | 작성 완료 | `_write`는 확장하지 않아요 |
| WRT-02 | OCCUPIED 자리를 덮어씀 | key1 (hash 1) → set key1 val1 | _write(1, 1, key1, val2) → get key1 → info | val2, size == 1, tombstones == 0 | 작성 완료 | 덮어쓰기는 개수가 바뀌지 않아요 |
| WRT-03 | TOMBSTONE 자리에 씀 | col 2 → del key1 | _write(None, 1, key1, val1) → get key1 → info | val1, size == 2, tombstones == 0 | 작성 완료 | `tombstones`를 1 줄이고 `size`를 1 늘려요 |

## 회귀

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| REG-01 | SET을 공통 함수로 바꿔도 Phase 1과 같게 동작 | — | Phase 1 tests/test_store.py 전체 | 모두 통과 | 작성 완료 | `_ensure_capacity(1)`은 Phase 1의 `+1` 확인과 같아요. 확장 테스트(EXP)가 특히 중요해요 |

## 인자 검사

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| ARG-01 | 인자 개수 불일치 | — | getset key1 / setnx key1 / setxx key1 / incr / decr key1 key2 / mset / mget | 모두 WRONG_ARGS (400) | 작성 완료 | `min_args`, `max_args` 범위로 검사해요 |
| ARG-02 | 문자열이 아닌 인자 | — | getset key1 123 / setnx key1 null / setxx 123 val1 | 모두 WRONG_TYPE (400) | 작성 완료 | R-25 |

## 원자성

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| ATM-01 | INCR를 동시에 보내도 빠지는 증가 없음 | 서버 실행 | 스레드 10개가 incr counter를 10번씩 → get counter | "100" | 작성 완료 | R-41, R-47. 서버가 요청을 하나씩 처리해서 읽기와 쓰기 사이에 다른 요청이 끼어들지 않아요 |

## 클라이언트 · CLI

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| CLT-08 | mset은 dict, mget은 list | 서버 실행 | `mset({"a": "1", "b": "2"})` → `mget("a", "b", "c")` | `"OK"` → `["1", "2", None]` | 작성 완료 | R-42, R-43. 나머지 새 메서드는 `execute`를 부르기만 해서 Phase 2 CLT-07과 같은 이유로 따로 확인하지 않아요 |
| CMD-06 | list 결과를 번호 붙여 출력 | — | `format_result(["1", None])` | `1) "1"` / `2) (nil)` (두 줄) | 작성 완료 | 각 항목은 Phase 2 출력 규칙(CMD-02)을 따라요 |

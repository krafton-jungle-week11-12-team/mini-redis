# Phase 4 테스트 케이스

이 문서를 읽으면 Phase 4에서 추가한 만료(TTL)가 어떤 상황에서 어떻게 동작해야 하는지 케이스별로 확인할 수 있어요. 각 케이스의 준비·실행·기대 결과를 그대로 따라 테스트 코드를 작성할 수 있어요.

동작 기준은 [만료 설계](../../design/phase4/expiration.md)와 [Phase 4 요구사항 명세서](../../requirements/phase4/phase4_requirement.md)예요. 비고의 `R-xx`는 요구사항 번호예요.

## 한눈에 보기

- 전체 24개이고 모두 **작성 전**이에요.
- 요구사항마다 동작을 가르는 경계만 골랐어요. 같은 코드 경로를 지나는 입력은 `A / B / C`로 한 케이스에 묶었어요.
- 시간은 가짜 시계로 건너뛰어요. 테스트가 실제로 기다리지 않아요.
- 만료 청소기(R-71 ~ R-80)는 2차 범위라서 다루지 않아요. 만료 시각 형식(R-54)은 설계에서 `time.monotonic` 기준 초로 바꾸자고 제안해서, 날짜 문자열 형식은 확인하지 않아요.

## 테스트 방식

| 접두어 | 대상 | 방식 | 파일 |
| --- | --- | --- | --- |
| `STL` `LZY` `OVW` `TTL` `DBS` `REG` | 명령어 | HTTP 없이 `dispatcher.execute`를 바로 불러요. 테스트마다 가짜 시계를 넣은 빈 저장소로 시작해요. (LZY-02 제외) | `tests/test_dispatcher.py` |
| `LZY-02` `CLN` | 탐사·확장 전 정리 | `HashTable`을 바로 불러요. 해시값은 Phase 1의 `fix_hash` fixture로 고정해요. | `tests/test_store.py` |
| `CLT` | 클라이언트 | Phase 2와 같이 서버를 띄우고 `MiniRedis`로 요청해요. 실제 시계를 써요. | `tests/test_client.py` |

가짜 시계는 `now` 값을 들고 있는 객체예요. 저장소를 `HashTable(clock=lambda: clock.now)`로 만들고, 테스트에서 `clock.now`를 바꿔 시간을 옮겨요. (예: `clock.now = 10`)

## 표기법

`fill N`, `col N`, `A → B`, `CODE (status)`, `tombstones`, `dbsize`, `capacity`는 [Phase 1 표기법](../phase1/test-cases.md#표기법)과 같고, `info`, `A / B / C`, `MAX_CAPACITY`를 8로 patch는 [Phase 3 표기법](../phase3/test-cases.md#표기법)과 같아요. 따로 적지 않으면 버킷은 8칸(`capacity == 8`)에서, 시계는 `now 0`에서 시작해요. Phase 4에서 새로 쓰는 표기는 아래와 같아요.

| 표기 | 뜻 | 예시 |
| --- | --- | --- |
| `now T` | 가짜 시계를 T초로 옮겨요. 이후 명령어는 이 시각에 실행돼요. | `now 10` → `clock.now = 10` |
| `set key value T` | TTL T초로 저장해요. | `set key1 val1 10` |
| `(keyA ~ keyB TTL T)` | 앞의 `fill`이나 `col`에서 keyA ~ keyB만 TTL T초로 저장해요. 나머지는 TTL 없이 저장해요. | `fill 6 (key1 ~ key3 TTL 10)` → `set key1 val1 10`, …, `set key3 val3 10`, `set key4 val4`, …, `set key6 val6` |

## SET TTL 지정

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| STL-01 | 만료 시각 직전까지 조회되고, 그 시각부터 없음 | set key1 val1 10 | now 9.999 → get key1 → now 10 → get key1 | val1 → nil | 작성 전 | R-51, R-53, R-59. `now >= expire_at`이면 만료예요 |
| STL-02 | TTL을 다시 지정하면 새 시간으로 바뀜 | set key1 val1 10 | set key1 val1 100 → now 50 → ttl key1 | OK → 50 | 작성 전 | R-55 |
| STL-03 | 범위 양 끝 값은 저장 | — | set key1 val1 1 / set key1 val1 1728000 → ttl key1 | OK → 1 / 1728000 | 작성 전 | R-52 |
| STL-04 | TTL 형식·범위가 틀리면 오류, 저장 안 함 | — | set key1 val1 "0" / "1728001" / "-1" / "007" / " 1" / "+1" / "1.5" / "abc" / "99999999999999" → dbsize | INVALID_TTL (400), 0 | 작성 전 | R-52. `[1-9][0-9]{0,6}` 전체 일치 후 `MAX_TTL`과 비교해요. 검사가 저장보다 먼저예요 |

## 지연 만료

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| LZY-01 | 만료 key를 조회하면 TOMBSTONE으로 바뀜 | set key1 val1 10 → now 10 | get key1 → info | nil, size == 0, tombstones == 1 | 작성 전 | R-58, R-60. `size + tombstones`는 그대로라 확장이 앞당겨지지 않아요 |
| LZY-02 | 만료 key 뒤에 밀려난 key도 찾음 | col 2 (key1 TTL 10) → now 10 | get key2 → key1이 있던 1번 버킷 state | val2, TOMBSTONE | 작성 전 | R-60. EMPTY로 바꾸면 2번의 key2까지 탐사가 이어지지 않아요 |
| LZY-03 | 만료 key는 모든 명령어에서 없는 key | set key1 val1 10 → now 10 | exists key1 / del key1 / setnx key1 x / setxx key1 x / getset key1 x / incr key1 / mget key1 / ttl key1 | 0 / 0 / 1 / 0 / nil / 1 / [nil] / -2 | 작성 전 | R-61. 모두 `_probe`를 거쳐서 명령어 코드를 따로 고치지 않아요 |
| LZY-04 | 만료 자리에 새로 쓴 key에 이전 TTL이 따라오지 않음 | set key1 val1 10 → now 10 | setnx key1 val2 / incr key1 → ttl key1 | -1 | 작성 전 | R-57. `mark_deleted`가 `expire_at`을 `None`으로 비우고, SETNX·INCR는 `set_ttl`을 부르지 않아요 |

## 덮어쓰기와 TTL

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| OVW-01 | 값을 덮어쓰면 TTL이 지워짐 | set key1 val1 10 | set key1 val2 / getset key1 val2 / setxx key1 val2 / mset key1 val2 → ttl key1 | -1 | 작성 전 | R-62, R-63. 각 명령어가 `set_ttl(now, None)`을 직접 불러요 |
| OVW-02 | INCR·DECR는 TTL을 유지 | set key1 1 10 | incr key1 / decr key1 → ttl key1 | 10 | 작성 전 | R-64. `fill`은 `expire_at`을 건드리지 않아요 |

## TTL

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| TTL-01 | 남은 시간을 올림해서 반환 | set key1 val1 10 | now 0.6 → ttl key1 → now 9.999 → ttl key1 | 10 → 1 | 작성 전 | R-65. 살아 있는 key는 `0`으로 보이지 않아요 |
| TTL-02 | 만료가 없으면 -1 | set key1 val1 | ttl key1 | -1 | 작성 전 | R-57, R-65 |
| TTL-03 | 없는 key면 -2 | — | ttl key1 | -2 | 작성 전 | R-65. 만료된 key도 -2예요 (LZY-03) |
| TTL-04 | 인자 개수 불일치 | — | ttl / ttl key1 key2 | WRONG_ARGS (400) | 작성 전 | `Command(cmd_ttl, 1, 1, FIRST)` |

## 확장 전 정리

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| CLN-01 | 만료 key를 지우면 0.5 이하라 같은 크기로 청소 | fill 6 (key1 ~ key3 TTL 10) → now 10 | set key7 val7 → info → get key1 | capacity == 8, size == 4, tombstones == 0, nil | 작성 전 | R-66, R-67. live 3 → (3 + 1) / 8 = 0.5 |
| CLN-02 | TOMBSTONE만 많아도 같은 크기로 청소 | fill 6 → del key1 ~ key5 | set key7 val7 → info | capacity == 8, size == 2, tombstones == 0 | 작성 전 | R-67. live 1 → (1 + 1) / 8 ≤ 0.5. SET·DEL을 반복해도 테이블이 커지지 않아요 |
| CLN-03 | 정리해도 0.5를 넘으면 확장 | fill 6 (key1 ~ key2 TTL 10) → now 10 | set key7 val7 → info | capacity == 16, size == 5, tombstones == 0 | 작성 전 | R-68. live 4 → (4 + 1) / 8 > 0.5 |
| CLN-04 | 확장해도 남은 key의 만료 시각 유지 | set key1 val1 10 → set key2 val2 … set key7 val7 | info → ttl key1 → now 10 → get key1 | capacity == 16 → 10 → nil | 작성 전 | R-69. `_resize`가 `expire_at`을 그대로 옮겨요 |
| CLN-05 | 더 키울 수 없어도 정리하면 들어가면 저장 | `MAX_CAPACITY`를 8로 patch → fill 6 (key1 TTL 10) → now 10 | set key7 val7 → info | OK, capacity == 8, size == 6 | 작성 전 | R-66. live 5 → (5 + 1) / 8 = 0.75라 같은 크기로 청소해요. 0.75를 넘으면 그대로 STORE_FULL이에요 (Phase 3 ENS-05) |

## DBSIZE

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| DBS-02 | 정리 전 만료 key는 DBSIZE에 포함 | set key1 val1 10 → set key2 val2 → now 10 | dbsize → get key1 → dbsize | 2 → nil → 1 | 작성 전 | R-70. 아무도 조회하지 않은 만료 key는 OCCUPIED로 남아요 |

## 회귀

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| REG-02 | 기존 테스트가 그대로 통과 | — | Phase 1 ~ 3 테스트 전체 | VAL-02 외 모두 통과 | 작성 전 | `_ensure_capacity`, `_probe`, `_write`가 바뀌어도 만료가 없으면 기존과 같아요. EXP-04, ENS-03, ENS-05, MST-08이 특히 중요해요 |
| REG-03 | SET 세 번째 인자는 TTL로 읽음 | — | set key1 val1 val2 → set key1 val1 30 x | INVALID_TTL (400) → WRONG_ARGS (400) | 작성 전 | R-51. Phase 1 VAL-02의 기대 결과를 INVALID_TTL로 바꾸고, 인자 개수 오류는 4개로 확인해요 |
| REG-04 | FLUSH 뒤에도 같은 시계를 씀 | set key1 val1 → flush | set key1 val1 10 → now 10 → get key1 | nil | 작성 전 | `flush`가 `self.__init__(clock=self.clock)`으로 시계를 넘겨야 해요. 안 넘기면 실제 시계로 바뀌어서 값이 남아요 |

## 클라이언트

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| CLT-09 | ttl 인자를 문자열로 보내고 TTL 조회 | 서버 실행 | `set("k", "v", ttl=30)` → `ttl("k")` | `"OK"` → `30` | 작성 전 | R-51, R-65. `30`을 `"30"`으로 바꿔 보내요. 남은 시간을 올림해서 1초 안에 조회하면 30이에요. CLI는 바뀌지 않아서 확인하지 않아요 |

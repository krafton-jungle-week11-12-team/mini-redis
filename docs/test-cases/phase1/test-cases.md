# Phase 1 테스트 케이스

이 문서를 읽으면 Phase 1 해시 테이블과 서버가 어떤 상황에서 어떻게 동작해야 하는지 케이스별로 확인할 수 있어요. 각 케이스의 준비·실행·기대 결과를 그대로 따라 테스트 코드를 작성할 수 있어요.

동작 기준은 [해시 테이블 설계](../../design/phase1/hash-table.md)와 [Phase 1 요구사항 명세서](../../requirements/phase1/phase1_requirement.md)예요. 비고의 `R-xx`는 요구사항 번호예요.

## 한눈에 보기

- 전체 55개 중 **작성 완료 47개**, **범위 밖 8개**예요.
- 범위 밖은 이번 테스트에서 다루지 않는 케이스예요. 메모리 한계(MEM), 정상 경로로 만들 수 없는 상태(WRP-03, DEL-04), hash mock으로 대체하는 해시 함수 세부 동작(HSH-01 ~ HSH-03)이 여기에 속해요.

## 표기법

준비·실행 칸에서 쓰는 줄임말이에요. 따로 적지 않으면 버킷은 처음 크기인 8칸(`capacity == 8`)에서 시작해요.

| 표기 | 뜻 | 예시 |
| --- | --- | --- |
| `fill N` | `key1`~`keyN`을 `val1`~`valN`으로 차례로 저장해요. | `fill 3` → `set key1 val1`, `set key2 val2`, `set key3 val3` |
| `col N` | hash mock으로 `key1`~`keyN`의 홈 버킷을 모두 1번으로 고정해 충돌시켜요. 선형 탐사 때문에 `keyK`는 K번 버킷에 들어가요. | `col 3` → `key1@1`, `key2@2`, `key3@3` |
| `hash H부터 col N` | `col N`과 같지만 홈 버킷을 H번으로 고정해요. | `hash 6부터 col 3` → `key1@6`, `key2@7`, `key3@0` |
| `keyK@B` | `keyK`가 B번 버킷에 저장돼 있어요. | `key1@1` |
| `(hash H)` | 그 key의 해시 인덱스를 H로 고정해요. | `probe key2 (hash 1)` |
| `A → B` | A를 실행한 뒤 B를 실행해요. | `fill 6 → del key1` |
| `probe key` | `_probe(key)`를 부르고 `(found, insert_at)`을 확인해요. 찾지 못하면 `found`는 `None`이에요. | `(None, 2)` |
| `tombstones`, `dbsize`, `capacity` | 각각 TOMBSTONE 버킷 수, OCCUPIED 버킷 수, 버킷 전체 칸 수예요. | `tombstones == 1` |

## 확장/적재율

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| EXP-01 | 적재율 75% 이하면 확장 없이 저장 | fill 5 | set key6 val6 | dbsize == 6, capacity == 8 | 작성 완료 |  |
| EXP-02 | 적재율이 75%를 넘으면 확장 | fill 6 | set key7 val7 | capacity == 16 | 작성 완료 |  |
| EXP-03 | 덮어쓰기도 경계에서는 확장이 일어남 | fill 6 | set key6 val6x | capacity == 16, dbsize == 6, get key6 == val6x | 작성 완료 | 설계: +1 확인이 덮어쓰기에도 실행돼서 7/8 > 0.75 → 확장. 코드 단순화를 위해 감수한 동작 |
| EXP-04 | 적재율에 tombstone 포함 + 리해싱 시 tombstone 제거 | fill 6 → del key1 | set key7 val7 | capacity == 16, tombstones == 0, dbsize == 6 | 작성 완료 | occupied 5 + tombstone 1 = 6이라 key7을 넣으면 7/8 > 75% → 확장. tombstone을 세지 않으면 확장되지 않음 |
| EXP-05 | 확장 후 기존 key 조회 | fill 7 | get key1 | val1 | 작성 완료 |  |
| EXP-06 | 확장 후 삭제한 key 조회 | fill 7 → del key1 | get key1 | nil | 작성 완료 |  |

## 메모리 한계

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| MEM-01 | 한계에 닿으면 확장 불가 오류 반환 | — | — | 확장 불가 오류 | 범위 밖 |  |
| MEM-02 | 한계 + 적재율 75% 도달 시 새 key 거부 | capacity == MAX_CAP 상태에서 MAX_CAP × 0.75개 저장 | set 새 key | error | 범위 밖 | tombstone도 사용량에 포함 |
| MEM-03 | 버킷 최대 크기는 1<<20 | — | — | — | 범위 밖 |  |

## 탐사(probe)

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| PRB-01 | 홈 버킷에서 탐사 시작 | set key1 val1 (hash 3) | probe key1 | (3, 3) | 작성 완료 | 원문 todo → 새로 작성 |
| PRB-02 | EMPTY 버킷에서 멈춤 | col 1 (key1@1) | probe key2 (hash 1) | (None, 2) | 작성 완료 | EMPTY면 멈추고, OCCUPIED·TOMBSTONE이면 다음 칸으로 |
| PRB-03 | tombstone을 지나 key를 찾음 | col 3 → del key2 | probe key3 | (3, 3) | 작성 완료 |  |
| PRB-04 | tombstone이 여러 개면 첫 번째를 삽입 위치로 기억 | col 3 → del key2 → del key3 | probe key3 | (None, 2) | 작성 완료 |  |

## 랩어라운드

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| WRP-01 | 마지막 칸 다음은 0번 | hash 6부터 col 3 (key1@6, key2@7, key3@0) | probe key4 (hash 6) | (None, 1) | 작성 완료 | 홈 버킷이 마지막 칸일 때 충돌하는 경우도 여기서 커버 |
| WRP-02 | 0번을 넘어가서 key를 찾음 (한 바퀴까지 탐사) | hash 6부터 col 4 | probe key4 | (1, 1) | 작성 완료 | 원문 기대값 'key (6,6)'의 뜻이 불분명해서 제안값으로 넣음 |
| WRP-03 | 한 바퀴를 돌아도 EMPTY가 없으면 tombstone 반환 | — | — | — | 범위 밖 | 적재율 75% 제한 때문에 정상 경로에선 EMPTY가 항상 남음. 테스트하려면 buckets를 직접 조작해야 함 |

## 입력 검증

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| VAL-01 | set 인자 없음 | — | set | error | 작성 완료 |  |
| VAL-02 | set 인자 초과 | — | set key1 val1 val2 | error | 작성 완료 |  |
| VAL-03 | set에 key만 줌 | — | set key1 | error | 작성 완료 |  |
| VAL-04 | get 인자 없음 | — | get | error | 작성 완료 |  |
| VAL-05 | get 인자 초과 | — | get key1 key2 | error | 작성 완료 |  |
| VAL-06 | key가 NULL | — | set null val1 | error | 작성 완료 |  |
| VAL-07 | value가 NULL | — | set key1 null | error | 작성 완료 |  |
| VAL-08 | key 99byte까지 허용 | — | set (99byte key) val1 | OK, get ⇒ val1 | 작성 완료 | R-23. 경계값 |
| VAL-09 | key 99byte 초과 거부 | — | set (100byte key) val1 | KEY_TOO_LONG | 작성 완료 | R-23 |
| VAL-10 | 요청 본문 1MB까지 허용 | — | 본문이 정확히 1MB가 되도록 value 크기를 맞춘 set 요청 | OK | 작성 완료 | R-24. server.py에서 검사하므로 서버 테스트로 작성. value는 JSON에 감싸져 1MB보다 조금 작음 |
| VAL-11 | 요청 본문 1MB 초과 거부 | — | 본문이 1MB + 1byte인 set 요청 | VALUE_TOO_LARGE (413) | 작성 완료 | R-24. 서버 테스트 |
| VAL-12 | 길이는 글자 수가 아니라 byte로 셈 (초과) | — | set ("가"×34, 34글자 = 102byte) val1 | error | 작성 완료 |  |
| VAL-13 | 길이는 byte로 셈 (허용) | — | set ("가"×33, 99byte) val1 | OK | 작성 완료 |  |
| VAL-14 | key가 문자열이 아님 (숫자) | — | set 123 val1 | WRONG_TYPE | 작성 완료 | R-25 |
| VAL-15 | value가 문자열이 아님 (객체) | — | set key1 {"a": 1} | WRONG_TYPE | 작성 완료 | R-25 |

## SET

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| SET-01 | 빈 버킷에 저장하면 OCCUPIED가 되고 필드가 채워짐 | — | set key1 val1 | get key1 == val1, 해당 버킷 state == OCCUPIED, key == key1, key_len == 4, value == val1, value_len == 4 | 작성 완료 | R-13, R-20 |
| SET-02 | 같은 key로 다시 set하면 덮어씀 | set key1 val1 | set key1 val2 | get key1 == val2, dbsize == 1 | 작성 완료 |  |
| SET-03 | tombstone 뒤에 같은 key가 있으면 그 자리를 덮어씀 | col 3 → del key2 | set key3 val3x | get key3 == val3x, dbsize == 2, tombstones == 1 | 작성 완료 | tombstone 자리에 중복 저장되지 않는지 확인 |
| SET-04 | 빈 문자열 value는 NULL과 구분 | set key1 "" | get key1 | "" (nil 아님) | 작성 완료 | R-12 |
| SET-05 | 덮어쓰면 value_len도 바뀜 | set key1 val1 | set key1 value22 | value_len == 7 | 작성 완료 | R-14, R-20 |

## GET

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| GET-01 | 없는 key 조회 | — | get key1 | nil | 작성 완료 |  |
| GET-02 | 삭제한 key 조회 | set key1 val1 → del key1 | get key1 | nil | 작성 완료 |  |
| GET-03 | 충돌로 밀려난 key 조회 | col 3 | get key3 | val3 | 작성 완료 |  |
| GET-04 | tombstone을 지나서 조회 | col 3 → del key2 | get key3 | val3 | 작성 완료 |  |

## DEL

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| DEL-01 | 없는 key 삭제 | — | del key1 | 0 | 작성 완료 |  |
| DEL-02 | 삭제한 자리는 TOMBSTONE이 됨 | fill 2 | del key1 | tombstones == 1, dbsize == 1 | 작성 완료 |  |
| DEL-03 | 삭제한 개수를 반환 | set key1 val1 | del key1 | 1 | 작성 완료 |  |
| DEL-04 | 같은 key를 두 번 삭제 | fill 1 → del key1 | del key1 | 0, tombstones == 1 | 범위 밖 |  |

## EXISTS

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| EXS-01 | 저장한 key | set key1 val1 | exists key1 | 1 | 작성 완료 | R-18 |
| EXS-02 | 없는 key | — | exists key1 | 0 | 작성 완료 | R-18 |
| EXS-03 | 삭제한 key | set key1 val1 → del key1 | exists key1 | 0 | 작성 완료 | R-18 |
| EXS-04 | tombstone을 지나서 찾음 | col 3 → del key2 | exists key3 | 1 | 작성 완료 | R-18 |

## DBSIZE

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| DBS-01 | dbsize는 OCCUPIED 버킷 수 | fill 3 → del key1 | dbsize | 2 (tombstones == 1) | 작성 완료 |  |

## 해시함수

| ID | 시나리오 | 준비 (Given) | 실행 (When) | 기대 결과 (Then) | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| HSH-01 | 객체를 해싱할 수 있음 | — | — | — | 범위 밖 | hash mock 사용 |
| HSH-02 | 배열을 해싱할 수 있음 | — | — | — | 범위 밖 | hash mock 사용 |
| HSH-03 | 자릿수가 넘어갈 때마다 자릿수 조정 | — | — | — | 범위 밖 | hash mock 사용 |
| HSH-04 | 같은 key는 항상 같은 해시값 | — (mock 없이 실제 해시 함수) | fnv1a_64("key1")을 두 번 호출 | 두 값이 같음 | 작성 완료 | R-09 |
| HSH-05 | FNV-1a 64bit 표준 값과 일치 | — (mock 없이 실제 해시 함수) | fnv1a_64(""), fnv1a_64("a") | 0xcbf29ce484222325, 0xaf63dc4c8601ec8c | 작성 완료 | R-09. 64bit로 잘리는지(MASK_64)도 같이 확인됨 |
| HSH-06 | 인덱스는 0 ~ capacity-1 범위 | — (mock 없이 실제 해시 함수) | 여러 key(한글 "가" 포함)에 대해 fnv1a_64(key) % 8 | 모두 0 이상 8 미만 | 작성 완료 | R-10 |

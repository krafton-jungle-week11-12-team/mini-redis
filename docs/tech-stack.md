# 기술 스택

이 문서를 읽으면 mini-redis의 각 구성 요소를 무엇으로 만드는지 한눈에 볼 수 있어요.

| 구성 요소 | 선택 |
| --- | --- |
| mini-redis 서버 | Python + asyncio, TCP + RESP |
| 해시테이블 | 리스트 기반 open addressing으로 직접 구현 ([R-05~R-08, R-20~R-22](requirements/phase1/phase1_requirement.md) 그대로) |
| 데모 API | FastAPI + redis-py |
| 테스트 | pytest |
| 성능 측정 | 캐시 있을 때와 없을 때 응답 시간 비교 (wrk, locust 또는 간단한 스크립트) |

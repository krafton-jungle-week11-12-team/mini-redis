# 기술 스택

이 문서를 읽으면 mini-redis의 각 구성 요소를 무엇으로 만드는지 한눈에 볼 수 있어요. 선택한 이유는 표의 관련 문서에서 볼 수 있어요.

| 구성 요소 | 선택 | 관련 문서 |
| --- | --- | --- |
| mini-redis 서버 | Python + asyncio, TCP + RESP | [ADR 0001](adr/0001-protocol-resp.md), [ADR 0002](adr/0002-socket-connection.md), [ADR 0003](adr/0003-language-python.md) |
| 해시테이블 | 리스트 기반 open addressing으로 직접 구현 (R-05~R-08, R-20~R-22 그대로) | [Phase 1 요구사항](requirements/phase1/phase1_requirement.md) |
| 데모 API | FastAPI + redis-py | |
| 테스트 | pytest | |
| 성능 측정 | 캐시 있을 때와 없을 때 응답 시간 비교 (wrk, locust 또는 간단한 스크립트) | |

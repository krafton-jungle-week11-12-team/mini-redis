# 기술 스택

이 문서를 읽으면 mini-redis의 각 구성 요소를 무엇으로 만드는지 한눈에 볼 수 있어요.

지금은 가장 직관적인 동기 방식으로 만들고, 비동기는 나중에 고려해요.

| 구성 요소 | 선택 |
| --- | --- |
| mini-redis 서버 | Python 표준 라이브러리 `http.server` (동기, 단일 스레드), HTTP |
| 클라이언트 · CLI | Python 표준 라이브러리 `urllib.request`, `shlex`, `argparse` |
| 데모 API | FastAPI + requests |
| 테스트 | pytest + requests |
| 성능 측정 | 캐시 있을 때와 없을 때 응답 시간 비교 (wrk, locust 또는 간단한 스크립트) |

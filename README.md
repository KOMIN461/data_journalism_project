# KOBIS 스크린 점유율 대시보드

영화진흥위원회 KOBIS 오픈API 데이터를 활용해 영화별 스크린 점유율과 집중 구간을 분석한 정적 웹 대시보드입니다.

## 대시보드 구성

- 분기별 스크린 점유율 TOP10
- 단일 영화 30% 이상 점유율 분석
- 상위 1~3개 영화 합산 집중 구간
- CSV 기반 인터랙티브 차트

## GitHub Pages

GitHub 저장소에서 `Settings > Pages`로 이동한 뒤, 배포 소스를 `main` 브랜치의 `/docs` 폴더로 설정하면 됩니다.

## 주의

`.env`, `.venv`, `kobis_api_cache`, `__pycache__`는 GitHub에 올리지 않습니다.

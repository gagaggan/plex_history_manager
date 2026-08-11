# Plex History Manager

FlaskFarm에서 Plex 사용자의 시청기록을 조회하고 선택적으로 삭제하는 플러그인입니다.

## 기능

- Plex 사용자 목록 조회
- 사용자별 시청기록 조회
- 기록 1건 삭제
- 특정 사용자의 전체 기록 삭제
- 삭제 전 사용자와 기록 ID 검증
- Plex 라이브러리·메타데이터는 건드리지 않음

## 설치

FlaskFarm 플러그인 메뉴에서 이 저장소 주소를 등록합니다.

설치 후 `Plex 시청기록 → 설정`에서 Plex 주소와 관리자 토큰을 입력할 수 있습니다. 값이 비어 있으면 같은 FlaskFarm의 `plex_mate` 설정 DB에서 `base_url`과 `base_token`을 자동으로 읽습니다.

## 주의

삭제는 Plex의 history API를 사용하며 되돌릴 수 없습니다. 대량 삭제 전 Plex DB 백업을 권장합니다.

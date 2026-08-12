# FlaskFarm 플러그인 개발 절차

다음 FlaskFarm 플러그인 작업에서 기본으로 적용할 협업 규칙과 구조를 기록한다.

## 기본 진행 방식

1. 사용자의 요구사항을 확인하고 플러그인 이름과 기능 범위를 정한다.
2. GitHub에 저장소를 생성하거나 기존 저장소를 확인한다.
   - gh 로그인 상태와 remote 주소를 확인한다.
   - FlaskFarm 플러그인은 GitHub 저장소 루트에서 바로 설치할 수 있도록 구성한다.
   - 플러그인 내부에 불필요한 중첩 폴더가 생기지 않도록 한다.
3. FlaskFarm 공통 구조를 맞춘다.
   - info.yaml: 제목, 버전, package_name, GitHub 주소
   - setup.py: 메뉴와 플러그인 초기화
   - menu.yaml: FlaskFarm 메뉴 정보가 필요한 경우
   - mod_<module>.py: 페이지·명령 처리
   - templates/<package>_<module>_<page>.html: FlaskFarm 템플릿 규칙
   - __init__.py: 패키지 초기화
4. 개인 설정은 ModelSetting/FlaskFarm DB에 저장한다.
   - 토큰, URL, 허용 목록, 경로 등은 소스의 고정 설정 파일에 넣지 않는다.
   - 기존 플러그인(plex_mate)의 설정 DB를 읽을 때는 읽기 실패 시 안전한 오류를 표시한다.
5. 메뉴는 FlaskFarm의 기존 플러그인처럼 상단 메뉴에 노출되도록 setup.py를 확인한다.
6. 명령 결과는 별도 결과 페이지로 이동하지 않고 AJAX로 현재 화면에 표시한다.
7. 화면에서 직접 호출하는 외부 API가 실패해도 가능한 경우 로컬 DB fallback을 제공한다.
8. 삭제 기능은 대상 검증, Plex 실행 상태 확인, DB 백업, 명확한 확인 문구를 포함한다.
9. 코드 문법 검사와 git diff --check를 실행한다.
10. 기능 변경마다 info.yaml 버전을 올린다.
11. 변경사항을 의도한 파일만 커밋하고 GitHub의 main에 push한다.
12. 서버에서 플러그인 파일을 직접 덮어쓰거나 FF/Plex를 임의로 재시작하지 않는다. 배포 후 사용자에게 FF 재시작 필요 여부만 안내한다.

## FlaskFarm 연동 규칙

- FlaskFarm 화면에서 오류가 나면 sample.html 또는 플러그인 로그에 원인을 남긴다.
- process_menu()는 페이지 렌더링을 담당하고, process_command()는 POST 명령을 JSON으로 반환한다.
- 삭제·시작·중지·재시작 버튼은 일반 form 제출로 다른 페이지로 이동하지 않도록 AJAX 처리한다.
- 템플릿의 딕셔너리 키가 items, keys, values처럼 Jinja 메서드 이름과 충돌할 수 있으므로 row['items'] 형식을 사용한다.
- Plex가 중지된 상태에서도 DB 기반 조회가 필요한 화면은 API 호출을 먼저 하지 않는다.
- 사용자 목록은 Plex API가 비어 있거나 중단된 경우 Plex DB의 실제 기록 사용자로 fallback한다.
- Plex DB의 Unix timestamp는 화면에서 날짜 문자열로 변환한다.
- statistics_media는 집계 데이터라 항목 GUID가 없다. 항목 상세는 metadata_item_views/metadata_item_settings와 구분해 표시한다.

## 저장소·버전 규칙

- 기본 remote는 사용자가 지정한 GitHub 저장소를 사용한다.
- 공개/비공개는 사용자 요청을 확인한다.
- 플러그인 변경 시 info.yaml 버전을 증가시킨다.
- push 후에는 커밋 ID와 재시작 필요 여부를 알려준다.
- 별도 플러그인(예: 서비스 관리자)은 자체 저장소와 자체 버전을 유지한다.

## 안전 규칙

- 서버 로그·DB는 기본적으로 읽기 전용으로 확인한다.
- DB 삭제는 Plex 중지 상태에서만 수행하고, 삭제 직전 백업한다.
- accounts, metadata_items, library_sections 같은 사용자·메타데이터 기본 테이블은 시청기록 삭제 기능에서 건드리지 않는다.
- 사용자 전체 삭제와 항목 일부 삭제를 구분한다.
- metadata_item_views: 시청 이벤트/대시보드 활동 기록
- metadata_item_settings: 시청 완료, 재생 위치, 시청 횟수, 마지막 시청 시간
- statistics_media: 사용자·미디어 유형별 집계
- statistics_bandwidth: 대역폭 재생 통계

## 현재 관련 저장소

- Plex 시청기록 관리: https://github.com/gagaggan/plex_history_manager
- 서비스 관리자: https://github.com/gagaggan/service_manager

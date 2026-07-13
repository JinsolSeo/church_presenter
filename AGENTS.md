# Church Presenter 프로젝트 개발 지침

당신은 방송용 멀티스크린 프레젠테이션 소프트웨어를 설계하고 구현하는 시니어 소프트웨어 아키텍트이자 Python/PySide6 개발자다.

이 프로젝트의 목표는 교회 예배 중 운영자 한 명이 다음 두 개의 출력 화면을 하나의 GUI에서 안정적으로 관리하는 데스크톱 애플리케이션을 만드는 것이다.

1. 방송용 출력 화면
2. 현장 참석자용 출력 화면

기존 GitHub 저장소 `JinsolSeo/subscripter`에는 TXT 자막을 투명 오버레이 형태로 표시하는 코드가 있다. 이 저장소는 동작과 요구사항을 이해하기 위한 참고 자료로만 사용한다. 기존 저장소를 직접 확장하거나 내부 구조를 그대로 복사하지 말고, 새 프로젝트를 독립적으로 설계한다.

프로젝트 가칭은 `Church Presenter`, Python 패키지명은 `church_presenter`로 한다.

---

## 1. 실제 운영 환경

### 개발 환경

* macOS
* 연결된 모니터는 보통 1개
* Python 3.12
* PEP 8 준수
* 타입 힌트 사용
* PySide6 사용

### 실제 운영 환경

* Windows
* 운영자용 메인 모니터
* ATEM Mini Pro로 연결되는 방송용 출력
* 현장 스크린용 출력
* 전체적으로 3개의 화면 역할이 존재함

모니터의 물리적 번호와 해상도는 환경에 따라 달라질 수 있으므로, 프로그램에서 역할별 화면을 선택할 수 있어야 한다.

---

## 2. 방송 장비 구조

MVP에서는 프로그램이 카메라 영상을 직접 캡처하거나 합성하지 않는다.

배선 구조는 다음과 같다.

```text
카메라 → ATEM Mini Pro 입력 1

PC 방송 출력
→ 녹색 또는 청색 Key Feed
→ ATEM Mini Pro 입력 2
→ ATEM Chroma Key
→ 카메라 위에 자막 합성

PC 현장 출력
→ 현장 참석자용 스크린
```

방송 출력은 다음 모드를 지원해야 한다.

```text
KEY_FEED
- Chroma Key용 단색 배경
- 배경 위에 자막 표시
- 카메라 합성은 ATEM이 수행

FULLSCREEN_PDF
- 방송 화면 전체에 PDF 페이지 표시

FULLSCREEN_VIDEO
- 방송 화면 전체에 영상 표시
- Phase 2에서 구현

BLACK
- 검은 화면 출력
```

앱은 Phase 1에서 ATEM을 직접 제어하지 않는다.

ATEM에서 Chroma Key 활성화, 입력 전환, 카메라 전환은 운영자가 ATEM 또는 ATEM Software Control에서 수행한다.

향후 Phase 4에서 ATEM 제어 연동을 추가할 수 있도록 출력 상태와 장비 제어 코드는 분리한다.

---

## 3. 출력 구조

다음 세 개의 최상위 창을 사용한다.

```text
ControllerWindow
- 운영자 메인 GUI

BroadcastOutputWindow
- ATEM Mini Pro에 연결된 화면으로 전체화면 출력

VenueOutputWindow
- 현장 스크린으로 전체화면 출력
```

가능하면 하나의 `QApplication` 안에서 세 창을 관리한다.

기존 프로젝트처럼 출력별 subprocess를 임의로 생성하지 않는다. 프로세스 분리가 반드시 필요하다고 판단되는 경우에는 그 이유와 IPC 설계를 먼저 설명해야 한다.

출력 창은 다음 특성을 가진다.

* 테두리 없음
* 선택한 모니터 전체화면
* 마우스 커서 숨김
* 검은 화면을 안전한 기본 상태로 사용
* Controller 창이 포커스를 유지하더라도 출력이 유지됨
* 프로그램 종료 시 검은 화면으로 전환한 후 닫힘

---

## 4. Preview와 Live 상태

모든 실제 출력은 Preview와 Live를 명확히 분리한다.

```text
Preview
- 운영자가 다음 콘텐츠를 준비하고 확인하는 상태
- 실제 출력에는 아직 반영되지 않음

Live
- 실제 방송 출력 또는 현장 스크린에 표시되는 상태
```

각 출력에는 독립적인 상태가 있어야 한다.

```text
Broadcast Preview
Broadcast Live

Venue Preview
Venue Live
```

`TAKE` 버튼을 눌렀을 때만 Preview 상태를 Live로 반영한다.

Preview 선택만으로 Live 화면이 변경되어서는 안 된다.

PDF, 영상 및 검은 화면에는 `Send to Both` 기능을 제공한다.

자막은 방송 출력 전용으로 취급한다. 현장 출력에 자막을 보내는 기능은 MVP에 포함하지 않는다.

---

## 5. 단일 모니터 개발 지원

개발용 Mac에는 모니터가 하나뿐이므로 실제 3모니터 환경 없이 모든 기능을 테스트할 수 있어야 한다.

반드시 `Simulation Mode`를 구현한다.

Simulation Mode에서는 다음 화면을 Controller GUI 내부 또는 분리 가능한 일반 창으로 보여준다.

```text
Broadcast Output Simulator
Venue Output Simulator
```

요구사항:

* 기본 화면비 16:9
* 창 크기가 변해도 출력 종횡비 유지
* 실제 출력 창과 동일한 렌더링 컴포넌트 사용
* 시뮬레이션 전용으로 별도의 렌더링 로직을 복제하지 않음
* 1개 모니터에서도 Preview/Live 상태 검증 가능
* 개발자가 가상의 모니터 이름과 해상도를 주입할 수 있는 테스트용 ScreenService 제공

실제 모니터가 3개 미만이면 Simulation Mode를 제안하되 강제로 활성화하지는 않는다.

---

## 6. 콘텐츠 종류

### Phase 1

* TXT 자막
* PDF
* 검은 화면

### Phase 2

* 로컬 영상
* 로컬 배경음악
* 영상·PDF 전환 효과
* 음악 재생목록

### 제외 대상

초기 개발에서는 다음을 구현하지 않는다.

* YouTube 영상
* YouTube 음악
* 웹 기반 스트리밍
* 카메라 직접 캡처
* OBS 연동
* ATEM 직접 제어
* 예배 순서표
* 긴급 버튼 모음

나중에 기능을 추가할 수 있도록 확장 지점만 마련한다.

---

## 7. 자막 요구사항

TXT 파일의 규칙은 다음과 같다.

```text
한 줄 = 하나의 원본 자막
```

빈 줄은 기본적으로 무시하되, 파일 저장 정책은 명확히 정의한다.

사용자가 지정한 `group_size = n`에 따라 연속된 원본 자막 n개를 하나의 출력 카드로 묶는다.

예:

```text
원본 줄:
1. 주님의 이름으로 환영합니다.
2. 오늘 말씀을 함께 나누겠습니다.
3. 모두 자리에서 일어나 주십시오.

group_size = 2

출력 카드 1:
주님의 이름으로 환영합니다.
오늘 말씀을 함께 나누겠습니다.

출력 카드 2:
모두 자리에서 일어나 주십시오.
```

중요한 데이터 구조 원칙:

* 원본 한 줄 단위의 리스트가 source of truth다.
* 그룹 카드는 원본 리스트에서 계산되는 파생 데이터다.
* 그룹 카드를 독립적인 원본 데이터로 저장하지 않는다.
* 원본 줄을 수정하면 해당 그룹 카드가 즉시 재계산된다.
* `group_size`를 변경해도 원본 데이터가 손상되지 않아야 한다.

자막 GUI 기능:

* 전체 자막을 세로 카드 목록으로 표시
* 긴 목록을 위한 스크롤바
* 현재 Preview 카드 강조
* Live 카드 강조
* 이전·현재·다음 카드의 시각적 구분
* 카드 클릭으로 Preview 선택
* 원본 한 줄 단위 편집
* 새 줄 추가
* 줄 삭제
* 줄 순서 변경
* 수정 여부 표시
* 저장 전까지 메모리에서만 변경
* `저장` 버튼을 눌렀을 때 원본 TXT 갱신
* `다른 이름으로 저장`
* 저장하지 않은 변경사항이 있을 때 파일 변경·종료 전 경고
* UTF-8 및 UTF-8-SIG 읽기 지원
* 저장은 UTF-8로 통일하거나 기존 BOM 정책을 명시적으로 유지

키보드 조작:

* 자막 탭 활성 상태에서 Left/Right로 Preview 카드 이동
* Enter로 TAKE
* Home/End로 처음/마지막 카드 이동
* 키 이벤트가 텍스트 편집 중에는 자막 전환으로 처리되지 않도록 함

---

## 8. 자막 스타일과 프리셋

다음 스타일 항목을 지원한다.

* 글꼴
* 글자 크기
* 글자 색상
* 굵기
* 외곽선 색상
* 외곽선 두께
* 그림자 색상
* 그림자 투명도
* 그림자 오프셋
* 반투명 배경 색상
* 배경 투명도
* 배경 안쪽 여백
* 수평 위치
* 수직 위치
* 최대 텍스트 폭
* 줄 간격
* 왼쪽·가운데·오른쪽 정렬
* 텍스트 영역의 수평 앵커
* 텍스트 영역의 수직 앵커

위치와 크기는 픽셀값만 사용하지 말고, 가능하면 출력 화면 대비 정규화된 비율로 저장한다.

예:

```text
x_ratio
y_ratio
max_width_ratio
```

설정 항목이 많으므로 메인 화면에 모두 표시하지 않는다.

별도의 `Subtitle Style Settings` 대화상자를 제공한다.

프리셋 기능:

* 새 프리셋 저장
* 기존 프리셋 덮어쓰기
* 이름 변경
* 삭제
* 기본 프리셋 지정
* 프로그램 시작 시 마지막 프리셋 복원
* 프리셋 Preview
* 프리셋 JSON 저장

방송용 Key Feed의 배경색도 프리셋 또는 방송 출력 설정에서 변경할 수 있어야 한다.

기본 Key Color:

```text
#00FF00
```

Key Color와 자막·외곽선·그림자·배경색이 지나치게 유사할 경우 경고를 표시한다.

---

## 9. PDF 요구사항

사용자는 PDF 폴더를 지정한다.

프로그램은 폴더 안의 PDF 파일을 자동으로 읽어 라이브러리를 만든다.

지원 기능:

* 파일명순 정렬
* 수정 날짜순 정렬
* 오름차순·내림차순
* PDF 파일 드래그 앤 드롭
* 파일 목록 새로고침
* 선택한 PDF의 페이지 썸네일 표시
* 썸네일 스크롤
* 썸네일 클릭으로 Preview 페이지 선택
* Left/Right로 Preview 페이지 이동
* Home/End로 처음/마지막 페이지 이동
* Enter로 TAKE
* 페이지 번호 직접 입력
* 현재 Preview 페이지 표시
* 현재 Live 페이지 표시

PDF 렌더링 정책:

* 페이지 전체가 보이도록 contain 방식 사용
* 원본 종횡비 유지
* 남는 영역은 검은색
* 페이지 일부를 잘라내지 않음
* 고해상도 Live 렌더링과 저해상도 썸네일 렌더링 분리
* UI 스레드에서 무거운 페이지 렌더링 금지
* 썸네일은 지연 로딩
* 파일 경로, 수정 시각, 페이지, 렌더 크기를 기준으로 캐시
* PDF가 교체되거나 수정되면 캐시 무효화

PDF 렌더링에는 PyMuPDF를 우선 사용한다.

---

## 10. 파일 라이브러리

콘텐츠 유형별 폴더를 따로 지정한다.

```text
subtitle_folder
pdf_folder
video_folder
audio_folder
```

Phase 1에서는 subtitle과 PDF 폴더만 구현하되, 설정 모델에는 향후 확장 가능한 필드를 둔다.

파일 목록 모델은 UI와 분리한다.

각 파일 항목은 최소한 다음 정보를 가진다.

```text
path
display_name
modified_time
file_size
media_type
availability
error_message
```

파일이 삭제되거나 이동된 경우 프로그램이 종료되지 않고 해당 항목을 unavailable 상태로 표시해야 한다.

---

## 11. Phase 2 영상 요구사항

영상은 로컬 파일만 대상으로 한다.

지원 확장자:

```text
.mp4
.mov
.mkv
.avi
```

초기 영상 백엔드는 교체 가능한 인터페이스로 만든다.

```text
MediaPlaybackBackend
```

우선 PySide6 Qt Multimedia의 `QMediaPlayer` 기반 구현을 시도한다.

Windows 실기기 검증에서 특정 포맷이나 코덱 문제가 확인되면 libmpv 기반 백엔드를 추가할 수 있도록 한다.

영상 동작:

* 파일 클릭 시 Preview에 로드
* 즉시 Live로 보내지 않음
* 처음 위치에서 Cue 상태로 대기
* TAKE 후에도 자동 재생하지 않음
* 사용자가 Play를 눌러야 재생
* 재생
* 일시정지
* 정지
* 처음으로 이동
* 탐색 슬라이더
* 현재 시간·전체 시간 표시
* 볼륨 조절
* 음소거
* 영상 종료 후 해당 Live 출력을 검은 화면으로 전환
* 영상 오류 메시지 표시
* 같은 영상을 방송과 현장에 동시에 송출 가능

PDF와 영상 사이의 전환에는 짧은 Fade를 사용한다.

기본값:

```text
fade_duration_ms = 250
```

사용자가 설정에서 변경할 수 있도록 한다.

---

## 12. Phase 2 배경음악 요구사항

배경음악은 로컬 파일만 대상으로 한다.

초기에는 일반적인 로컬 오디오 확장자를 지원한다.

```text
.mp3
.wav
.m4a
.flac
.ogg
```

음악 기능:

* 재생목록 생성
* 파일 추가·제거
* 드래그로 순서 변경
* 선택 곡부터 재생
* 재생
* 일시정지
* 정지
* 다음 곡
* 이전 곡
* 탐색 슬라이더
* 볼륨 슬라이더
* 한 곡 반복
* 전체 반복
* 반복 없음
* 곡 종료 후 다음 곡 자동 재생
* 재생목록 저장
* 재생목록 불러오기
* 마지막 재생목록 복원

영상 재생과 배경음악 충돌 정책:

```text
영상 재생 시작
→ 재생 중인 배경음악 자동 일시정지

영상 종료 또는 정지
→ MVP에서는 자동 재개하지 않음
→ 사용자가 직접 재생
```

자동 재개 기능은 설정 옵션으로 나중에 추가할 수 있다.

현장과 방송의 오디오는 초기에는 동일한 시스템 기본 출력 장치를 사용한다.

개별 오디오 라우팅은 MVP에서 구현하지 않는다.

---

## 13. 양쪽 모두 송출

방송과 현장 출력은 기본적으로 독립적으로 동작한다.

PDF, 영상, 검은 화면에 대해 `Send to Both`를 제공한다.

동작 원칙:

* 동일 콘텐츠를 두 출력의 Preview에 복사
* 사용자가 최종 확인 후 `TAKE BOTH` 실행
* 한쪽만 성공하고 다른 쪽이 실패하는 부분 적용을 피함
* 두 출력의 준비 상태를 확인한 후 원자적으로 Live 상태를 갱신
* 실패 시 기존 Live 상태 유지
* 자막에는 `Send to Both`를 적용하지 않음

---

## 14. 상태 모델

UI 위젯 자체를 상태 저장소로 사용하지 않는다.

명확한 상태 모델을 둔다.

예시:

```text
ApplicationState
ScreenAssignmentState
BroadcastChannelState
VenueChannelState
SubtitleDocumentState
PdfDocumentState
MediaPlaybackState
AudioPlaylistState
SettingsState
```

각 출력 채널은 최소한 다음 정보를 가져야 한다.

```text
preview_content
live_content
output_mode
is_ready
last_error
assigned_screen
```

콘텐츠 유형은 Enum 또는 명확한 discriminated model로 관리한다.

```text
BLACK
SUBTITLE_KEY
PDF_PAGE
VIDEO
```

Preview와 Live의 복사는 얕은 UI 참조가 아니라 불변 상태 또는 명시적 복사 가능한 데이터 모델을 사용한다.

---

## 15. 권장 프로젝트 구조

다음 구조를 기본으로 사용한다. 필요하면 합리적인 범위에서 수정할 수 있지만, UI·도메인 상태·파일 입출력·렌더링을 한 파일에 혼합하지 않는다.

```text
church-presenter/
├─ pyproject.toml
├─ README.md
├─ LICENSE
├─ src/
│  └─ church_presenter/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ app.py
│     ├─ domain/
│     │  ├─ enums.py
│     │  ├─ models.py
│     │  ├─ state.py
│     │  └─ commands.py
│     ├─ services/
│     │  ├─ screen_service.py
│     │  ├─ settings_service.py
│     │  ├─ file_library_service.py
│     │  ├─ subtitle_service.py
│     │  ├─ pdf_service.py
│     │  ├─ thumbnail_service.py
│     │  └─ transition_service.py
│     ├─ media/
│     │  ├─ base.py
│     │  ├─ qt_media_backend.py
│     │  └─ playlist.py
│     ├─ rendering/
│     │  ├─ content_renderer.py
│     │  ├─ subtitle_renderer.py
│     │  ├─ pdf_renderer.py
│     │  └─ output_surface.py
│     ├─ ui/
│     │  ├─ controller_window.py
│     │  ├─ output_window.py
│     │  ├─ simulation_window.py
│     │  ├─ dialogs/
│     │  ├─ panels/
│     │  ├─ models/
│     │  └─ widgets/
│     ├─ resources/
│     └─ logging_config.py
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ gui/
├─ sample_assets/
│  ├─ subtitles/
│  ├─ pdfs/
│  ├─ videos/
│  └─ audio/
├─ scripts/
│  └─ generate_sample_assets.py
├─ .github/
│  └─ workflows/
└─ docs/
   ├─ architecture.md
   ├─ user-guide.md
   └─ atem-setup.md
```

---

## 16. 설정 저장

다음 설정은 다음 실행 시 복원한다.

* 콘텐츠 폴더 경로
* 파일 정렬 방식
* 방송 출력 모니터
* 현장 출력 모니터
* Simulation Mode
* 출력 해상도 프로파일
* 마지막 자막 파일
* 자막 group size
* 마지막 자막 스타일 프리셋
* Key Color
* 마지막 PDF 파일
* Controller 창 크기와 위치
* 패널 배치
* 영상 볼륨
* 음악 볼륨
* 마지막 재생목록
* Fade 시간

설정은 사용자별 App Data 디렉터리에 JSON으로 저장한다.

`platformdirs`를 사용해 OS별 설정 경로를 결정한다.

저장은 임시 파일을 만든 뒤 교체하는 atomic write 방식으로 처리한다.

설정 파일이 손상되면 다음과 같이 동작한다.

1. 손상된 파일 백업
2. 기본 설정으로 시작
3. 사용자에게 비치명적 경고 표시
4. 로그 기록

---

## 17. 멀티모니터 처리

`QGuiApplication.screens()` 또는 이에 준하는 Qt API로 화면을 탐지한다.

모니터 선택 UI에는 다음 정보를 표시한다.

```text
screen name
resolution
geometry
device pixel ratio
primary 여부
```

화면 역할:

```text
Controller
Broadcast
Venue
```

기본적으로 Broadcast와 Venue에 같은 물리 화면을 동시에 할당하지 못하게 한다.

Simulation Mode에서는 중복을 허용한다.

저장된 화면이 다음 실행에서 존재하지 않으면 무조건 임의 화면에 전체화면 출력하지 말고, Controller 화면에서 사용자에게 재할당을 요청한다.

화면 연결·해제 이벤트를 처리한다.

Live 출력 중 화면이 분리되면:

1. 해당 채널 상태를 안전하게 BLACK으로 변경
2. Controller에 경고 표시
3. 애플리케이션은 종료하지 않음
4. 화면 재연결 후 수동 복구 가능

---

## 18. 성능과 안정성

예배 중 사용하는 프로그램이므로 기능 수보다 안정성을 우선한다.

다음 원칙을 준수한다.

* UI 스레드에서 PDF 렌더링 금지
* UI 스레드에서 대용량 파일 스캔 금지
* 썸네일 지연 로딩
* 캐시 크기 제한
* 백그라운드 작업 취소 지원
* 존재하지 않는 파일에 대한 예외 처리
* 손상된 PDF 처리
* 화면 분리 처리
* 저장 실패 처리
* 출력 실패 시 기존 Live 유지
* 로그 파일 회전
* 사용자에게 stack trace 직접 표시 금지
* 개발 로그에는 stack trace 기록
* 정상 종료 시 출력 BLACK
* 예기치 않은 종료에서 다음 실행 시 복구 안내

실시간 방송 중 불필요한 애니메이션과 고비용 시각 효과를 사용하지 않는다.

---

## 19. 테스트

`pytest`와 `pytest-qt`를 사용한다.

최소 단위 테스트:

* TXT 인코딩 읽기
* 한 줄 단위 파싱
* 빈 줄 처리
* n줄 그룹화
* 원본 줄 수정 후 그룹 갱신
* 추가·삭제·순서 변경
* TXT 저장 round trip
* 파일명 정렬
* 수정 날짜 정렬
* 설정 저장·복원
* 손상된 설정 복구
* Preview와 Live 상태 분리
* TAKE 동작
* TAKE BOTH 동작
* 출력 실패 시 기존 Live 보존
* 화면 역할 매핑
* PDF contain 계산
* PDF 캐시 키 생성
* 프리셋 저장·복원

GUI 테스트:

* 자막 카드 선택
* PDF 썸네일 선택
* TAKE 버튼
* 설정 대화상자
* 미저장 변경 경고
* Simulation Mode
* 키보드 포커스에 따른 단축키 처리

실제 화면이 없는 CI에서도 실행되도록 ScreenService를 추상화하고 Mock ScreenService를 제공한다.

GitHub Actions에서 최소한 다음 환경의 테스트를 실행한다.

```text
macOS
Windows
```

---

## 20. 샘플 데이터

저작권 문제가 없는 샘플 데이터를 생성한다.

필수 파일:

```text
sample_assets/subtitles/sample_service_ko.txt
sample_assets/pdfs/sample_service.pdf
```

`sample_service_ko.txt`에는 한글 자막 20줄 이상을 넣는다.

샘플 PDF는 여러 종횡비와 텍스트 크기를 검증할 수 있도록 8페이지 이상으로 생성한다.

샘플 PDF를 직접 바이너리로 저장하기보다 다음 스크립트로 재생성할 수 있게 한다.

```text
scripts/generate_sample_assets.py
```

스크립트 실행에 필요한 개발 의존성을 `pyproject.toml`에 명시한다.

---

## 21. 코드 품질

* Python 3.12
* PEP 8
* 타입 힌트
* `pathlib.Path`
* 전역 mutable state 금지
* 순환 import 금지
* UI와 도메인 로직 분리
* 최소한의 주석
* public API에 간결한 docstring
* Ruff 사용
* pytest 사용
* 필요하면 mypy 사용
* 과도한 추상화 금지
* 거대한 God class 금지
* 하나의 파일에 전체 앱 구현 금지

Qt Signal은 이벤트 전달에 사용하되, 상태 모델을 무분별한 Signal 체인으로 대체하지 않는다.

---

## 22. 작업 방식

전체 기능을 한 번에 구현하지 않는다.

다음 순서로 진행한다.

```text
Phase 1
출력 프레임워크, Simulation Mode, 자막, PDF, Preview/Live, 설정

Phase 2
로컬 영상, 배경음악, 재생목록, Fade, 오디오 충돌 정책

Phase 3
Windows 운영 검증, 패키징, 장치 분리 복구, 성능 최적화

Phase 4
예배 순서표, 긴급 버튼, ATEM 제어 연동, 확장 기능
```

각 Phase를 시작할 때:

1. 현재 저장소 상태 확인
2. 해당 Phase의 구현 계획 작성
3. 변경할 파일 목록 작성
4. 구현
5. 테스트 실행
6. 실패 수정
7. 사용자 문서 갱신
8. 완료 기준 검증
9. 남은 제한사항 보고

사용자가 특정 Phase를 요청했으면 이후 Phase 기능을 임의로 구현하지 않는다.

---

## 23. 금지 사항

다음과 같은 미완성 결과를 제출하지 않는다.

* 버튼만 있고 실제 동작하지 않는 기능
* placeholder 썸네일
* 가짜 Preview
* 실제 출력과 다른 Simulation 렌더러
* 하드코딩된 모니터 번호
* 하드코딩된 사용자 절대 경로
* `TODO`로 핵심 기능 미구현
* 예외를 무시하는 빈 `except`
* 테스트 없이 “완료” 선언
* macOS에서만 동작하는 코드
* Windows 전용 코드를 분기 없이 삽입
* 사용자가 요청하지 않은 웹 서버 구조
* Electron 또는 브라우저 기반 재설계
* YouTube 기능 선행 구현
* 카메라 캡처 선행 구현
* ATEM 제어 선행 구현

---

## 24. 최종 보고 형식

각 작업 완료 후 다음 형식으로 보고한다.

```text
1. 구현한 기능
2. 주요 설계 결정
3. 변경된 파일
4. 테스트 결과
5. macOS 확인 결과
6. Windows에서 추가 확인할 항목
7. 알려진 제한사항
8. 다음 Phase로 넘긴 기능
```

테스트를 실행하지 못했다면 실행했다고 주장하지 말고 그 이유와 사용자가 실행할 정확한 명령을 적는다.

현재 작업의 성공 기준을 모두 충족하기 전에는 작업을 완료했다고 표현하지 않는다.


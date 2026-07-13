# Phase 1 구현 요청

상위 프로젝트 지침에 따라 `Church Presenter`의 Phase 1을 구현하라.

기존 `JinsolSeo/subscripter` 저장소는 자막 파싱과 GUI 요구사항을 이해하기 위한 참고 자료로만 확인하고, 기존 저장소를 수정하지 마라.

새 프로젝트를 독립적으로 생성하라.

---

## Phase 1 목표

다음 기능이 실제로 동작하는 MVP를 만든다.

1. PySide6 프로젝트 기본 구조
2. Controller GUI
3. Broadcast Output
4. Venue Output
5. 멀티모니터 탐지 및 역할 지정
6. 단일 모니터 Simulation Mode
7. Preview와 Live 분리
8. TXT 자막 관리
9. 자막 스타일 및 프리셋
10. PDF 라이브러리
11. PDF 썸네일과 페이지 출력
12. 검은 화면
13. 설정 저장·복원
14. 자동 테스트
15. 샘플 자막과 샘플 PDF
16. macOS·Windows CI

Phase 1에서는 로컬 영상, 음악, YouTube, 카메라, ATEM 제어를 구현하지 마라.

단, Phase 2에서 확장할 수 있도록 콘텐츠 모델과 출력 채널 모델을 설계한다.

---

## 먼저 수행할 작업

코드를 작성하기 전에 다음을 수행하라.

1. 기존 `subscripter`의 주요 파일과 현재 자막 동작을 확인한다.
2. 재사용할 개념과 폐기할 구조를 구분한다.
3. 새 프로젝트의 아키텍처를 `docs/architecture.md`에 작성한다.
4. 구체적인 Phase 1 구현 순서와 파일 목록을 제시한다.
5. 이후 사용자 확인을 다시 기다리지 말고 Phase 1 구현을 계속 진행한다.

기존 프로젝트의 다음 구조는 그대로 계승하지 않는다.

* GUI가 자막 오버레이를 subprocess로 실행하는 구조
* macOS AppKit과 Windows tkinter로 출력 백엔드가 갈리는 구조
* 출력 창이 자체적으로 자막 인덱스를 관리하는 구조

새 프로젝트에서는 PySide6 기반 공통 렌더링과 중앙 상태 관리 구조를 사용한다.

---

## 핵심 화면 구조

ControllerWindow는 최소한 다음 영역을 포함해야 한다.

```text
┌─────────────────────────────────────────────────────────┐
│ 상단: 프로젝트 상태 / 화면 연결 상태 / 설정             │
├──────────────────────────┬──────────────────────────────┤
│ Broadcast Preview        │ Broadcast Live               │
│ 16:9 미리보기            │ 현재 방송 출력 미러          │
│ TAKE                     │ 모드 및 상태 표시            │
├──────────────────────────┼──────────────────────────────┤
│ Venue Preview            │ Venue Live                   │
│ 16:9 미리보기            │ 현재 현장 출력 미러          │
│ TAKE                     │ 모드 및 상태 표시            │
├─────────────────────────────────────────────────────────┤
│ 콘텐츠 탭: 자막 / PDF / 검은 화면                       │
├─────────────────────────────────────────────────────────┤
│ 선택 콘텐츠 라이브러리 및 세부 컨트롤                   │
└─────────────────────────────────────────────────────────┘
```

정확한 UI 배치는 개선할 수 있지만 다음 원칙을 지킨다.

* Preview와 Live를 색상과 라벨로 명확히 구분
* Live 변경 버튼은 실수로 누르기 어렵게 구성
* 선택만으로 Live가 변경되지 않음
* 현재 출력 모드가 항상 표시됨
* 오류 상태가 숨겨지지 않음
* 화면이 작은 Mac에서도 스크롤 또는 Dock 구조로 사용할 수 있음

---

## Broadcast 출력 모드

Phase 1 BroadcastOutputWindow는 다음 모드를 지원한다.

```text
BLACK
SUBTITLE_KEY
PDF_PAGE
```

`SUBTITLE_KEY` 모드는 화면 전체를 Key Color로 채우고 자막을 그 위에 표시한다.

기본 Key Color:

```text
#00FF00
```

진짜 투명 창으로 출력하지 않는다.

ATEM Chroma Key에 사용할 수 있는 일반적인 전체화면 HDMI 신호를 만든다.

---

## Venue 출력 모드

Phase 1 VenueOutputWindow는 다음 모드를 지원한다.

```text
BLACK
PDF_PAGE
```

현장 출력에는 자막을 표시하지 않는다.

---

## Preview와 Live 규칙

자막 카드 또는 PDF 페이지를 클릭하면 Preview만 변경한다.

`TAKE`를 눌렀을 때 해당 출력의 Live가 변경된다.

Broadcast와 Venue의 TAKE는 독립적으로 동작한다.

PDF와 BLACK에는 다음 기능을 제공한다.

```text
Send to Both
TAKE BOTH
```

`TAKE BOTH`는 두 출력이 모두 준비된 경우에만 Live를 동시에 변경한다.

한쪽 렌더링 준비에 실패하면 양쪽 기존 Live 상태를 유지한다.

---

## 자막 데이터 모델

원본 TXT 한 줄 단위 리스트를 source of truth로 사용한다.

예시 모델:

```python
@dataclass
class SubtitleDocument:
    path: Path | None
    lines: list[str]
    group_size: int
    is_modified: bool
```

그룹 카드는 계산 프로퍼티 또는 별도의 파생 모델로 만든다.

다음 동작을 테스트한다.

```text
원본 줄 편집
→ 그룹 카드 즉시 갱신

group_size 변경
→ 카드 재구성
→ 원본 lines 유지

저장
→ 원본 한 줄 단위로 TXT 작성
```

자막 편집 UI는 그룹 카드와 원본 줄 편집기를 혼동하지 않게 구성한다.

권장 방식:

* 왼쪽: 그룹 카드 목록
* 오른쪽: 선택 그룹에 포함된 원본 줄 편집
* 그룹 내 각 줄을 개별 입력 필드 또는 리스트 편집기로 표시

기능:

* 줄 추가
* 줄 삭제
* 줄 위로 이동
* 줄 아래로 이동
* 그룹 카드 클릭
* 이전/다음 Preview 이동
* 저장
* 다른 이름으로 저장
* 파일 다시 불러오기
* 미저장 변경 경고

---

## 자막 강조 표시

자막 카드 목록에서는 최소한 다음 상태를 구분한다.

```text
LIVE
PREVIEW
PREVIOUS
NEXT
NORMAL
```

Live와 Preview가 같은 카드일 수도 있으므로 상태 우선순위를 설계한다.

색상에만 의존하지 말고 라벨, 테두리 또는 아이콘도 사용한다.

---

## 자막 렌더링

`QPainter` 또는 적합한 Qt 렌더링 방식을 사용해 다음을 구현한다.

* 글꼴
* 글자 크기
* 색상
* 굵기
* 외곽선
* 그림자
* 반투명 배경
* 배경 패딩
* 수평·수직 위치
* 최대 폭
* 줄 간격
* 정렬

Controller Preview, Simulation Output, 실제 Broadcast Output에서 동일한 SubtitleRenderer를 사용한다.

렌더링 코드를 복제하지 않는다.

정규화된 좌표를 사용하여 해상도가 달라도 비슷한 위치에 표시되게 한다.

---

## 자막 스타일 설정 창

별도의 Modal 또는 Modeless Dialog로 구현한다.

변경 내용은 실제 Live에 즉시 적용하지 않는다.

설정 창 Preview에서 먼저 확인하고, `적용`을 눌렀을 때 선택된 Preview 상태에 반영한다.

프리셋 기능:

* 생성
* 저장
* 불러오기
* 이름 변경
* 삭제
* 기본 지정
* 마지막 프리셋 복원

최소 3개의 기본 프리셋을 샘플로 제공한다.

```text
Lower Third
Centered Worship
Large Announcement
```

Key Color와 충돌 가능성이 있는 글자색이나 배경색에는 경고를 표시한다.

---

## PDF 라이브러리

사용자가 PDF 폴더를 선택할 수 있어야 한다.

파일 목록:

* 파일명 표시
* 수정 날짜 표시
* 파일명순 정렬
* 수정 날짜순 정렬
* 오름차순·내림차순
* 새로고침
* Drag and Drop

PDF를 선택하면 페이지 썸네일을 생성한다.

요구사항:

* 썸네일 지연 로딩
* UI 스레드 차단 금지
* 현재 보이는 썸네일 우선
* 캐시 사용
* PDF 변경 시 캐시 무효화
* 손상된 PDF는 목록에 오류 상태로 표시
* 하나의 PDF 오류 때문에 앱이 종료되지 않음

---

## PDF Preview와 출력

썸네일 클릭 시 선택한 채널의 Preview 페이지를 변경한다.

방송과 현장 중 대상 채널을 명확히 선택할 수 있어야 한다.

PDF 페이지 표시 방식:

```text
contain
aspect ratio 유지
여백 검은색
crop 금지
```

Controller Preview와 실제 출력은 동일한 PDF 렌더 결과 또는 동일한 렌더링 파이프라인을 사용한다.

Preview는 저해상도, Live는 출력 크기에 맞는 해상도를 사용할 수 있다.

Live 전환 전 고해상도 렌더가 준비되지 않았다면:

* 준비 중 상태 표시
* 기존 Live 유지
* 준비 완료 후 사용자가 TAKE 가능

---

## 키보드 조작

키보드 입력은 현재 활성 콘텐츠 패널을 기준으로 동작한다.

### 자막 패널

```text
Left       이전 Preview 카드
Right      다음 Preview 카드
Home       첫 카드
End        마지막 카드
Enter      Broadcast TAKE
```

### PDF 패널

```text
Left       이전 Preview 페이지
Right      다음 Preview 페이지
Home       첫 페이지
End        마지막 페이지
Enter      현재 대상 채널 TAKE
```

텍스트 입력 필드에 포커스가 있으면 Left/Right/Home/End를 콘텐츠 전환 단축키로 처리하지 않는다.

---

## 멀티모니터 설정

설정 창에서 다음 역할을 지정한다.

```text
Controller Screen
Broadcast Screen
Venue Screen
```

각 화면에 다음 정보를 표시한다.

```text
이름
해상도
좌표
배율
Primary 여부
```

Broadcast와 Venue에 같은 화면을 할당하려 할 경우 경고한다.

실제 모니터가 부족할 때는 Simulation Mode를 사용한다.

출력 화면은 사용자가 명시적으로 `출력 시작`을 누른 뒤에만 전체화면으로 연다.

프로그램 시작 직후 임의 모니터를 가리지 않는다.

---

## Simulation Mode

Mac 1모니터 환경에서 모든 기능을 검증할 수 있게 한다.

Simulation Mode에서는 실제 OutputWindow와 같은 렌더링 위젯을 다음 위치에 표시한다.

```text
Controller 내부
또는
사용자가 이동·크기 조절 가능한 별도 일반 창
```

Simulation Mode 기능:

* Broadcast 가상 화면
* Venue 가상 화면
* 각각 독립적인 Preview와 Live
* 1280×720, 1920×1080 등 가상 프로파일 선택
* 화면 연결·해제 시뮬레이션
* Device Pixel Ratio 시뮬레이션
* 실제 출력과 동일한 상태 전환

별도의 “가짜 출력 이미지”로 구현하지 않는다.

---

## 설정 저장

다음 값을 저장하고 복원한다.

* 자막 폴더
* PDF 폴더
* 파일 정렬
* Screen 역할
* Simulation Mode
* 가상 출력 해상도
* Controller 창 geometry
* 마지막 자막 파일
* 자막 group size
* 마지막 PDF
* 마지막 PDF 페이지
* 현재 스타일 프리셋
* Key Color

설정은 `platformdirs` 기반 사용자 설정 폴더에 JSON으로 저장한다.

Atomic write와 손상 복구를 구현한다.

---

## 종료 처리

프로그램 종료 순서:

1. 저장하지 않은 자막 변경사항 확인
2. Broadcast Live를 BLACK으로 전환
3. Venue Live를 BLACK으로 전환
4. 짧은 UI 이벤트 처리 기회 제공
5. 출력 창 닫기
6. 설정 저장
7. 앱 종료

종료 중 예외가 발생해도 가능한 범위에서 출력 창을 닫는다.

---

## 샘플 데이터

다음을 생성한다.

```text
sample_assets/subtitles/sample_service_ko.txt
sample_assets/pdfs/sample_service.pdf
scripts/generate_sample_assets.py
```

자막 파일에는 최소 20개의 자연스러운 한글 예배 안내 문장을 넣는다.

샘플 PDF는 최소 8페이지이며 다음을 포함한다.

* 16:9 페이지
* 4:3에 가까운 페이지
* 세로형 페이지
* 짧은 제목
* 긴 본문
* 큰 글씨
* 작은 글씨
* 페이지 번호

---

## 테스트

다음 명령으로 테스트할 수 있게 한다.

```bash
pytest
ruff check .
```

가능하면 다음도 제공한다.

```bash
mypy src
```

필수 테스트:

* 자막 파싱
* UTF-8-SIG
* 그룹화
* group size 변경
* 원본 줄 수정
* 추가·삭제·순서 이동
* 저장 round trip
* 미저장 상태
* 파일 정렬
* 설정 round trip
* 손상 설정 복구
* Preview/Live 분리
* TAKE
* TAKE BOTH
* 부분 실패 rollback
* PDF contain 크기 계산
* 썸네일 캐시
* Mock screen 탐지
* Simulation Mode
* 종료 시 BLACK 전환

GUI smoke test는 실제 모니터가 없어도 실행되어야 한다.

---

## CI

GitHub Actions를 작성한다.

테스트 환경:

```text
macos-latest
windows-latest
```

CI에서 실제 전체화면 모니터 테스트를 요구하지 않는다.

ScreenService와 OutputSurface를 Mock 또는 Offscreen 모드로 테스트한다.

---

## 문서

다음을 작성한다.

```text
README.md
docs/architecture.md
docs/user-guide.md
docs/atem-setup.md
```

`docs/atem-setup.md`에는 다음을 설명한다.

* PC Broadcast Output을 ATEM HDMI 입력에 연결
* 출력 화면에 녹색 Key Feed 표시
* ATEM에서 해당 입력을 Chroma Key 소스로 선택
* 카메라 입력을 배경으로 사용
* Key Color 조정
* PDF 전체화면 송출 시 Chroma Key를 해제하거나 입력을 직접 전환해야 함
* 앱은 Phase 1에서 ATEM을 자동 제어하지 않음

---

## 완료 기준

다음 항목이 모두 확인되어야 Phase 1 완료로 판단한다.

* Mac 1모니터에서 Simulation Mode 실행 가능
* Broadcast와 Venue 시뮬레이터가 독립적으로 동작
* Preview 변경이 Live를 바꾸지 않음
* TAKE를 눌렀을 때만 Live 변경
* TXT 파일 로드 가능
* n줄 그룹화 가능
* 원본 한 줄 단위 수정 가능
* 저장 전 원본 파일이 변경되지 않음
* 저장 후 원본 TXT가 올바르게 갱신됨
* 자막 스타일 변경과 프리셋 저장 가능
* 녹색 Key Feed에 자막 출력 가능
* PDF 폴더 라이브러리 생성 가능
* PDF 썸네일 클릭 가능
* PDF 페이지 Preview와 Live 출력 가능
* PDF가 종횡비를 유지하며 검은 여백으로 표시됨
* 파일명·수정 날짜 정렬 가능
* Drag and Drop 가능
* 설정이 다음 실행에서 복원됨
* 종료 시 모든 출력이 BLACK으로 전환됨
* 테스트 통과
* macOS와 Windows CI 통과

핵심 기능에 placeholder 또는 TODO가 남아 있으면 완료로 판단하지 마라.

Phase 1 구현 후에는 다음 형식으로 결과를 보고하라.

```text
1. 구현 기능
2. 아키텍처
3. 주요 파일
4. 테스트 명령과 결과
5. Simulation Mode 사용법
6. 실제 멀티모니터 사용법
7. ATEM 연결 방법
8. Windows에서 실기기 확인할 항목
9. 알려진 제한사항
10. Phase 2 진입 전 권장 수정사항
```

# Preview Monitor Control Routing Implementation Plan

**Goal:** 모니터 클릭을 클릭한 채널의 Preview 기반 개별 제어로 연결하고 TAKE 계열 버튼의 표시를 한국어로 바꾼다.

**Architecture:** `ControllerWindow`의 기존 애플리케이션 이벤트 필터에서 모니터 클릭을 감지하고, `ApplicationState`의 해당 채널 `preview_content`를 탭·대상 채널·포커스로 변환한다. 상태 전이와 키 처리 로직은 그대로 두며, 모니터 주도 탭 전환에서만 기존 Preview 복원을 억제한다.

**Tech Stack:** Python 3.12+, PySide6/Qt Widgets, pytest, pytest-qt

## Global Constraints

- Preview/Live 값과 준비 상태는 모니터 클릭으로 변경하지 않는다.
- Live 모니터를 클릭해도 해당 채널의 Preview 콘텐츠를 기준으로 한다.
- 방향키는 클릭한 채널의 Preview만 변경한다.
- 기존 TAKE, TAKE BOTH, 영상 Cue/재생 및 linked navigation 경로를 변경하지 않는다.
- 기존 `.DS_Store`와 sample asset 변경은 수정하거나 stage하지 않는다.

### Task 1: 한국어 버튼 문구 회귀 테스트와 변경

**Files:**
- Modify: `tests/gui/test_controller.py`
- Modify: `src/church_presenter/ui/controller_window.py`
- Modify: `src/church_presenter/ui/panels/subtitle_panel.py`
- Modify: `src/church_presenter/ui/panels/bible_panel.py`
- Modify: `src/church_presenter/ui/panels/instant_panel.py`
- Modify: `src/church_presenter/ui/panels/pdf_panel.py`
- Modify: `src/church_presenter/ui/panels/video_panel.py`
- Modify: `src/church_presenter/ui/panels/black_panel.py`

- [x] 버튼 텍스트 테스트를 `송출`, `동시 송출`, `송출 화면 적용`, `현장 화면 적용` 기대값으로 먼저 변경한다.
- [x] 테스트가 기존 영어 문구 때문에 실패하는지 확인한다.
- [x] 버튼 생성 및 반응형 PDF 버튼 갱신 문자열만 변경한다.
- [x] variant, signal, enable 상태가 유지되는지 focused test로 확인한다.

### Task 2: Preview 기반 모니터 클릭 라우팅

**Files:**
- Modify: `tests/gui/test_controller.py`
- Modify: `src/church_presenter/ui/controller_window.py`
- Modify: `src/church_presenter/ui/panels/video_panel.py`

- [x] 성경 Preview/PDF Live 조합의 송출 Live 클릭 테스트를 추가하고 탭 이동과 네 상태값 보존을 검증한다.
- [x] 송출 Preview 클릭도 같은 결과를 내는 테스트를 추가한다.
- [x] 현장 PDF Preview 클릭 후 대상이 현장 단일 채널로 바뀌고 방향키가 현장만 변경하는 테스트를 추가한다.
- [x] 테스트가 클릭 라우팅 부재로 실패하는지 확인한다.
- [x] `VideoPanel.set_target_role(role: ChannelRole) -> None`을 추가해 영상 대상 선택을 명시적으로 제공한다.
- [x] 모니터 자손의 왼쪽 클릭을 채널로 해석하는 helper를 `ControllerWindow`에 추가한다.
- [x] Preview 종류를 탭·포커스로 매핑하는 helper와 범위 제한 탭 복원 guard를 구현한다.
- [x] 기존 키보드 처리기로 방향키를 보내 focused test를 통과시킨다.

### Task 3: 회귀 검증과 문서 정합성

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/superpowers/plans/2026-08-09-preview-monitor-control-routing.md`

- [x] 사용자 가이드에 모니터 클릭이 해당 채널 Preview를 제어한다는 규칙과 버튼 문구를 기록한다.
- [x] `tests/gui/test_controller.py` 전체를 offscreen으로 실행한다.
- [x] 전체 non-media 테스트를 offscreen으로 실행한다.
- [x] `ruff check src tests`와 `mypy src/church_presenter`를 실행한다.
- [x] diff를 전체 검토해 상태 변경, 비동기 준비, 영상 제어 회귀가 없는지 확인한다.

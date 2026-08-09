# Church Presenter 개발 인수인계

마지막 갱신: 2026-07-14  
대상 범위: Phase 1 + Phase 2  
목적: 다음 개발 세션에서 이전 오류, 시행착오, 설계 의도와 검증 기준을 바로 이어서
확인하기 위한 기록이다.

이 문서는 현재 코드에 반영된 사실만 기록한다. 새 세션에서는 먼저 루트의
`AGENTS.md`를 읽고, 이 문서와 현재 작업 트리를 확인한 뒤 작업을 시작한다.

## 현재 검증 기준선

마지막 전체 검증 결과는 다음과 같다.

```text
ruff check .                         통과
mypy src                             46개 소스 파일 통과
QT_QPA_PLATFORM=offscreen pytest -q -m "not media_integration"  56 passed
QT_QPA_PLATFORM=offscreen pytest -q -m media_integration        1 passed
```

PyMuPDF가 사용하는 SWIG 타입에서 비치명적 deprecation warning 5건이 출력된다.
테스트 실패는 아니며 애플리케이션 코드에서 발생한 경고도 아니다.

현재 작업 트리에는 기존 사용자 변경과 아직 추적되지 않은 프로젝트 파일이 많다.
새 세션에서 `git reset --hard`, `git clean` 또는 일괄 checkout으로 정리하지 않는다.
항상 `git status --short`로 범위를 먼저 확인한다.

## 운영상 반드시 유지할 규칙

- Preview 선택만으로 Live를 바꾸지 않는다.
- TAKE는 해당 채널의 준비가 완료된 경우에만 Live를 바꾼다.
- TAKE BOTH는 두 채널 준비 상태를 모두 검증한 뒤 원자적으로 적용한다.
- TAKE BOTH 실패 시 양쪽의 기존 Live를 유지한다.
- Venue에는 자막을 보내지 않는다.
- 종료 및 화면 분리 시 안전 상태는 BLACK이다.
- 자막 원본 한 줄 목록이 source of truth이며 그룹 카드는 파생 데이터다.
- PDF 재정렬은 원본 PDF를 수정하지 않는 파생 순서다.
- 무거운 PDF 검색과 렌더링은 UI 스레드에서 실행하지 않는다.

## 해결된 오류와 시행착오

### 1. TAKE 실행 시 `str.value` 예외

증상:

```text
Traceback (most recent call last):
  File ".../controller_window.py", line 287, in take
    self.status.setText(f"{role.value.title()} TAKE 완료")
                           ^^^^^^^^^^
AttributeError: 'str' object has no attribute 'value'
```

원인:

- `ChannelRole`을 기대하는 메서드에 Qt Signal이 `role.value`인 문자열을 전달했다.
- Python 타입 힌트와 달리 Qt Signal 경계에서는 Enum이 자동 보존되지 않는다.

최종 해결:

- `ControllerWindow._normalize_role()`에서 `ChannelRole | str`을
  `ChannelRole`로 정규화한다.
- `set_preview()`, `mark_preview_ready()`, `take()` 진입 시 정규화한다.
- 회귀 테스트는 `test_take_normalizes_string_role_from_qt`이다.

주의:

- 새 Qt 슬롯이 채널 역할을 받을 때도 UI 경계에서 정규화한다.
- 문자열이 들어올 수 있는데 `.value`를 직접 호출하는 코드를 다시 만들지 않는다.

### 2. 자막과 PDF를 한 키보드로 진행할 수 없었던 문제

초기 증상:

- 자막과 PDF가 탭으로 분리되어 있었다.
- 활성 탭에서만 방향키가 동작해 예배 중 자막과 PDF를 동시에 진행할 수 없었다.

첫 해결 시도:

- Controller 중앙에 `자막 + PDF 동시 진행`, `함께 이전`, `함께 다음`,
  `TAKE BOTH`를 추가했다.
- 체크박스가 켜져 있으면 현재 포커스와 무관하게 모든 방향키를 동시 이동으로
  처리했다.

첫 시도의 문제:

- 동시 진행 체크박스가 켜진 상태에서는 자막 탭이나 PDF 탭으로 포커스를 옮겨도
  개별 이동을 할 수 없었다.
- 체크박스 상태만으로 키보드 문맥을 판단하면 탭별 단축키를 가로채게 된다.

최종 해결:

- 키보드 문맥을 체크 상태가 아니라 포커스 영역으로 구분한다.
- 중앙 동시 진행 영역에 포커스가 있으면 Left/Right/Home/End를 함께 이동으로,
  Enter를 TAKE BOTH로 처리한다.
- 자막 탭에 포커스가 있으면 자막만 이동하고 Enter는 Broadcast TAKE다.
- PDF 탭에 포커스가 있으면 PDF만 이동하고 Enter는 선택 채널 TAKE다.
- `QLineEdit`, spin box, combo box에서는 단축키를 가로채지 않는다.
- 탭 내부의 일반 버튼은 고유 Enter 동작을 유지한다.

관련 코드:

- `ControllerWindow.eventFilter()`
- `ControllerWindow._keyboard_area()`
- `ControllerWindow._handle_navigation_key()`

관련 테스트:

- `test_keyboard_navigation_does_not_steal_text_edit_keys`
- `test_focused_content_tab_keeps_individual_navigation`
- `test_linked_navigation_advances_subtitle_and_venue_pdf`

### 3. 중앙 영역 Enter가 TAKE BOTH 대신 포커스 버튼을 실행할 수 있던 문제

원인:

- `QPushButton`과 `QCheckBox` 같은 자식 위젯은 Enter를 `QMainWindow.keyPressEvent()`
  이전에 소비할 수 있다.
- 메인 창의 `keyPressEvent()`만 재정의해서는 중앙의 `함께 이전` 버튼에 포커스가
  있을 때 Enter를 TAKE BOTH로 보장할 수 없다.

최종 해결:

- `QApplication` event filter에서 중앙 영역의 키를 자식 위젯보다 먼저 처리한다.
- 중앙 영역의 Enter와 숫자 키패드 Enter 모두 `take_linked_previews()`로 전달한다.
- 창을 닫을 때 event filter를 제거한다.

폐기한 접근:

- 중앙 버튼별 `keyPressEvent()` 재정의: 중복 코드와 누락 가능성이 커서 사용하지
  않았다.
- `QShortcut` 다중 등록: 텍스트 편집 및 탭별 우선순위 충돌이 생기기 쉬워
  사용하지 않았다.

### 4. offscreen GUI 테스트에서 포커스 복귀가 인식되지 않았던 문제

테스트 중 나타난 증상:

```text
test_keyboard_navigation_does_not_steal_text_edit_keys
expected preview_index == 1, actual preview_index == 0
```

원인:

- `window.setFocus()` 뒤에도 offscreen Qt의 `QApplication.focusWidget()`이 이전
  `QLineEdit`를 잠시 반환했다.
- 실제 키 이벤트는 Controller에 전달됐지만 오래된 focusWidget 값 때문에 텍스트
  입력으로 오판했다.

최종 해결:

- event filter가 받은 `watched` 위젯을 실제 키 이벤트 대상자로 우선 사용한다.
- 대상자가 없을 때만 `QApplication.focusWidget()`을 사용한다.

주의:

- 이 보정 없이 focusWidget만 신뢰하면 CI에서는 실패하고 실제 GUI에서는 간헐적으로
  다른 문맥으로 처리될 수 있다.

### 5. 중앙 동시 이동이 콘텐츠 종류를 무시하던 문제

첫 구현의 문제:

- 함께 이동 버튼이 Broadcast/Venue Preview 상태를 보지 않고 자막과 PDF 커서를
  무조건 둘 다 이동했다.
- 활성화 시 PDF 대상 채널을 Venue로 강제로 바꾸는 방식은 Broadcast Preview에
  PDF가 있는 경우와 맞지 않았다.

최종 해결:

- `ControllerWindow._linked_preview_targets()`가 실제 Preview 콘텐츠 종류를 읽는다.
- Broadcast Preview가 자막이면 자막 커서를 이동한다.
- PDF가 들어 있는 Broadcast 또는 Venue Preview만 PDF 이동 대상에 포함한다.
- BLACK인 Preview는 그대로 둔다.
- 두 Preview가 PDF면 두 채널을 같은 선택 페이지로 준비한다.
- 동시 진행 활성화만으로 PDF 대상 combo를 Venue로 강제 변경하지 않는다.

관련 테스트:

- `test_linked_navigation_uses_each_preview_content_type`

현재 한계:

- PDF 패널에는 하나의 현재 문서/페이지 커서만 있다. Broadcast와 Venue에 서로 다른
  PDF 문서가 Preview 중인 상태에서 각각의 문서를 독립적으로 다음 페이지로 넘기는
  기능은 아직 없다. 두 채널이 모두 PDF 이동 대상이면 현재 PDF 패널의 문서와
  페이지를 양쪽에 준비한다.

### 6. 중앙 버튼이 비활성화되어 작동하지 않는 것처럼 보이던 문제

원인:

- 초기 구현은 동시 진행 체크박스가 꺼져 있으면 `함께 이전`, `함께 다음`,
  `TAKE BOTH`를 비활성화했다.
- 사용자는 버튼을 먼저 누르고 모드를 시작할 수 없었다.

최종 해결:

- 중앙 버튼은 항상 활성 상태를 유지한다.
- 버튼이나 중앙 영역 단축키를 사용하면 동시 진행 체크박스를 자동으로 켠다.
- 중앙 이동 후 상태줄에 자막 위치와 PDF 재생 순서 위치를 표시한다.

### 7. 동시 진행 체크박스가 배경과 구분되지 않던 문제

증상:

- 체크박스와 글자색이 중앙 배경과 비슷해 상태를 빠르게 구분하기 어려웠다.

최종 해결:

- `SyncContentCheck` 전용 스타일을 추가했다.
- 꺼짐은 흰 배경/진한 테두리, 켜짐은 파란 배경/흰 글자/노란 indicator를 쓴다.
- 색에만 의존하지 않도록 `켜짐`, `꺼짐` 문구도 표시한다.
- 중앙 영역에 키보드 포커스가 있으면 굵은 남색 테두리를 표시한다.

관련 코드와 테스트:

- `ui/styles.py`의 `QCheckBox#SyncContentCheck`
- `test_sync_checkbox_has_explicit_on_off_label`

### 8. PDF 썸네일 정렬 정책

- 썸네일은 `Static`, 좌→우 흐름, 줄바꿈 그리드로 표시한다.
- 페이지 순서는 항상 원본 PDF의 1쪽부터 오름차순이다.
- 내부 드래그 앤 드롭은 비활성화한다.
- 이전 설정의 `pdf_page_orders` 값은 호환성을 위해 읽을 수 있지만 화면에는 적용하지
  않는다.
- 비동기 썸네일 완료 시 `_item_for_page()`가 UserRole의 원본 페이지 번호로 항목을
  찾아 갱신한다.

### 9. PDF 양쪽 송출 때 Send to Both를 매번 눌러야 했던 문제

최종 해결:

- PDF 패널에 Venue와 Broadcast 대상 체크박스를 각각 표시한다.
- 두 체크박스를 모두 켠 상태에서 페이지를 선택하거나 이동하면 두 Preview를 자동으로
  준비한다.
- `pdf_link_outputs` 설정으로 다음 실행에 복원한다.
- PDF 양쪽 연동과 자막+PDF 동시 진행은 서로 다른 운용 모드이므로 한쪽을 켜면
  다른 쪽을 끈다.

주의:

- PDF 양쪽 연동은 같은 PDF 페이지를 Broadcast와 Venue에 보내는 기능이다.
- 자막+PDF 동시 진행은 Preview의 서로 다른 콘텐츠 종류를 함께 넘기는 기능이다.

### 10. PDF 동시/개별 렌더 작업이 준비 상태를 뒤늦게 덮어쓸 위험

문제 상황:

- PDF를 양쪽 Preview로 준비한 직후 PDF 탭에서 한 채널만 다른 페이지로 이동하면,
  이전 양쪽 렌더 요청이 늦게 완료될 수 있다.
- 오래된 완료 신호가 새 페이지의 준비 상태를 잘못 ready로 만들면 렌더되지 않은
  Preview를 TAKE할 위험이 있다.

최종 해결:

- 단일 채널 준비를 시작할 때 기존 `_both_job_tokens`와 pending 상태를 취소한다.
- 양쪽 준비를 시작할 때 기존 단일 `_page_job_token`을 취소한다.
- 토큰이 현재 요청과 일치하는 완료 신호만 처리한다.

주의:

- PDF 비동기 경로를 수정할 때 content 상태와 readiness 상태가 같은 요청 토큰을
  가리키는지 반드시 확인한다.
- 취소 코드를 제거하거나 빈 예외 처리로 대체하지 않는다.

### 11. Qt Multimedia 64비트 Signal 직접 연결 실패

`QMediaPlayer.positionChanged(qlonglong)`와 `durationChanged(qlonglong)`을 사용자
정의 `Signal(int)`에 직접 연결하면 일부 PySide6 빌드에서 backend 생성 중
`RuntimeError`가 발생했다. 현재 `QtMediaBackend`는 lambda 경계에서 `int()`로
정규화한 뒤 Signal을 emit한다. Qt Signal끼리 타입이 비슷해 보여도 직접 연결하지
말고 명시적 경계 변환을 유지한다.

### 12. 동기 Mock backend가 CUE 표시를 LOADING으로 덮어씀

Mock의 `load()`는 첫 프레임을 동기 emit한다. 처음에는 `cue_preview()` 호출 뒤에
LOADING 라벨을 썼기 때문에 완료 콜백의 CUE가 다시 LOADING으로 바뀌었다. 현재는
LOADING을 먼저 설정하고 backend를 호출한다. 실제 backend가 비동기라고 가정해
호출 이후 상태를 덮어쓰지 않는다.

### 13. Ended된 같은 영상을 다시 TAKE할 때 종료 backend 재사용

같은 경로라는 이유만으로 기존 Live backend를 재사용하면 Ended/Error/Stopped 뒤
새 Cue backend가 준비됐어도 종료된 player가 남았다. 현재 같은 경로 재사용은
`LIVE_PAUSED`, `PLAYING`, `PAUSED`에서만 허용한다. 종료 후 같은 파일 재송출 회귀
테스트는 `test_video_ended_and_error_each_turn_live_black`이다.

### 14. 샘플 영상 headless 생성

외부 FFmpeg가 없는 Mac에서 Qt recorder의 H.264 VideoToolbox session 생성이
실패했다. 스크립트는 외부 FFmpeg가 있으면 H.264/AAC를 생성하고, 없으면 Qt
Multimedia의 software MPEG-4 encoder로 12초 MP4를 만든다. 폰트/그림 렌더링 때문에
fallback은 `QCoreApplication`이 아니라 `QGuiApplication`을 사용해야 한다.

### 15. PLAYING인데 영상이 0번 프레임에 고정

증상은 `PLAYING` 상태와 프레임 Signal은 계속 발생하지만 position이 0ms에서 증가하지
않는 것이었다. `QMediaPlayer`가 재생 중 `BufferedMedia`를 다시 emit할 때마다
`QtMediaBackend._media_status_changed()`가 초기 로딩으로 오인해 position을 0으로
되돌리고 Preview priming을 다시 시작한 것이 원인이었다.

현재 Loaded/Buffered 초기화는 backend 상태가 `LOADING`일 때 한 번만 수행한다.
회귀 테스트 `test_qt_backend_cues_first_frame_and_plays`는 `PLAYING`뿐 아니라 position이
500ms 이상 증가하고 Live 프레임 픽셀 값이 실제로 달라지는지 확인한다. 미디어 테스트를
다시 상태 확인만으로 축소하지 않는다.

### 16. 첫 프레임 준비 전에 영상 패널 TAKE 가능

Controller의 상단 TAKE는 채널 readiness를 반영했지만 영상 패널 내부 TAKE/TAKE BOTH는
항상 활성화되어 있었다. 파일 선택 직후 누르면 정상적인 비동기 준비 중에도
`영상 첫 프레임이 아직 준비되지 않았습니다`가 표시되어 backend 오류처럼 보였다.

현재 영상 패널은 Broadcast/Venue의 실제 첫 프레임 readiness를 별도로 추적한다.
TAKE는 선택 채널 준비 후, TAKE BOTH는 두 채널 모두 준비된 뒤에만 활성화된다.
`Content.video()`와 완료 Signal 경로는 resolve된 절대 경로로 비교하며 느린 decoder의
Cue timeout은 10초다. 회귀 테스트는 `test_video_take_waits_until_a_real_first_frame`과
`test_video_content_normalizes_relative_paths`다.

### 17. 같은 영상 재Cue 시 첫 프레임 timeout

`QMediaPlayer.setSource()`에 현재와 같은 URL을 다시 전달하면 macOS Qt Multimedia가
소스 변경을 생략할 수 있다. 이때 `LoadedMedia`와 새 `videoFrameChanged`가 발생하지 않아
10초 후 `첫 영상 프레임을 준비하지 못했습니다`가 표시됐다. 단일 최초 Cue는 성공하고
같은 파일을 다시 선택했을 때만 실패할 수 있어 코덱 문제로 오인하기 쉬웠다.

현재 `QtMediaBackend.load()`는 다음 순서를 보장한다.

1. 기존 source와 이전 decoded frame 수신을 비활성화한다.
2. 빈 `QUrl`로 source를 명시적으로 해제한다.
3. event loop 다음 tick에 세대 번호가 일치하는 source만 새로 설정한다.
4. Loaded/Buffered 뒤 첫 프레임을 위해 재생하고, 느린 decoder에는 1.5초/4초에 seek 후
   priming을 한 번 더 시도한다.
5. 첫 프레임을 받으면 Pause와 0초 seek 후에만 Preview CUE를 완료한다.

로드 중 `playbackStateChanged`가 LOADING/priming 상태를 덮지 못하게 했고, 오류 또는
timeout에서는 이전 readiness와 프레임을 반드시 제거한다. timeout 로그에는 Qt의 media
status, playback state, position, duration, error string을 남긴다. 같은 영상의 새 Cue가
준비된 경우 TAKE는 기존 Live decoder를 재사용하지 않고 새 decoder로 교체한다.

함께 수정한 안전장치는 비영상 Live에서 영상 Stop을 눌러 BLACK으로 바꾸지 않는 것,
PDF/BLACK이 영상 Preview를 대체하면 영상 TAKE readiness를 무효화하는 것, 유효한 Live
영상 상태에서만 Play/Pause/Seek/Stop을 허용하는 것이다.

실제 Qt 회귀 테스트 `test_qt_backend_cues_both_then_recues_same_source`를 제거하거나 Mock
테스트로 대체하지 않는다. 이 문제는 Mock backend에서는 재현되지 않는다.

### 18. TAKE BOTH 후 Broadcast만 재생

TAKE BOTH는 두 Preview backend를 각각 Live로 교환했지만 영상 패널과 키보드의 Play가
항상 현재 `target_role` 한 곳에만 전달되어 Venue는 첫 프레임에 남았다. 현재 같은 영상이
양쪽 Live에 TAKE BOTH되면 `VideoPlaybackManager`가 두 역할을 transport 그룹으로
연결한다. Play/Pause/Stop/Restart/Seek는 선택 채널과 무관하게 두 backend에 적용된다.

한쪽에서 개별 TAKE 또는 다른 콘텐츠로 전환하거나 한 decoder가 종료/오류 상태가 되면
그룹을 해제한다. 따라서 이후 transport 명령이 의도하지 않은 다른 Live에 전달되지
않는다. 실제 Qt 회귀 테스트 `test_qt_linked_transport_plays_both_live_channels`는 두
decoder의 position이 모두 500ms 이상 증가하는지 확인한다.

두 decoder의 동일 오디오가 기본 출력 장치에서 중복 재생되지 않도록 연동 중 Venue
backend는 강제 음소거하고 Broadcast backend만 오디오를 출력한다. 그룹 해제 시 두
backend 모두 사용자의 전역 영상 음소거 설정으로 복원한다.

### 19. Windows Live 영상 프레임 변환으로 Controller까지 버벅임

기존 `QtMediaBackend`는 `QVideoSink`의 모든 Live 프레임에 `toImage()`를 호출하고,
Controller/Simulation/실제 출력의 `OutputSurface`가 각각 `QPainter.drawImage()`로
다시 그렸다. Windows 하드웨어 디코딩 프레임에서는 GPU→CPU readback과 색상 변환이
매 프레임 발생할 수 있고, GUI 이벤트 루프가 밀리면 영상과 Controller가 함께
끊겼다.

현재 Preview 첫 프레임만 `QImage`로 변환한다. Live에서는 `QVideoFrame`을 유지해
각 `OutputSurface`의 `QVideoWidget.videoSink()`로 전달한다. 콘텐츠 전환 시에만 마지막
네이티브 프레임을 한 번 이미지로 고정해 기존 250ms fade를 수행한다. 회귀 테스트는
`test_qt_backend_cues_first_frame_and_plays`에서 Live 타입이 `QVideoFrame`인지,
`test_output_surface_uses_native_video_frame_until_content_changes`에서 sink 표시와
해제를 확인한다.

### 20. 로컬 음악 첫 Play가 로딩 완료 직후 Pause로 덮임

오디오 `LoadedMedia` 처리에서 `loaded.emit()` 뒤 `player.pause()`를 호출했다.
`loaded` 콜백은 pending Play를 동기 실행할 수 있으므로 실제 순서가
`Play → Pause`가 되었고, Windows backend에서는 첫 클릭이 PAUSED로 끝날 수 있었다.

현재 오디오 backend는 prepared Pause를 먼저 확정한 뒤 `loaded`를 알린다. 따라서
콜백의 Play가 마지막 transport 명령이 된다. 실제 WAV와 `QMediaPlayer`를 사용하는
`test_qt_local_audio_first_play_stays_playing`은 첫 클릭 후 PLAYING 유지와 position
증가를 확인한다.

### 21. Windows에서 YouTube 정보는 보이지만 오디오 재생은 시작되지 않음

메타데이터 조회 뒤 실제 재생만 별도의 libmpv와 Windows DLL에 의존해 macOS에서는
정상인데 Windows에서는 시작되지 않을 수 있었다. 영상의 YouTube 재생은 이미 Qt
Multimedia의 progressive 스트림 경로에서 정상 동작하고 있었다.

현재 로컬 음악과 YouTube 음악은 모두 오디오 전용 `QtMediaBackend`를 사용한다.
YouTube 음악은 영상과 같은 progressive 스트림을 해석하지만 video sink는 만들지 않고
`QAudioOutput`만 연결한다. `python-mpv`와 `mpv-2.dll` 요구사항은 제거했다. 오류 로그에는
Qt media/playback 상태, hasAudio/hasVideo, 원본 URL, 선택 출력 장치, 볼륨과 음소거를
남겨 Windows 장치·codec 문제를 구분할 수 있다.

## 다시 사용하지 않을 접근 요약

| 접근 | 문제가 된 이유 | 현재 대안 |
|---|---|---|
| 체크박스 상태만으로 전역 방향키 처리 | 탭별 개별 이동을 가로챔 | 포커스 영역별 키보드 문맥 |
| `QMainWindow.keyPressEvent()`만 사용 | 자식 버튼이 Enter를 먼저 소비함 | QApplication event filter |
| `focusWidget()`만 신뢰 | offscreen CI에서 이전 입력 위젯이 남음 | 실제 event target 우선 |
| 썸네일 행 번호를 PDF 페이지로 사용 | 재정렬 후 잘못된 페이지와 이미지 연결 | UserRole의 원본 페이지 ID |
| 동시 진행 활성화 시 Venue를 강제 선택 | 실제 Preview 콘텐츠와 불일치 | Preview ContentType 기반 대상 계산 |
| 체크가 꺼지면 중앙 버튼 비활성화 | 기능 발견성과 즉시 조작성이 낮음 | 버튼 사용 시 자동 활성화 |
| 비동기 요청을 취소하지 않고 새 요청 시작 | 오래된 ready 신호가 새 상태를 오염 | 단일/양쪽 요청 상호 취소와 토큰 검증 |

## 주요 코드 진입점

| 관심 영역 | 파일/구성요소 |
|---|---|
| Preview/Live, TAKE, 키보드 라우팅 | `src/church_presenter/ui/controller_window.py` |
| PDF 선택, 재정렬, 비동기 준비 | `src/church_presenter/ui/panels/pdf_panel.py` |
| 자막 원본/그룹 카드 탐색 | `src/church_presenter/ui/panels/subtitle_panel.py` |
| 채널 상태와 원자적 TAKE BOTH | `src/church_presenter/domain/state.py` |
| 설정과 PDF별 페이지 순서 | `src/church_presenter/domain/models.py` |
| 공통 고대비 UI 스타일 | `src/church_presenter/ui/styles.py` |
| Controller 회귀 테스트 | `tests/gui/test_controller.py` |
| PDF 회귀 테스트 | `tests/gui/test_pdf_panel.py` |
| 영상 prepared/live player 교환 | `src/church_presenter/media/video_manager.py` |
| Qt/Mock backend | `src/church_presenter/media/qt_media_backend.py`, `mock_backend.py` |
| 음악 반복·자동 Pause 정책 | `src/church_presenter/media/audio_controller.py` |
| 영상/음악 UI | `src/church_presenter/ui/panels/video_panel.py`, `audio_panel.py` |
| Phase 2 회귀 테스트 | `tests/unit/test_media.py`, `tests/gui/test_media_panels.py` |

## 다음 세션 시작 절차

```bash
cat AGENTS.md
cat docs/session-handoff.md
git status --short
.venv/bin/ruff check .
.venv/bin/mypy src
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q -m "not media_integration"
```

키보드나 PDF 동작을 변경할 경우 최소한 다음을 다시 확인한다.

1. 텍스트 입력 중 Left/Right가 자막을 넘기지 않는가.
2. 중앙 영역에서 Left/Right가 Preview 콘텐츠 종류별로 이동하는가.
3. 중앙 영역 Enter가 포커스 버튼과 관계없이 TAKE BOTH인가.
4. 동시 진행이 켜져 있어도 자막/PDF 탭 포커스에서는 개별 이동하는가.
5. PDF 재정렬 후 썸네일, Preview, 페이지 번호, 다음 이동 순서가 일치하는가.
6. PDF 준비 실패 또는 취소 시 기존 Live가 유지되는가.
7. 종료 시 두 출력이 BLACK으로 전환되는가.

## 실기기에서 남은 검증

- Windows 3모니터 환경의 Controller/Broadcast/Venue 역할 지정
- ATEM Mini Pro 입력으로 실제 KEY_FEED 색상과 자막 가독성 확인
- Windows 디스플레이 배율 125%, 150%에서 중앙 컨트롤 레이아웃 확인
- 메인 Enter와 숫자 키패드 Enter가 중앙 영역에서 동일하게 TAKE BOTH인지 확인
- 빠른 연속 방향키 입력 중 PDF 취소/완료 순서와 Live 안정성 확인
- 모니터 분리 후 BLACK 전환과 수동 복구 확인

Windows의 실제 코덱, 오디오 장치, HDMI, 다중 decoder 성능은 자동 테스트로 완료
판정하지 않는다. `docs/windows-media-test.md` 체크리스트로 Phase 3에서 검증한다.

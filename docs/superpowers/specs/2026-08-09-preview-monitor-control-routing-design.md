# Preview Monitor Control Routing Design

## Goal

상단의 송출·현장 Preview/Live 모니터를 클릭하면 클릭한 채널의 현재 Preview 콘텐츠를
제어하는 하단 탭으로 이동하고, 방향키가 그 채널의 Preview만 조작하도록 한다. 동시에
Controller의 TAKE 계열 버튼을 `송출`과 `동시 송출`이라는 한국어 문구로 표시한다.

## Confirmed Interaction

상단 네 모니터는 모두 클릭할 수 있다.

- 송출 Preview 또는 송출 Live 클릭 → 송출 Preview 콘텐츠를 기준으로 제어 전환
- 현장 Preview 또는 현장 Live 클릭 → 현장 Preview 콘텐츠를 기준으로 제어 전환

클릭한 모니터가 Live여도 Live 콘텐츠 종류는 판정에 사용하지 않는다. 예를 들어 송출
Preview가 성경이고 송출 Live가 PDF이면 송출 Live 클릭도 성경 탭과 성경 방향키 제어를
활성화한다.

## State Safety

`ApplicationState`는 계속 Preview와 Live 콘텐츠의 유일한 기준이다. 모니터 클릭은 다음
값을 변경하지 않는다.

- `broadcast.preview_content`
- `broadcast.live_content`
- `venue.preview_content`
- `venue.live_content`
- 각 채널의 Preview 준비 상태
- 비디오 Preview/Live decoder 및 재생 상태

클릭은 UI의 현재 탭, 콘텐츠 패널의 대상 채널 선택, 키보드 포커스만 변경한다. TAKE,
TAKE BOTH, Preview 준비, PDF 렌더링, 영상 Cue와 같은 기존 상태 전이 경로는 수정하지
않는다.

## Monitor Click Detection

`ControllerWindow`가 이미 애플리케이션 이벤트 필터를 통해 키보드 입력을 중앙 처리하므로,
같은 이벤트 필터에서 왼쪽 마우스 클릭의 대상 위젯이 네 `ChannelMonitor` 중 어느 것의
자손인지 판정한다. 이 방식은 모니터 프레임뿐 아니라 헤더, 라벨, 렌더링 surface를 클릭한
경우도 동일하게 처리한다.

마우스 이벤트는 소비하지 않는다. 클릭 라우팅을 수행한 후 `False`를 반환해 기존 surface
처리와 Qt 이벤트 전파를 유지한다.

## Preview-to-Control Routing

클릭한 채널의 `preview_content`를 다음과 같이 대응한다.

| Preview 콘텐츠 | 선택할 하단 영역 | 포커스 및 채널 처리 |
| --- | --- | --- |
| 찬양 자막 | 찬양 | 찬양 카드 목록에 포커스 |
| 성경 자막 | 성경 | 성경 콘티 목록에 포커스 |
| 즉석 문구 | 기타 | 즉석 패널 자체에 포커스 |
| PDF | PDF | PDF 대상을 클릭한 한 채널로 바꾸고 썸네일 목록에 포커스 |
| 영상 | 영상 | 영상 제어 채널을 클릭한 채널로 바꾸고 파일 목록에 포커스 |
| BLACK/단색 | 기타 | 빈 화면 영역을 표시하되 Preview/Live는 변경하지 않음 |

현장 Preview에는 도메인 검증상 자막이 들어갈 수 없으므로 정상 UI 흐름에서는 PDF, 영상,
BLACK/단색만 라우팅된다. 알 수 없는 자막 source는 기존 호환 동작과 동일하게 찬양으로
취급한다.

PDF가 양쪽 Preview 대상으로 설정된 상태에서 한 채널 모니터를 클릭하면 PDF 패널 대상을
그 한 채널로 좁힌다. 이후 방향키는 클릭한 채널의 PDF Preview만 이동시키며 반대 채널은
유지한다. 영상도 같은 원칙으로 제어 채널 선택만 바꾼다.

## Tab Transition Guard

기존 `_content_tab_changed()`는 운영자가 찬양·성경 탭을 직접 선택할 때 그 패널의 마지막
선택을 송출 Preview에 복원한다. 모니터 클릭에 이 동작이 실행되면 클릭만으로 Preview가
바뀔 수 있다.

따라서 모니터 라우팅 중에만 적용되는 범위 제한 guard를 두고, 해당 guard가 활성화된 탭
전환에서는 `restore_preview()`를 생략한다. 일반적인 탭 클릭은 기존 복원 동작을 그대로
사용한다. guard는 `try/finally`로 즉시 해제해 예외가 발생해도 이후 탭 동작에 영향을 주지
않는다.

## Keyboard Behavior

새로운 키보드 상태나 전역 활성 채널을 추가하지 않는다. 탭과 포커스가 이동한 뒤 기존
`_keyboard_area()`와 `_handle_navigation_key()`가 입력을 처리한다.

- 찬양/성경: Left·Right와 Home·End는 해당 송출 Preview 자막만 이동
- PDF: Left·Right와 Home·End는 클릭한 채널의 PDF Preview만 이동
- 영상: 기존 영상 탭의 선택 채널 동작 유지
- 즉석 문구: 패널 자체 포커스에서 기존 즉석 이전·다음 동작 사용
- BLACK/단색: 이동 가능한 순서가 없으므로 기타 탭 표시만 수행

클릭한 채널과 무관한 Preview 및 양쪽 Live는 방향키 조작 전후 모두 유지되어야 한다.

## Button Copy

내부 메서드, signal, object name, 상태 모델의 TAKE 용어는 호환성을 위해 유지하고 버튼의
표시 문자열만 바꾼다.

- `TAKE BOTH` → `동시 송출`
- `TAKE` → `송출`
- `TAKE selected channel` → `송출`
- `TAKE 송출` → `송출 화면 적용`
- `TAKE 현장` → `현장 화면 적용`

버튼 크기, variant 속성, enable 조건, signal 연결은 변경하지 않는다.

## Error and Edge Handling

- 아직 준비 중인 Preview도 종류에 따른 탭 전환은 허용하지만 준비 상태는 바꾸지 않는다.
- 빈 PDF/영상 목록에서는 탭과 대상 채널만 전환하고 기존 Preview를 유지한다.
- 오른쪽 클릭과 모니터 밖 클릭은 제어 전환을 일으키지 않는다.
- Live와 Preview 콘텐츠 종류가 달라도 항상 Preview 종류를 사용한다.
- 탭 전환 중 Preview 복원 signal이 억제되어 클릭 자체가 출력 상태를 바꾸지 않는다.

## Testing

GUI 테스트는 다음을 검증한다.

1. 모든 TAKE 계열 버튼이 요구된 한국어 문구를 표시하고 기존 variant를 유지한다.
2. 송출 Live 클릭이 송출 Preview의 성경 탭으로 이동하며 네 Preview/Live 값을 보존한다.
3. 송출 Preview와 송출 Live가 같은 라우팅 결과를 만든다.
4. 현장 Live 클릭이 현장 Preview의 PDF 탭과 현장 단일 대상을 선택한다.
5. 이후 PDF 방향키 입력이 현장 Preview만 이동시키고 송출 PDF Preview와 양쪽 Live를
   변경하지 않는다.
6. Live 콘텐츠 종류가 PDF이고 Preview가 성경이어도 성경으로 라우팅한다.
7. 일반적인 수동 찬양·성경 탭 전환의 기존 Preview 복원 동작은 유지한다.
8. 기존 linked navigation, TAKE, TAKE BOTH, 영상 및 출력 테스트가 계속 통과한다.

## Non-goals

- 클릭으로 Preview 또는 Live를 TAKE하는 기능
- 현재 제어 채널을 별도 영구 설정으로 저장하는 기능
- Live 콘텐츠를 기준으로 하단 탭을 선택하는 기능
- 키보드 단축키 체계 변경
- 상태 메시지와 사용자 문서 전체의 TAKE 용어 일괄 번역

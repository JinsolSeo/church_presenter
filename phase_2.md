# Phase 2 구현 요청

프로젝트 루트의 `AGENTS.md`와 기존 아키텍처 문서를 먼저 읽고 모든 상위 지침을 준수하라.

현재 저장소에는 Phase 1에서 다음 기능이 구현되어 있다고 가정한다.

* PySide6 기반 Controller GUI
* Broadcast / Venue 독립 출력
* 멀티모니터 선택
* 단일 모니터 Simulation Mode
* Preview / Live 분리
* TXT 자막 편집 및 출력
* PDF 라이브러리, 썸네일, 페이지 출력
* BLACK 출력
* 설정 저장 및 복원
* 테스트와 CI 기본 구조

Phase 2의 목표는 기존 구조를 유지하면서 **로컬 영상 재생과 로컬 배경음악 재생 기능을 안정적으로 추가하는 것**이다.

기존 Phase 1 기능을 대규모로 재작성하지 말고, 현재 도메인 모델과 출력 렌더링 구조에 미디어 기능을 확장하라.

---

# 1. Phase 2 범위

다음 기능을 구현한다.

1. 로컬 영상 파일 라이브러리
2. 영상 Preview, Cue, TAKE, Play 제어
3. Broadcast / Venue 영상 출력
4. 동일 영상을 양쪽 출력으로 보내는 기능
5. 영상 종료 후 BLACK 전환
6. PDF·영상·BLACK 간 Fade 전환
7. 로컬 배경음악 파일 라이브러리
8. 음악 재생목록
9. 음악 반복 및 자동 다음 곡
10. 음악 재생 상태 저장 및 복원
11. 영상 재생 시 배경음악 자동 일시정지
12. 미디어 오류 처리
13. 테스트와 샘플 미디어 생성
14. Windows 운영 환경 검증 준비

다음 기능은 구현하지 않는다.

* YouTube 링크
* 웹 스트리밍
* 카메라 캡처
* OBS 연동
* ATEM 직접 제어
* 오디오 장치별 개별 라우팅
* 예배 순서표
* 긴급 버튼 모음
* 자동 오디오 Ducking
* 네트워크 미디어
* DRM 미디어

---

# 2. 구현 전 확인

코드를 수정하기 전에 다음 작업을 수행하라.

1. 현재 저장소 구조와 Phase 1 구현 상태를 확인한다.
2. 현재 콘텐츠 타입, Preview/Live 상태 모델, OutputSurface 구조를 확인한다.
3. 영상과 오디오를 어떤 계층에 추가할지 설계한다.
4. 기존 코드 중 재사용할 부분과 수정할 부분을 구분한다.
5. 변경할 파일 목록과 구현 순서를 작성한다.
6. 별도 사용자 확인을 기다리지 말고 구현을 계속 진행한다.

Phase 1의 구조가 메타프롬프트와 다를 경우 기존 구현을 무조건 폐기하지 말고, 최소한의 리팩터링으로 Phase 2 요구사항을 수용하라.

---

# 3. 권장 미디어 아키텍처

미디어 재생 구현은 UI 코드와 분리한다.

다음과 같은 추상화를 사용한다.

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol


class VideoPlaybackBackend(ABC):
    @abstractmethod
    def load(self, path: Path) -> None:
        ...

    @abstractmethod
    def play(self) -> None:
        ...

    @abstractmethod
    def pause(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def seek(self, position_ms: int) -> None:
        ...

    @abstractmethod
    def set_volume(self, volume: float) -> None:
        ...


class AudioPlaybackBackend(ABC):
    @abstractmethod
    def load(self, path: Path) -> None:
        ...

    @abstractmethod
    def play(self) -> None:
        ...

    @abstractmethod
    def pause(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def seek(self, position_ms: int) -> None:
        ...

    @abstractmethod
    def set_volume(self, volume: float) -> None:
        ...
```

정확한 인터페이스는 현재 프로젝트 구조에 맞게 수정할 수 있다.

중요 원칙:

* UI가 `QMediaPlayer`를 직접 소유하지 않도록 한다.
* 미디어 재생 상태를 UI 위젯에만 저장하지 않는다.
* 출력 채널 상태와 재생기 상태를 구분한다.
* 백엔드 교체가 가능해야 한다.
* 테스트에서는 실제 코덱 없이 Mock Backend를 사용할 수 있어야 한다.

---

# 4. 미디어 백엔드 선택

초기 구현은 PySide6 Qt Multimedia를 우선 사용한다.

```text
QMediaPlayer
QAudioOutput
QVideoSink 또는 QVideoWidget
```

그러나 백엔드는 교체 가능한 구조로 만든다.

Windows 실기기에서 다음 문제가 발생할 수 있다.

* 특정 MKV 재생 실패
* 일부 MOV 코덱 미지원
* 오디오만 재생되고 영상이 나오지 않음
* 탐색 위치 오류
* 첫 프레임 표시 지연
* 영상 종료 신호 누락
* 하드웨어 가속 차이

따라서 다음 조건을 만족해야 한다.

1. Qt Multimedia 구현을 별도 backend 모듈에 둔다.
2. 출력·도메인 로직이 Qt Multimedia에 강하게 종속되지 않게 한다.
3. 향후 `libmpv` backend를 추가할 수 있어야 한다.
4. 현재 Phase에서는 libmpv를 동시에 구현하지 않아도 된다.
5. Qt Multimedia로 지원되지 않는 파일은 명확한 오류를 표시한다.
6. 지원 가능 여부를 확실히 알 수 없는 파일을 무조건 재생 가능으로 표시하지 않는다.

---

# 5. 지원 파일 형식

## 영상

기본 확장자:

```text
.mp4
.mov
.mkv
.avi
```

확장자가 지원 목록에 있더라도 실제 코덱에 따라 재생 실패할 수 있으므로, 파일 확장자만으로 재생 성공을 보장하지 않는다.

영상 파일 항목은 최소한 다음 정보를 가진다.

```text
path
display_name
modified_time
file_size
duration_ms
resolution
availability
playback_status
error_message
thumbnail_path 또는 cached_thumbnail
```

가능하면 메타데이터를 비동기로 읽는다.

## 음악

기본 확장자:

```text
.mp3
.wav
.m4a
.flac
.ogg
```

음악 파일 항목은 최소한 다음 정보를 가진다.

```text
path
display_name
modified_time
file_size
duration_ms
availability
error_message
```

---

# 6. 영상 라이브러리

사용자는 영상 폴더를 지정할 수 있어야 한다.

기능:

* 폴더 선택
* 폴더 내 영상 자동 검색
* 파일명순 정렬
* 수정 날짜순 정렬
* 오름차순·내림차순
* 새로고침
* Drag and Drop
* 파일 삭제·이동 감지
* unavailable 상태 표시
* 재생 불가 파일 오류 표시
* 마지막 사용 폴더 복원

영상 목록에는 다음 정보를 표시한다.

* 파일명
* 재생 시간
* 해상도
* 파일 크기
* 오류 상태
* 썸네일

썸네일 추출이 실패해도 파일 자체를 목록에서 제거하지 않는다.

썸네일 생성은 UI 스레드에서 수행하지 않는다.

---

# 7. 영상 Preview와 Live 상태

영상 선택만으로 실제 출력이 변경되어서는 안 된다.

영상 상태는 다음 단계를 구분한다.

```text
UNLOADED
LOADING
READY
CUE
LIVE_PAUSED
PLAYING
PAUSED
STOPPED
ENDED
ERROR
```

정확한 Enum 이름은 현재 프로젝트 스타일에 맞게 조정할 수 있다.

## 영상 선택

영상 파일을 클릭하면:

1. 선택한 출력 채널의 Preview에 로드한다.
2. 영상 위치를 0으로 이동한다.
3. 첫 프레임 또는 적절한 Preview 이미지를 표시한다.
4. 자동 재생하지 않는다.
5. Preview 상태를 `CUE`로 둔다.
6. Live 화면은 변경하지 않는다.

## TAKE

사용자가 TAKE를 누르면:

1. Preview 영상 상태를 Live 상태로 복사한다.
2. Live 출력에 영상 첫 프레임을 표시한다.
3. 자동 재생하지 않는다.
4. 사용자 Play 입력을 기다린다.

즉:

```text
파일 선택
→ Preview Cue

TAKE
→ Live Cue

Play
→ 실제 영상 재생
```

영상 파일 클릭이나 TAKE만으로 영상 오디오가 재생되어서는 안 된다.

---

# 8. 영상 재생 컨트롤

각 영상 출력 채널에 다음 제어 기능을 제공한다.

* Play
* Pause
* Stop
* 처음으로 이동
* 탐색 슬라이더
* 현재 시간
* 전체 시간
* 음소거
* 볼륨 조절
* 프레임 또는 Preview 갱신
* 영상 오류 표시

시간 표시는 다음 형식을 사용한다.

```text
MM:SS / MM:SS
```

1시간 이상이면:

```text
HH:MM:SS / HH:MM:SS
```

## Stop 동작

Stop을 누르면:

1. 영상 재생을 멈춘다.
2. 재생 위치를 처음으로 이동한다.
3. 해당 Live 출력은 BLACK으로 전환한다.

## 영상 종료 동작

영상이 자연스럽게 끝나면:

1. 재생 상태를 ENDED로 변경한다.
2. 해당 Live 출력은 BLACK으로 전환한다.
3. 배경음악은 자동 재개하지 않는다.
4. 종료 이벤트를 로그에 기록한다.

마지막 프레임을 계속 표시하지 않는다.

---

# 9. Broadcast와 Venue 영상 출력

Broadcast와 Venue는 기본적으로 독립적인 영상 상태를 가진다.

가능한 상태 예:

```text
Broadcast Live: VIDEO_A 재생 중
Venue Live: PDF 5페이지
```

또는:

```text
Broadcast Live: BLACK
Venue Live: VIDEO_B Cue 상태
```

동일한 영상 파일을 양쪽에 보낼 수 있어야 한다.

## Send to Both

영상 파일을 선택하고 `Send to Both`를 실행하면:

1. 동일 영상을 Broadcast Preview와 Venue Preview에 로드한다.
2. 양쪽 모두 첫 프레임에서 Cue 상태로 둔다.
3. 실제 Live는 변경하지 않는다.

## TAKE BOTH

양쪽 Preview가 모두 준비된 경우:

1. 양쪽 Live를 동일 영상의 Cue 상태로 전환한다.
2. 자동 재생하지 않는다.
3. 이후 Play Both 또는 개별 Play를 선택할 수 있다.

`Play Both`를 구현하는 경우 두 재생기는 가능한 한 동시에 시작해야 한다.

완벽한 프레임 동기화를 보장하지 않아도 되지만, 사용자 입력 후 가능한 동일 이벤트 루프 사이클에서 시작한다.

한쪽 영상 준비가 실패하면 두 출력 모두 기존 Live를 유지한다.

---

# 10. 영상 렌더링 구조

영상 출력은 Controller Preview, Simulation Mode, 실제 Output Window에서 일관되게 동작해야 한다.

다음 중 하나의 구조를 선택하라.

## 구조 1

각 Live Output마다 독립된 `QMediaPlayer`와 Video Sink 사용

## 구조 2

하나의 decoder 결과를 여러 출력으로 복제

Phase 2 MVP에서는 구현 안정성을 위해 **출력 채널별 독립 플레이어**를 우선 고려한다.

다만 동일 파일을 양쪽에서 재생할 경우 CPU/GPU 사용량이 증가할 수 있으므로 이 제한을 문서화한다.

실제 출력과 Simulation Output이 동시에 켜져 있을 때 불필요하게 동일 영상을 중복 디코딩하지 않도록 설계 가능성을 검토한다.

Preview용 재생기와 Live용 재생기를 무분별하게 다수 생성하지 않는다.

---

# 11. Fade 전환

다음 콘텐츠 전환에 짧은 Fade를 적용한다.

```text
PDF → VIDEO
VIDEO → PDF
BLACK → PDF
BLACK → VIDEO
PDF → BLACK
VIDEO → BLACK
```

기본 전환 시간:

```text
250 ms
```

설정 가능 범위 예:

```text
0–2000 ms
```

Fade 정책:

1. 기존 Live 콘텐츠를 fade out
2. 새 콘텐츠 준비 완료 확인
3. 새 콘텐츠로 전환
4. 새 콘텐츠 fade in

영상은 첫 프레임이 준비되기 전에 화면에 노출하지 않는다.

전환 준비에 실패하면:

* 기존 Live 유지
* 오류 표시
* 부분 전환 금지

자막 Key Feed에는 Fade 적용 여부를 별도 설정할 수 있도록 확장 가능하게 하되, Phase 2에서는 PDF·VIDEO·BLACK 전환에 집중한다.

Fade 구현은 고비용 블러나 복잡한 효과를 사용하지 않는다.

---

# 12. 배경음악 라이브러리

사용자는 음악 폴더를 지정할 수 있어야 한다.

기능:

* 폴더 선택
* 오디오 파일 자동 검색
* 파일명순 정렬
* 수정 날짜순 정렬
* Drag and Drop
* 파일 존재 여부 확인
* 재생 불가 상태 표시
* 마지막 사용 폴더 복원

음악은 Broadcast 또는 Venue별 콘텐츠가 아니라 애플리케이션 전역 배경음악 플레이어로 취급한다.

초기 오디오는 시스템 기본 오디오 출력 장치로 재생한다.

현장과 방송의 오디오를 별도로 라우팅하지 않는다.

---

# 13. 음악 재생목록

재생목록 모델을 UI와 분리한다.

예시:

```python
@dataclass
class PlaylistItem:
    item_id: str
    path: Path
    title: str
    duration_ms: int | None
    is_available: bool
    error_message: str | None


@dataclass
class AudioPlaylist:
    name: str
    items: list[PlaylistItem]
    current_index: int | None
    repeat_mode: RepeatMode
    is_modified: bool
```

정확한 구조는 프로젝트 스타일에 맞게 변경할 수 있다.

필수 기능:

* 음악 파일 추가
* 복수 파일 추가
* 파일 제거
* 전체 비우기
* 드래그로 순서 변경
* 선택 곡부터 재생
* 현재 곡 강조
* 다음 곡
* 이전 곡
* 재생
* 일시정지
* 정지
* 탐색 슬라이더
* 볼륨 슬라이더
* 음소거
* 반복 없음
* 한 곡 반복
* 전체 반복
* 곡 종료 후 다음 곡 자동 재생
* 재생목록 저장
* 재생목록 불러오기
* 다른 이름으로 저장
* 마지막 재생목록 복원
* 삭제된 파일 상태 표시

재생목록 파일 형식은 JSON을 사용한다.

파일 경로는 가능한 한 절대 경로를 저장하되, 재생목록 파일과 같은 디렉터리 하위 파일은 상대 경로로 저장할 수 있도록 고려한다.

---

# 14. 음악 재생 정책

## 반복 없음

```text
현재 곡 종료
→ 다음 곡이 있으면 자동 재생
→ 마지막 곡이면 정지
```

## 한 곡 반복

```text
현재 곡 종료
→ 같은 곡 처음부터 재생
```

## 전체 반복

```text
현재 곡 종료
→ 다음 곡 재생
→ 마지막 곡 종료 시 첫 곡 재생
```

## Previous 동작

재생 위치가 일정 시간 이상 진행된 상태에서 Previous를 누르면 현재 곡 처음으로 이동한다.

그렇지 않으면 이전 곡으로 이동한다.

기본 기준:

```text
3초
```

---

# 15. 영상과 배경음악 충돌 정책

영상의 실제 Play가 시작될 때 배경음악이 재생 중이면 자동으로 일시정지한다.

중요:

* 영상 파일을 Preview에 로드할 때는 배경음악을 멈추지 않는다.
* TAKE로 영상 첫 프레임을 Live에 올릴 때도 배경음악을 멈추지 않는다.
* 실제 영상 Play 명령이 실행되는 시점에만 배경음악을 일시정지한다.

정책:

```text
영상 Play 시작
→ 배경음악 재생 중인지 확인
→ 재생 중이면 Pause
→ 자동 일시정지 사유 기록
```

영상이 다음 상태가 되어도 배경음악을 자동 재개하지 않는다.

```text
영상 Pause
영상 Stop
영상 Ended
영상 Error
영상 Live 해제
```

사용자가 직접 음악 Play를 눌러야 한다.

배경음악이 영상 때문에 자동 일시정지되었다는 상태를 GUI에 표시한다.

예:

```text
영상 재생으로 인해 배경음악이 일시정지되었습니다.
```

향후 자동 재개 옵션을 추가할 수 있도록 사유 상태를 별도로 보존한다.

---

# 16. 여러 영상 동시 재생 정책

Broadcast와 Venue에서 서로 다른 영상이 동시에 재생될 수 있다.

정책:

* 첫 번째 영상이 Play될 때 배경음악 Pause
* 두 번째 영상이 Play되어도 음악 상태는 유지
* 한 영상이 끝나도 다른 영상이 재생 중일 수 있음
* 모든 영상이 끝나더라도 음악은 자동 재개하지 않음

현재 재생 중인 영상 채널 수를 상태 모델에서 추적한다.

---

# 17. Preview와 Live 상태 일관성

Preview에서 다른 영상을 선택해도 기존 Live 영상은 중단되지 않아야 한다.

예:

```text
Venue Live: 영상 A 재생 중
Venue Preview: 영상 B 선택
```

이 상태가 가능해야 한다.

TAKE 시 현재 Live 영상의 처리 정책:

1. 기존 Live 영상 정지
2. 기존 영상 오디오 중단
3. Fade out
4. 새 영상 첫 프레임 표시
5. Cue 상태 유지
6. 새 영상은 자동 재생하지 않음

Preview 변경으로 Live 재생기가 재사용되거나 초기화되지 않도록 한다.

---

# 18. 콘텐츠 상태 확장

Phase 1 콘텐츠 모델에 다음 타입을 추가한다.

```text
VIDEO
```

콘텐츠 모델 예:

```python
@dataclass(frozen=True)
class VideoContent:
    path: Path
    position_ms: int = 0
    volume: float = 1.0
    is_muted: bool = False
```

실제 재생 중 position을 불변 콘텐츠 객체에 매 프레임 저장하지 않는다.

다음 두 상태를 구분한다.

```text
선택된 콘텐츠 상태
실시간 재생 상태
```

예:

```text
VideoContentDescriptor
VideoPlaybackRuntimeState
```

---

# 19. 미디어 오류 처리

다음 오류를 처리한다.

* 파일 없음
* 권한 없음
* 지원하지 않는 컨테이너
* 지원하지 않는 코덱
* 손상된 파일
* 오디오 장치 없음
* 영상 출력 초기화 실패
* 탐색 실패
* 재생 중 파일 삭제
* 재생 backend 오류
* duration 확인 실패
* thumbnail 생성 실패

오류 발생 시:

1. 앱 전체를 종료하지 않는다.
2. 해당 항목에 오류 상태를 표시한다.
3. 기존 Live 콘텐츠는 가능한 유지한다.
4. 영상 재생 중 치명적 오류가 발생하면 해당 출력은 BLACK으로 전환한다.
5. 사용자에게 간결한 오류 메시지를 표시한다.
6. 상세 stack trace는 로그에 기록한다.
7. 재시도 버튼 또는 다시 로드 기능을 제공한다.

---

# 20. UI 요구사항

## 영상 패널

최소 구성:

```text
영상 폴더 선택
정렬 방식
새로고침
영상 파일 목록
영상 썸네일
파일 정보
Broadcast Preview로 보내기
Venue Preview로 보내기
Send to Both
TAKE
TAKE BOTH
Play
Pause
Stop
처음으로
탐색 슬라이더
현재 시간 / 전체 시간
볼륨
음소거
상태 표시
오류 표시
```

Broadcast와 Venue 중 어느 출력 채널을 제어하는지 항상 명확히 표시한다.

## 음악 패널

최소 구성:

```text
음악 폴더 선택
음악 파일 목록
재생목록
파일 추가
파일 제거
순서 변경
재생
일시정지
정지
이전 곡
다음 곡
탐색 슬라이더
현재 시간 / 전체 시간
볼륨
음소거
반복 모드
현재 곡 표시
영상으로 인한 자동 일시정지 표시
재생목록 저장
재생목록 불러오기
```

UI는 작은 Mac 화면에서도 사용할 수 있도록 Dock, Splitter, Tab 또는 Scroll Area를 활용한다.

---

# 21. 키보드 단축키

텍스트 편집 중이 아닐 때 다음 단축키를 지원한다.

## 영상 패널

```text
Left / Right
Preview 탐색 또는 미디어 탐색 정책을 명확히 정의

Enter
현재 대상 채널 TAKE

Space
현재 Live 영상 Play / Pause

S
Stop

Home
영상 처음으로 이동
```

Left/Right가 탐색 슬라이더와 영상 파일 선택에 충돌하지 않도록 포커스 기반 정책을 정의한다.

## 음악 패널

```text
Space
Play / Pause

Ctrl+Right 또는 Command+Right
다음 곡

Ctrl+Left 또는 Command+Left
이전 곡
```

macOS와 Windows 단축키 차이를 고려한다.

---

# 22. 설정 저장

다음 Phase 2 설정을 저장하고 복원한다.

* 영상 폴더
* 음악 폴더
* 영상 정렬 방식
* 음악 정렬 방식
* 영상 볼륨
* 음악 볼륨
* 영상 음소거
* 음악 음소거
* Fade 시간
* 마지막 선택 영상
* 마지막 선택 음악 파일
* 마지막 재생목록
* 반복 모드
* Playlist panel 상태
* 최근 재생목록 목록

실행 재개 시 영상이나 음악을 자동으로 재생하지 않는다.

재생 위치를 저장하더라도 자동 재생하지 않고 Cue 또는 Paused 상태로 복원한다.

---

# 23. 종료 처리

프로그램 종료 시:

1. 저장하지 않은 자막 변경 확인
2. 저장하지 않은 음악 재생목록 변경 확인
3. 모든 영상 재생 중단
4. 배경음악 중단
5. Broadcast 출력 BLACK
6. Venue 출력 BLACK
7. 미디어 리소스 해제
8. 설정 저장
9. 출력 창 닫기
10. 앱 종료

미디어 backend가 종료되지 않아 프로세스가 남지 않도록 한다.

---

# 24. 샘플 미디어

저작권 문제가 없는 샘플 미디어를 생성하거나 생성 스크립트를 제공한다.

필수:

```text
sample_assets/videos/sample_video.mp4
sample_assets/audio/sample_track_01.wav
sample_assets/audio/sample_track_02.wav
sample_assets/audio/sample_track_03.wav
sample_assets/playlists/sample_playlist.json
```

가능하면 `scripts/generate_sample_assets.py`를 확장하여 다음을 생성한다.

* 10초 이상 샘플 영상
* 화면에 프레임 번호 또는 시간 표시
* 테스트용 오디오 사인파 또는 간단한 톤
* 서로 길이가 다른 오디오 파일
* 저작권 없는 생성 데이터

샘플 영상 생성에 FFmpeg가 필요한 경우:

* FFmpeg 의존성을 문서화한다.
* FFmpeg가 없어도 테스트 전체가 실패하지 않게 한다.
* 생성된 작은 샘플 파일을 저장소에 포함할 수 있는지 파일 크기를 검토한다.

---

# 25. 테스트

`pytest`와 `pytest-qt`를 사용한다.

실제 코덱과 오디오 장치가 없는 CI에서도 대부분의 테스트가 가능하도록 Mock Backend를 사용한다.

## 필수 단위 테스트

* 영상 파일 확장자 필터
* 음악 파일 확장자 필터
* 파일명 정렬
* 수정 날짜 정렬
* 영상 콘텐츠 상태
* Preview와 Live 분리
* 영상 TAKE
* 영상 TAKE BOTH
* 부분 실패 rollback
* Cue 상태
* Play 상태
* Pause 상태
* Stop 후 BLACK
* Ended 후 BLACK
* 영상 오류 후 BLACK
* Fade 상태 전환
* Fade 시간 설정
* 음악 재생목록 추가
* 음악 재생목록 제거
* 음악 순서 변경
* 음악 현재 index 처리
* 반복 없음
* 한 곡 반복
* 전체 반복
* 자동 다음 곡
* Previous 3초 정책
* 재생목록 저장·복원
* 삭제된 파일 처리
* 영상 Play 시 음악 자동 Pause
* 영상 Preview 시 음악 유지
* 영상 TAKE 시 음악 유지
* 영상 종료 후 음악 자동 재개 금지
* 두 영상 동시 상태
* 설정 저장·복원
* 종료 시 미디어 정지
* 종료 시 BLACK

## GUI 테스트

* 영상 파일 클릭
* Preview Cue 표시
* TAKE
* Play
* Pause
* Stop
* 탐색 슬라이더
* 볼륨
* 음소거
* Send to Both
* TAKE BOTH
* 영상 종료 상태
* 음악 파일 추가
* Playlist drag reorder
* 반복 모드 변경
* 영상으로 인한 음악 Pause 표시
* Simulation Mode 영상 렌더링

## Backend 계약 테스트

Mock Backend와 Qt Multimedia Backend가 동일한 인터페이스를 만족하는지 검사한다.

---

# 26. CI

기존 GitHub Actions를 확장한다.

환경:

```text
macos-latest
windows-latest
```

CI 원칙:

* 실제 오디오 장치를 요구하지 않음
* 실제 다중 모니터를 요구하지 않음
* 실제 전체화면을 요구하지 않음
* Mock Backend 중심 테스트
* Qt Offscreen 모드 사용
* 샘플 미디어 메타데이터 검증
* Backend 초기화 실패가 전체 테스트 실패로 오인되지 않게 구분

실제 Qt Multimedia 재생 smoke test는 운영체제별로 가능한 범위에서 별도 마커를 사용한다.

예:

```bash
pytest -m "not media_integration"
pytest -m media_integration
```

---

# 27. 성능 요구사항

다음 항목을 점검한다.

* 영상 목록 스캔 시 UI 멈춤 방지
* 썸네일 비동기 생성
* 메타데이터 비동기 로딩
* Preview 영상 준비 중 취소
* 빠르게 다른 영상을 선택할 때 이전 작업 취소
* 캐시 크기 제한
* 영상 재생 중 PDF 썸네일 작업 우선순위 조절
* 음악 재생 중 UI 응답성 유지
* 실제 출력과 Preview의 불필요한 중복 디코딩 최소화
* 사용하지 않는 플레이어 리소스 해제

성능 측정 결과를 문서에 기록한다.

---

# 28. Windows 실기기 검증 항목

Phase 2 완료 후 Windows에서 다음을 수동 확인할 수 있도록 체크리스트를 작성한다.

```text
MP4 H.264 재생
MOV 재생
MKV 재생
AVI 재생
영상 오디오 출력
영상 탐색
Pause / Resume
영상 종료 BLACK
Broadcast HDMI 출력
Venue HDMI 출력
양쪽 동시 재생
Fade 전환
배경음악 재생
영상 시작 시 음악 Pause
재생목록 자동 다음 곡
전체 반복
한 곡 반복
프로그램 종료 후 프로세스 잔류 여부
```

지원이 불안정한 포맷은 문서에 명시한다.

필요하면 권장 영상 포맷을 다음과 같이 안내한다.

```text
MP4
H.264 video
AAC audio
1920×1080
30 fps 또는 60 fps
```

---

# 29. 문서 갱신

다음을 갱신하거나 추가한다.

```text
README.md
docs/architecture.md
docs/user-guide.md
docs/media-playback.md
docs/windows-media-test.md
```

`docs/media-playback.md`에는 다음을 설명한다.

* 지원 파일 형식
* 코덱과 컨테이너의 차이
* Cue / TAKE / Play 흐름
* 영상 종료 후 BLACK 정책
* 배경음악 자동 Pause 정책
* Fade 설정
* 재생 오류 해결 방법
* 권장 영상 인코딩 설정
* Qt Multimedia 제한
* 향후 libmpv backend 확장 계획

---

# 30. 코드 품질

* Python 3.12
* PEP 8
* 타입 힌트
* `pathlib.Path`
* 전역 mutable state 금지
* UI와 재생 로직 분리
* UI와 Playlist 모델 분리
* 거대한 Controller 클래스 금지
* 빈 `except` 금지
* 핵심 기능에 TODO 금지
* 테스트 가능한 Backend 추상화
* Ruff 통과
* pytest 통과
* 기존 Phase 1 테스트 유지
* macOS와 Windows 분기 최소화

---

# 31. 완료 기준

다음 항목이 모두 확인되어야 Phase 2 완료로 판단한다.

* 영상 폴더를 선택할 수 있음
* 영상 목록이 자동 생성됨
* 파일명·수정 날짜 정렬 가능
* 영상 썸네일 표시
* 영상 클릭 시 Preview Cue
* 클릭만으로 Live가 바뀌지 않음
* TAKE 후에도 자동 재생되지 않음
* Play를 눌렀을 때만 재생
* Broadcast 영상 출력 가능
* Venue 영상 출력 가능
* Send to Both 가능
* TAKE BOTH 가능
* 영상 종료 후 BLACK
* Stop 후 BLACK
* PDF와 영상 간 Fade
* 음악 폴더 선택 가능
* 음악 재생목록 생성 가능
* Drag reorder 가능
* 재생·일시정지·정지 가능
* 반복 없음·한 곡 반복·전체 반복 가능
* 다음 곡 자동 재생
* 재생목록 저장·복원
* 영상 Play 시 배경음악 자동 Pause
* 영상 종료 후 배경음악 자동 재개되지 않음
* Simulation Mode에서 영상과 음악 상태 확인 가능
* 설정 복원 가능
* 종료 시 영상과 음악이 정지됨
* 종료 시 출력 BLACK
* 기존 Phase 1 기능이 정상 동작
* 자동 테스트 통과
* macOS와 Windows CI 통과

핵심 기능이 placeholder이거나 버튼만 존재하고 실제로 동작하지 않는 경우 완료로 판단하지 마라.

---

# 32. 최종 보고 형식

Phase 2 구현 후 다음 형식으로 보고하라.

```text
1. 구현한 영상 기능
2. 구현한 음악 기능
3. 미디어 backend 구조
4. 주요 변경 파일
5. Preview / Cue / TAKE / Play 흐름
6. 배경음악 충돌 처리
7. Fade 구현 방식
8. 테스트 명령과 결과
9. macOS 확인 결과
10. Windows 실기기 확인 항목
11. 지원이 불안정한 포맷
12. 성능과 리소스 사용 제한
13. 알려진 문제
14. Phase 3로 넘긴 기능
```

테스트를 실행하지 못한 항목은 실행했다고 주장하지 말고, 정확한 이유와 실행 명령을 작성하라.

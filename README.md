# Church Presenter

Church Presenter는 한 명의 운영자가 ATEM용 송출 Key/PDF/영상 출력과 현장용
PDF/영상 출력을 독립적으로 제어하는 PySide6 데스크톱 애플리케이션입니다.
현재 Phase 1·2 범위인 TXT 자막, PDF, BLACK, Preview/Live TAKE, 멀티모니터,
Simulation Mode, 로컬 영상 및 전역 배경음악 재생목록을 지원합니다. 화면의 채널명은
`송출`과 `현장`으로 표시하되 내부 상태 모델의 Broadcast/Venue 명칭은 유지합니다.
Controller UI는 FHD(1920×1080)를 기준으로 구성되며 Light Professional, Dark
Modern, Minimalist Light 테마를 실행 중 즉시 전환하고 다음 실행에 복원합니다.
노트북 크기에서는 컴팩트 밀도가 자동 적용되고, 상단 Preview/Live 영역과 하단
콘텐츠 영역의 구분선을 직접 조절할 수 있습니다. 하단 전체에는 바깥 스크롤바가
생기지 않으며 긴 데이터 목록만 해당 목록 안에서 스크롤됩니다.

운영 중에는 `동시 진행`으로 송출 자막과 현장 PDF를 한 번의 방향키/TAKE BOTH로
제어할 수 있고, PDF만 양쪽에 보낼 때는 두 Preview 체크박스를 함께 선택할 수
있습니다. PDF 파일은 파일명 내림차순, 페이지 썸네일은 원본 페이지 오름차순으로
고정되어 예배 중 순서가 임의로 바뀌지 않습니다. 오른쪽 `예배 순서` 패널에서는
두 Preview의 조합과 진행 순서를 JSON 프리셋으로 저장하고 다시 불러올 수 있습니다.

영상은 `파일 선택 → Preview Cue → TAKE → Live Cue → Play` 순서로만 재생됩니다.
선택이나 TAKE만으로 영상과 오디오가 시작되지 않습니다. 영상 Play 시 재생 중인
배경음악은 자동으로 Pause되며 영상이 끝나도 자동 재개되지 않습니다.

## 설치 및 실행

Python 3.12 환경에서 다음을 실행합니다.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m church_presenter
```

개발용 한 모니터에서는 상단 `화면 / 오디오 설정`에서 Simulation Mode를 선택하고
가상 해상도, 연결 상태 및 공통 오디오 출력 장치를 정한 뒤 `출력 시작`을 누릅니다. Preview를
선택해도 출력은 바뀌지 않으며, 해당 TAKE 또는 TAKE BOTH를 눌러야 Live가
변경됩니다. 출력 창이 닫혀 있다면 TAKE가 지정된 출력 창을 먼저 시작하고, 창을
시작할 수 없으면 기존 Live를 유지합니다.

상단 `테마` 선택기는 Controller UI에만 적용됩니다. Preview/Live 콘텐츠와 물리·가상
출력 렌더링은 테마를 바꿔도 변경되지 않습니다. 잘못되거나 삭제된 테마가 저장되어
있으면 Light Professional로 안전하게 복구됩니다. 모든 테마의 자막 출력 카드는
Live와 Preview만 각각 빨간색과 파란색으로 강조합니다.

## 품질 확인

```bash
pytest
ruff check .
mypy src
python scripts/generate_sample_assets.py
```

기본 샘플은 `sample_assets` 아래 자막, PDF, 12초 영상, WAV 3곡과 JSON
재생목록으로 제공됩니다. 생성 스크립트는 외부 FFmpeg를 우선 사용하고, 없으면
Qt Multimedia encoder로 MP4를 생성합니다. 자세한 조작법은
[`docs/user-guide.md`](docs/user-guide.md), 출력 구조는
[`docs/architecture.md`](docs/architecture.md), ATEM 연결은
[`docs/atem-setup.md`](docs/atem-setup.md), 미디어 정책은
[`docs/media-playback.md`](docs/media-playback.md), Windows 검증은
[`docs/windows-media-test.md`](docs/windows-media-test.md)를 참고하십시오. 이전 오류와 설계
시행착오는 [`docs/session-handoff.md`](docs/session-handoff.md)에 정리되어 있습니다.

YouTube, 웹 스트리밍, 카메라 캡처, OBS, ATEM 직접 제어, 장치별 오디오 라우팅은
포함하지 않습니다.

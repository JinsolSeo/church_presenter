# Church Presenter

Church Presenter는 한 명의 운영자가 ATEM용 송출 Key/PDF/영상 출력과 현장용
PDF/영상 출력을 독립적으로 제어하는 PySide6 데스크톱 애플리케이션입니다.
현재 Phase 1·2 범위인 즉석 문구·준비된 찬양·성경 자막, PDF, 검정·크로마키 빈 화면,
Preview/Live TAKE, 멀티모니터,
Simulation Mode, 로컬/YouTube 영상 및 로컬/YouTube 혼합 배경음악 재생목록을 지원합니다. 화면의 채널명은
`송출`과 `현장`으로 표시하되 내부 상태 모델의 Broadcast/Venue 명칭은 유지합니다.
Controller UI는 FHD(1920×1080)를 기준으로 구성되며 Light Professional, Dark
Modern, Minimalist Light, Warm Linen, Deep Ocean, Graphite Violet 테마를 실행 중
즉시 전환하고 다음 실행에 복원합니다.
노트북 크기에서는 컴팩트 밀도가 자동 적용되고, 상단 Preview/Live 영역과 하단
콘텐츠 영역의 구분선을 직접 조절할 수 있습니다. 하단 전체에는 바깥 스크롤바가
생기지 않으며 긴 데이터 목록만 해당 목록 안에서 스크롤됩니다.

운영 중에는 `동시 진행`으로 송출 자막과 현장 PDF를 한 번의 방향키/TAKE BOTH로
제어할 수 있고, PDF만 양쪽에 보낼 때는 두 Preview 체크박스를 함께 선택할 수
있습니다. `바로 Live`를 켜면 화살표 또는 PageUp/PageDown 입력 뒤 준비 완료 시
TAKE BOTH도 자동 실행됩니다. PDF 파일은 파일명 내림차순, 페이지 썸네일은 원본 페이지 오름차순으로
고정되어 예배 중 순서가 임의로 바뀌지 않습니다. 오른쪽 `예배 순서` 패널에서는
두 Preview의 조합과 진행 순서를 JSON 프리셋으로 저장하고 다시 불러올 수 있습니다.
오른쪽 예배 순서 패널은 실행 중 항상 표시되며, 상단 `원격 연결`에서 같은 Wi-Fi의
태블릿·스마트폰으로 Controller 화면을 미러링하고 직접 조작할 수 있습니다. 서버는
노트북 안에서만 실행되며 여러 원격 기기의 동시 접속을 지원합니다.

콘텐츠 영역은 `즉석`, `찬양`, `성경`, `PDF`, `영상`, `음악`, `빈 화면`의 한 단계
탭으로 구성됩니다. 즉석 탭의 문구는 돌발 상황용이며 예배 순서에는 저장되지 않습니다.
준비된 찬양과 주간 성경 콘티는 각각의 탭에서 Preview/TAKE하고
예배 순서에 의미 참조로 저장할 수 있습니다. 성경 본문 JSON은 저작권 확인 없이
저장소에 포함하지 않으며 운영자가 로컬 파일을 선택합니다.

영상은 로컬 파일과 공개 단일 YouTube URL 모두 `항목 선택 → Preview Cue → TAKE →
Live Cue → Play` 순서로만 재생됩니다. 항목 선택만으로 decoder를 시작하지 않으며,
Preview Cue와 TAKE만으로도 영상과
오디오가 재생되지는 않습니다. 영상 Play 시 재생 중인 배경음악은 자동으로 Pause되며
영상이 끝나도 자동 재개되지 않습니다.

## 설치 및 실행

Python 3.12 환경에서 다음을 실행합니다.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m church_presenter
```

YouTube 배경음악은 Python 패키지 외에 시스템 `libmpv` runtime이 필요합니다.
macOS 개발 환경은 `brew install mpv` 후 위 설치 명령을 실행합니다. Windows에서는
`mpv-2.dll`을 포함한 libmpv 빌드를 설치하고 DLL 디렉터리를 `PATH`에 추가하거나
패키징한 실행 파일 옆의 `libmpv` 폴더에 배치해야 합니다. 다른 위치를 쓰면
`CHURCH_PRESENTER_LIBMPV_DIR`에 절대 경로를 지정할 수 있습니다. `yt-dlp`와
`python-mpv` Python 패키지는
프로젝트 의존성으로 설치됩니다. YouTube extractor 변경 대응이 필요할 때는
영상 탭의 `기능 최신화`를 사용합니다. 이 버튼은 실행 중인 프로젝트 `.venv`에서
`yt-dlp[default]`와 호환 범위의 `python-mpv`를 갱신하며, 완료 후 앱을 다시 시작해야
합니다. 수동으로는 `python -m pip install --upgrade "yt-dlp[default]"`를 사용할 수
있습니다.

개발용 한 모니터에서는 상단 `화면 / 오디오 설정`에서 Simulation Mode를 선택하고
가상 해상도, 연결 상태 및 공통 오디오 출력 장치를 정한 뒤 `출력 시작`을 누릅니다. Preview를
선택해도 출력은 바뀌지 않으며, 해당 TAKE 또는 TAKE BOTH를 눌러야 Live가
변경됩니다. 출력 창이 닫혀 있다면 TAKE가 지정된 출력 창을 먼저 시작하고, 창을
시작할 수 없으면 기존 Live를 유지합니다.

상단 `테마` 선택기는 Controller UI에만 적용됩니다. Preview/Live 콘텐츠와 물리·가상
출력 렌더링은 테마를 바꿔도 변경되지 않습니다. 잘못되거나 삭제된 테마가 저장되어
있으면 Light Professional로 안전하게 복구됩니다. 모든 테마의 자막 출력 카드는
Live와 Preview만 각각 빨간색과 파란색으로 강조합니다.

## 원격 연결

노트북과 원격 기기를 같은 Wi-Fi에 연결한 뒤 상단 `원격 연결`을 누르고 표시된 QR
코드를 Safari 또는 Chrome으로 스캔합니다. 서버는 `0.0.0.0`에 바인드하며 기본 포트
8765가 사용 중이면 8790까지 빈 포트를 자동 선택합니다. 접속 URL의 긴 난수 토큰은
서버를 시작하거나 재시작할 때마다 새로 생성되고, `연결 종료` 즉시 폐기됩니다.
외부 인터넷이나 클라우드 서버는 필요하지 않으며 포트 포워딩도 설정하지 않습니다.
원격 조작 응답성을 보호하기 위해 재생 중인 네이티브 영상 영역은 준비된 첫 프레임을
정지 화면으로 표시하고, 버튼·목록·상태 등 Controller UI만 계속 갱신합니다.
모바일에서는 한 손가락 탭·드래그가 기존처럼 Controller 조작으로 전달됩니다. 두
손가락 pinch와 이동은 원격 화면만 1~4배로 확대하고 이동하며 Controller에는
전달되지 않습니다. 더블 탭은 2배 확대와 화면 맞춤을 전환하고, `화면 맞춤` 버튼은
확대와 이동을 즉시 초기화합니다.
Safari처럼 JPEG 디코딩이 느린 브라우저에서도 오래된 화면이 쌓이지 않도록 브라우저는
렌더링 중인 프레임과 최신 대기 프레임만 유지합니다. 모바일 캔버스 해상도도 조작에
필요한 수준으로 제한해 화면 갱신이 입력 전송을 방해하지 않도록 합니다.

처음 실행할 때 Windows 방화벽이 표시되면 현재 사설 네트워크에서 Python 또는
패키징된 Church Presenter의 통신을 허용하십시오. macOS에서는 시스템 설정의
`네트워크 > 방화벽 > 옵션`에서 Church Presenter의 수신 연결을 허용합니다. 같은
Wi-Fi여도 게스트 Wi-Fi, AP/client isolation, 호텔·사내망 정책 또는 운영체제
방화벽이 기기 간 접속을 막을 수 있습니다. 자세한 사용 및 수동 검증 절차는
[`docs/user-guide.md`](docs/user-guide.md)를 참고하십시오.

## 품질 확인

```bash
pytest
ruff check .
mypy src
python scripts/generate_sample_assets.py
```

기본 샘플은 `sample_assets` 아래 곡 JSON 4개, PDF, 12초 영상, WAV 3곡과 JSON
재생목록으로 제공됩니다. 생성 스크립트는 외부 FFmpeg를 우선 사용하고, 없으면
Qt Multimedia encoder로 MP4를 생성합니다. 자세한 조작법은
[`docs/user-guide.md`](docs/user-guide.md), 출력 구조는
[`docs/architecture.md`](docs/architecture.md), ATEM 연결은
[`docs/atem-setup.md`](docs/atem-setup.md), 미디어 정책은
[`docs/media-playback.md`](docs/media-playback.md), Windows 검증은
[`docs/windows-media-test.md`](docs/windows-media-test.md), 성경 JSON 형식과 재생성 방법은
[`docs/bible-data.md`](docs/bible-data.md), 곡 JSON 및 찬양 콘티 형식은
[`docs/song-data.md`](docs/song-data.md)를 참고하십시오. 이전 오류와 설계
시행착오는 [`docs/session-handoff.md`](docs/session-handoff.md)에 정리되어 있습니다.

YouTube 검색·playlist import·다운로드, 기타 웹 스트리밍, 카메라 캡처, OBS, ATEM
직접 제어는 포함하지 않습니다. 영상과 배경음악의 YouTube 항목은 공개 단일 영상
URL의 스트림을 실시간으로 해석해 재생합니다.

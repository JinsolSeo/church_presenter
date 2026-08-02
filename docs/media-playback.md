# 미디어 재생

## 지원 형식과 코덱

영상 라이브러리는 `.mp4`, `.mov`, `.mkv`, `.avi`, 음악 라이브러리는 `.mp3`,
`.wav`, `.m4a`, `.flac`, `.ogg`를 검색합니다. 확장자는 컨테이너 형식일 뿐 실제
영상·음성 코덱 지원을 보장하지 않습니다. 같은 MOV나 MKV도 내부 코덱에 따라 한
컴퓨터에서는 재생되고 다른 컴퓨터에서는 실패할 수 있습니다.

가장 안정적인 운영용 영상 권장값은 MP4 컨테이너, H.264 영상, AAC 오디오,
1920x1080, 30 또는 60fps입니다. 예배 전에 실제 운영 PC와 HDMI 출력에서 모든
파일을 끝까지 시험하십시오.

## Cue / TAKE / Play

로컬 파일 또는 YouTube URL 항목을 선택한 뒤 `Preview Cue`를 누르면 음소거된 Preview decoder를 시작하고 첫 실제
프레임에서 정지합니다. 파일 선택만으로는 decoder나 Preview를 변경하지 않습니다.
첫 프레임이 준비되기 전에는 TAKE가 비활성/실패 상태이며 기존 Live가 유지됩니다.
TAKE는 준비된 decoder를 Live 역할로 바꾸지만 재생하지 않습니다. Play만 실제 재생과
영상 오디오를 시작합니다. Preview에서 다른 파일을 준비해도 기존 Live decoder는
중단되지 않습니다.

같은 파일을 다시 선택해도 decoder 소스를 비운 뒤 새로 로드하므로 첫 프레임부터 다시
Cue됩니다. 이미 Live인 같은 영상을 새로 Cue하여 TAKE하면 기존 재생 위치를 재사용하지
않고 새 decoder를 0초의 Live Pause 상태로 교체합니다.

양쪽 송출은 동일 파일을 두 개의 독립 decoder로 준비합니다. 한쪽 준비가 실패하면
TAKE BOTH는 두 기존 Live를 모두 보존합니다. 완전한 프레임 동기화는 보장하지
않습니다. TAKE BOTH로 같은 영상을 Live에 올리면 두 decoder의 transport가 연결되어
어느 채널이 선택되어 있어도 Play/Pause/Stop/처음으로/탐색이 양쪽에 함께 적용됩니다.
이후 한쪽에 다른 콘텐츠를 개별 TAKE하면 연결이 자동 해제되고 다시 독립적으로
제어됩니다. 같은 시스템 장치에 동일 오디오가 중복 출력되지 않도록 연동 중에는
Broadcast decoder만 영상 오디오를 출력하고 Venue decoder는 자동 음소거됩니다.

## 종료, BLACK, Fade

Stop은 위치를 0으로 돌리고 해당 Live를 BLACK으로 전환합니다. 자연 종료와 치명적
backend 오류도 마지막 프레임을 남기지 않고 BLACK으로 전환합니다. BLACK, PDF,
VIDEO 사이에는 고정 250ms 선형 fade-out/fade-in을 사용합니다. 영상 탭에는 Fade 입력과
별도 현황 문구를 표시하지 않으며 상태 안내는 Controller 하단 상태바를 사용합니다. 새
콘텐츠 준비 실패 시 fade와 상태 commit을 시작하지 않습니다.

## 배경음악 충돌 정책

영상 Preview와 TAKE는 배경음악에 영향을 주지 않습니다. 영상 Play가 시작될 때 음악이
PLAYING이면 PauseReason을 VIDEO로 기록하고 Pause합니다. 이후 영상 Pause, Stop,
Ended, Error 또는 모든 영상 종료가 발생해도 음악을 자동 재개하지 않습니다. 운영자가
직접 Play해야 합니다. 서로 다른 두 영상이 동시에 재생돼도 첫 Play에서만 음악 상태가
변합니다.

## YouTube 영상 스트리밍

선택한 영상 폴더에 `video_url.json`이 있으면 로컬 영상 뒤에 공개 단일 YouTube URL을
자동으로 합칩니다. `URL 추가`와 `URL 삭제`는 이 고정 파일을 atomic write하며 파일명을
따로 묻지 않습니다. URL Cue 시 yt-dlp가 영상과 오디오가 함께 든 progressive 스트림을
worker에서 해석하고 Qt Multimedia에 전달합니다. 해석된 임시 URL은 메모리에만 두며
JSON에 저장하거나 다운로드하지 않습니다. 이후 첫 프레임 준비, TAKE, Play/Pause/Stop,
탐색, 양쪽 Cue와 TAKE BOTH는 로컬 영상과 같은 상태 머신을 사용합니다.

네트워크 영상은 스트림 해석 시간을 포함해 최대 30초 동안 Cue를 기다립니다. 실패하면
TAKE를 활성화하지 않고 기존 Live를 유지합니다. 공개 단일 영상만 지원하며 playlist,
로그인, 쿠키, 비공개·연령 제한 영상은 지원하지 않습니다. 외부 서비스 변경과 네트워크
상태에 따라 실패할 수 있으므로 예배 전에 실제 운영 PC에서 끝까지 검증하십시오.

## YouTube 오디오 스트리밍

배경음악 재생목록은 선택한 음악 폴더의 로컬 오디오 파일 전체로 구성됩니다. 폴더에
`youtube_url.json`이 있으면 공개된 단일 YouTube 영상 URL을 뒤에 합치고, 파일이 없으면
URL은 불러오지 않습니다. URL 추가·삭제와 fallback 변경은 고정 파일에 즉시 atomic
write되며 사용자가 재생목록 파일명을 지정하지 않습니다.
URL 추가 시 yt-dlp 메타데이터 조회를 worker에서 실행하고 제목, 재생 시간, video ID와
원본 URL을 갱신합니다. 조회에 실패해도 URL과 오류 상태는 재생목록에 남고 앱과 로컬
미디어 기능은 계속 동작합니다. playlist URL 전체 import, 채널/검색, 로그인, 쿠키,
비공개·연령 제한 영상과 파일 다운로드는 지원하지 않습니다.

Play 또는 Prepare 시 yt-dlp가 best-audio 스트림을 다시 해석하고 오디오 전용 libmpv에
전달합니다. 해석된 URL은 만료될 수 있으므로 메모리에서만 사용하며 JSON에 저장하거나
영구 캐시하지 않습니다. URL과 함께 yt-dlp가 반환한 User-Agent, Referer와 기타 HTTP
헤더를 libmpv에 전달하고, 지원되는 libmpv에서는 권장 HTTP 요청 크기도 적용합니다.
PREPARING, LOADING, PLAYING, PAUSED, BUFFERING, ENDED와 ERROR는 Qt 로컬 backend와
같은 공통 상태로 UI에 전달됩니다. 준비가 30초를 넘거나, 15초 이상 buffering이
계속되거나, 재생 도중 스트림이 끊기면 오류로 처리합니다.

macOS에서는 python-mpv의 native event callback이 전달되지 않는 환경이 있어 libmpv
property를 Qt 메인 스레드의 짧은 타이머로 함께 확인합니다. 이벤트와 폴링은 같은 상태
변환 함수를 사용하고 중복 신호를 억제하므로 준비 완료, 재생 위치와 종료 처리가 동일하게
동작합니다.

YouTube 항목에 로컬 fallback을 지정하면 스트리밍 준비 또는 재생 실패 시
`Streaming failed — playing local fallback`을 표시하고 Qt local backend로 전환합니다.
fallback도 없거나 재생할 수 없으면 항목은 ERROR로 남습니다. 반복과 다음 곡 정책은
현재 폴더 재생목록의 반복과 다음 곡 정책을 그대로 따릅니다.

Python 의존성은 `yt-dlp`와 `python-mpv`이며, 후자는 별도 시스템 libmpv를 필요로
합니다. macOS는 `brew install mpv`, Windows는 `mpv-2.dll`을 포함한 libmpv 빌드를
설치합니다. Windows backend는 `CHURCH_PRESENTER_LIBMPV_DIR`, 실행 파일 위치,
`libmpv`/`mpv` 하위 폴더와 `PATH` 순서로 DLL을 찾습니다. 패키징 시 DLL 또는 dylib의
위치와 mpv 라이선스를 별도로 확인해야 합니다. YouTube extractor는 외부 서비스 변경에
영향을 받으므로 운영 전 `python -m pip install --upgrade "yt-dlp[default]"`와 실제 URL 재생을
검증하십시오. 다운로드 기능은 제공하지 않으며, 콘텐츠 이용 조건과 재생 권한은
사용자가 확인해야 합니다.

영상 탭의 `기능 최신화`는 현재 앱을 실행한 프로젝트 `.venv`의 Python으로
`yt-dlp[default]`와 `python-mpv`를 업데이트합니다. `yt-dlp[default]`에는 호환되는
`yt-dlp-ejs`가 포함됩니다. 셸이나 시스템 Python으로 우회하지 않으며 macOS와 Windows에서
같은 명령 구조를 사용합니다. 실행 중 로드된 모듈은 교체되지 않으므로 완료 후 앱을 다시
시작해야 합니다. Deno는 Python 패키지가 아니므로 버튼이 설치하지 않으며, 완료 결과에서
PATH 감지 여부를 안내합니다.

`화면 / 오디오 설정`의 출력 장치는 로컬 음악, 영상과 YouTube 오디오에 함께
적용합니다. YouTube backend는 Qt 장치의 native ID와 설명을 libmpv 장치 목록에
대조합니다. 운영 체제나 드라이버가 서로 다른 이름을 제공해 안전하게 대응할 수 없으면
시스템 기본 출력으로 전환하고 로그에 선택 장치와 fallback을 남깁니다.

## 오류 해결

- 파일 없음: 파일을 원래 위치로 복구하거나 라이브러리/재생목록에서 다시 선택합니다.
- 지원하지 않는 코덱: 권장 MP4 H.264/AAC로 다시 인코딩합니다.
- 첫 프레임 준비 실패: 로컬 파일은 10초, YouTube 영상은 30초 안에 실제 프레임을 얻지
  못한 경우입니다. 다시 Cue하고, 로컬 파일이면 권한·손상·코덱을, YouTube 영상이면
  네트워크와 공개 상태를 확인합니다. 상세 Qt media/playback 상태와 decoder 오류는
  애플리케이션 로그에 기록됩니다.
- 영상은 나오고 소리가 없음: 앱 음소거, 영상 볼륨과 `화면 / 오디오 설정`의 공통
  출력 장치를 확인합니다. 시스템 설정을 따르려면 `시스템 기본 출력`을 선택합니다.
- YouTube 영상 Cue 실패: 최신 yt-dlp, 네트워크와 영상 공개 상태를 확인합니다. Qt
  Multimedia가 해당 progressive 스트림을 재생하지 못한 상세 원인은 로그에 남습니다.
- YouTube 음악 정보만 나오고 재생되지 않음: 최신 yt-dlp인지 확인하고, Windows에서는
  `mpv-2.dll`의 비트 수가 Python과 같은지와 `CHURCH_PRESENTER_LIBMPV_DIR` 또는
  실행 파일 옆 `libmpv` 폴더를 확인합니다. 상세 원인은 애플리케이션 로그에 남습니다.
- 일부 MKV/MOV/AVI 실패: Windows Media Foundation/Qt FFmpeg backend 및 GPU driver
  차이가 원인일 수 있습니다. 운영용 파일은 권장 MP4로 변환합니다.

사용자 화면에는 간결한 오류만 표시하고 상세 예외는 회전 로그에 남습니다. 실패한
Preview는 기존 Live를 바꾸지 않으며 Live 중 치명적 오류만 해당 채널을 BLACK으로
전환합니다.

## Qt Multimedia 제한과 확장

로컬/YouTube 영상과 로컬 배경음악 backend는 PySide6 Qt Multimedia입니다. YouTube
영상은 yt-dlp가 해석한 임시 progressive URL을 Qt에 전달하고, YouTube 오디오는
yt-dlp + libmpv adapter를 사용합니다. 컨테이너/코덱, 하드웨어 가속,
탐색 정밀도, 첫 프레임 시간과 종료 이벤트는 OS별로 다를 수 있습니다. backend는
`MediaPlaybackBackend` 뒤에 격리되어 있습니다. 기존 영상 backend는 libmpv로
교체하지 않았습니다.

Broadcast와 Venue의 다른 영상을 동시에 재생하면 decoder 두 개를 사용합니다. 각
채널에서 Live 재생 중 다음 영상을 Cue하면 일시적으로 Preview decoder도 사용하므로
최대 네 개의 영상 decoder가 동작할 수 있습니다. Controller, Simulation, 실제 출력은
같은 네이티브 `QVideoFrame`을 각 `QVideoWidget` sink로 전달받습니다. Preview 첫
프레임과 화면 전환 순간만 `QImage`로 변환하며, Live의 매 프레임을 Python GUI
스레드에서 이미지로 변환하고 다시 그리지 않습니다. 현재 macOS offscreen smoke에서는
640x360 10fps 12초 샘플의 단일 Cue, 양쪽 동시 Cue, 같은 소스 재Cue, 연속 프레임
진행과 Play/Pause/Stop을 확인했으며 Windows 성능 수치는 아직 측정하지 않았습니다.

macOS에서 `Failed setup for format videotoolbox_vld`가 출력되더라도 뒤이어 실제 첫
프레임과 위치 진행이 확인되면 Qt FFmpeg가 CPU 변환으로 대체한 경고이며 Cue 실패로
판정하지 않습니다. 사용자 화면의 Cue 오류와 애플리케이션 로그의 최종 backend 상태를
함께 확인해야 합니다.

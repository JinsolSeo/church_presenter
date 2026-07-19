# 로컬 미디어 재생

## 지원 형식과 코덱

영상 라이브러리는 `.mp4`, `.mov`, `.mkv`, `.avi`, 음악 라이브러리는 `.mp3`,
`.wav`, `.m4a`, `.flac`, `.ogg`를 검색합니다. 확장자는 컨테이너 형식일 뿐 실제
영상·음성 코덱 지원을 보장하지 않습니다. 같은 MOV나 MKV도 내부 코덱에 따라 한
컴퓨터에서는 재생되고 다른 컴퓨터에서는 실패할 수 있습니다.

가장 안정적인 운영용 영상 권장값은 MP4 컨테이너, H.264 영상, AAC 오디오,
1920x1080, 30 또는 60fps입니다. 예배 전에 실제 운영 PC와 HDMI 출력에서 모든
파일을 끝까지 시험하십시오.

## Cue / TAKE / Play

파일 선택은 음소거된 Preview decoder를 시작하고 첫 실제 프레임에서 정지합니다.
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
VIDEO 사이에는 기본 250ms 선형 fade-out/fade-in을 사용하며 0–2000ms로 변경할 수
있습니다. 새 콘텐츠 준비 실패 시 fade와 상태 commit을 시작하지 않습니다.

## 배경음악 충돌 정책

영상 Preview와 TAKE는 배경음악에 영향을 주지 않습니다. 영상 Play가 시작될 때 음악이
PLAYING이면 PauseReason을 VIDEO로 기록하고 Pause합니다. 이후 영상 Pause, Stop,
Ended, Error 또는 모든 영상 종료가 발생해도 음악을 자동 재개하지 않습니다. 운영자가
직접 Play해야 합니다. 서로 다른 두 영상이 동시에 재생돼도 첫 Play에서만 음악 상태가
변합니다.

## 오류 해결

- 파일 없음: 파일을 원래 위치로 복구하거나 라이브러리/재생목록에서 다시 선택합니다.
- 지원하지 않는 코덱: 권장 MP4 H.264/AAC로 다시 인코딩합니다.
- 첫 프레임 준비 실패: 10초 안에 실제 프레임을 얻지 못한 경우입니다. 다시 Cue하고 파일
  권한과 손상 여부를 확인한 뒤, 반복되면 권장 MP4 H.264/AAC로 변환합니다. 상세 Qt
  media/playback 상태와 decoder 오류는 애플리케이션 로그에 기록됩니다.
- 영상은 나오고 소리가 없음: 앱 음소거, 영상 볼륨과 `화면 / 오디오 설정`의 공통
  출력 장치를 확인합니다. 시스템 설정을 따르려면 `시스템 기본 출력`을 선택합니다.
- 일부 MKV/MOV/AVI 실패: Windows Media Foundation/Qt FFmpeg backend 및 GPU driver
  차이가 원인일 수 있습니다. 운영용 파일은 권장 MP4로 변환합니다.

사용자 화면에는 간결한 오류만 표시하고 상세 예외는 회전 로그에 남습니다. 실패한
Preview는 기존 Live를 바꾸지 않으며 Live 중 치명적 오류만 해당 채널을 BLACK으로
전환합니다.

## Qt Multimedia 제한과 확장

Phase 2 backend는 PySide6 Qt Multimedia입니다. 컨테이너/코덱, 하드웨어 가속,
탐색 정밀도, 첫 프레임 시간과 종료 이벤트는 OS별로 다를 수 있습니다. backend는
`MediaPlaybackBackend` 뒤에 격리되어 있으므로 Windows 검증에서 필요하면 Phase 3에
libmpv adapter를 추가할 수 있습니다.

Broadcast와 Venue의 다른 영상을 동시에 재생하면 decoder 두 개를 사용합니다. 각
채널에서 Live 재생 중 다음 영상을 Cue하면 일시적으로 Preview decoder도 사용하므로
최대 네 개의 영상 decoder가 동작할 수 있습니다. Controller, Simulation, 실제 출력은
같은 디코딩 프레임을 공유합니다. 현재 macOS offscreen smoke에서는 640x360 10fps
12초 샘플의 단일 Cue, 양쪽 동시 Cue, 같은 소스 재Cue, 연속 프레임 진행과
Play/Pause/Stop을 확인했으며 Windows 성능 수치는 아직 측정하지 않았습니다.

macOS에서 `Failed setup for format videotoolbox_vld`가 출력되더라도 뒤이어 실제 첫
프레임과 위치 진행이 확인되면 Qt FFmpeg가 CPU 변환으로 대체한 경고이며 Cue 실패로
판정하지 않습니다. 사용자 화면의 Cue 오류와 애플리케이션 로그의 최종 backend 상태를
함께 확인해야 합니다.

# Windows Phase 2 실기기 검증 체크리스트

## 권장 환경

- Windows 운영자 모니터 + ATEM용 Broadcast HDMI + Venue HDMI
- Windows 디스플레이 배율 100%, 125%, 150%
- MP4 H.264/AAC 1920x1080 30fps와 60fps 기준 파일
- 실제 운영에 사용할 MOV, MKV, AVI 및 음악 파일

각 항목은 실제 장비에서 확인한 뒤 날짜, PC/GPU, Qt/Python 버전과 결과를 기록합니다.
현재 개발 Mac의 자동 테스트 결과를 Windows 실기기 통과로 간주하지 않습니다.

## 영상

- [ ] MP4 H.264/AAC Preview 첫 프레임과 재생
- [ ] MOV 재생 또는 명확한 지원 오류
- [ ] MKV 재생 또는 명확한 지원 오류
- [ ] AVI 재생 또는 명확한 지원 오류
- [ ] 영상 오디오가 시스템 기본 출력으로 재생
- [ ] 선택과 TAKE만으로 영상/오디오가 시작되지 않음
- [ ] 탐색, Pause/Resume, 처음으로 이동
- [ ] Stop 후 해당 Live BLACK
- [ ] 자연 종료 후 해당 Live BLACK
- [ ] 손상/삭제/지원하지 않는 코덱 오류 후 앱 유지
- [ ] Broadcast HDMI 실제 출력
- [ ] Venue HDMI 실제 출력
- [ ] 서로 다른 영상 양쪽 동시 재생
- [ ] 동일 영상 Send to Both / TAKE BOTH
- [ ] 한쪽 Cue 실패 시 양쪽 기존 Live 유지
- [ ] BLACK/PDF/VIDEO 고정 250ms Fade

## 배경음악

- [ ] MP3, WAV, M4A, FLAC, OGG 지원 여부 기록
- [ ] 재생/Pause/Stop/탐색/볼륨/음소거
- [ ] 자동 다음 곡
- [ ] 반복 없음 마지막 곡 정지
- [ ] 한 곡 반복
- [ ] 전체 반복 마지막→첫 곡
- [ ] Previous 3초 정책
- [ ] JSON 저장/복원 및 삭제된 파일 경고
- [ ] 영상 Preview와 TAKE 시 음악 유지
- [ ] 영상 Play 시 음악 자동 Pause 안내
- [ ] 영상 종료/Stop/Error 후 음악 자동 재개 안 됨
- [ ] 공개 단일 YouTube URL 메타데이터 조회
- [ ] YouTube Play/Pause/Stop/Seek/Previous/Next 및 반복
- [ ] PREPARING/BUFFERING/ERROR 상태에서 Controller 응답 유지
- [ ] 네트워크 차단 시 로컬 fallback 전환 문구와 재생
- [ ] fallback 없음/삭제 시 항목 오류만 발생하고 로컬 미디어 유지
- [ ] yt-dlp 미설치 상태에서 로컬 음악/영상 유지
- [ ] `mpv-2.dll` 없음 또는 로드 실패 상태에서 앱 유지
- [ ] 종료 후 libmpv thread/process 잔류 없음

Windows 개발 환경에서는 `python -m pip install -e ".[dev]"`로 Python wrapper와
yt-dlp를 설치한 뒤, `mpv-2.dll`을 제공하는 libmpv 빌드의 디렉터리를 `PATH`에
추가합니다. 배포 패키지는 DLL을 실행 파일 옆에 포함하고 대상 PC에서 새 프로세스로
실행해 로드 여부를 확인합니다. YouTube 검증 전에는
`python -m pip install --upgrade yt-dlp`로 extractor를 갱신합니다.

## 운영 안정성

- [ ] 출력 중 한 화면 분리 시 해당 채널 BLACK 및 앱 유지
- [ ] 빠른 연속 Cue에서 오래된 완료 신호가 새 Preview를 덮지 않음
- [ ] 2시간 연속 영상/음악 운용 중 메모리·CPU·GPU 기록
- [ ] 두 영상 Live + 두 다음 영상 Cue의 최대 decoder 부하 기록
- [ ] 앱 종료 시 두 출력 BLACK
- [ ] 앱 종료 후 `church-presenter`/Python 프로세스 잔류 없음
- [ ] 디스플레이 배율별 Controller 조작 가능

Qt Multimedia에서 운영 파일의 재생 실패, 오디오만 재생, 부정확한 탐색, 종료 신호
누락 또는 GPU 호환 문제가 반복되면 파일을 권장 MP4로 재인코딩해 비교합니다. 권장
파일도 실패하면 로그와 파일의 `ffprobe` 결과를 보존하고 Phase 3 libmpv backend
검토 항목으로 등록합니다.

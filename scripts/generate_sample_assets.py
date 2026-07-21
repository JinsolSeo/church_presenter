from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = ROOT / "sample_assets"
OUTPUT = SAMPLE_ROOT / "pdfs" / "sample_service.pdf"


def find_korean_font() -> Path | None:
    candidates = [
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf"),
    ]
    return next((path for path in candidates if path.is_file()), None)


def add_page(
    document: fitz.Document,
    width: float,
    height: float,
    title: str,
    body: str,
    page_number: int,
    font_path: Path | None,
    title_size: float,
    body_size: float,
) -> None:
    page = document.new_page(width=width, height=height)
    page.draw_rect(page.rect, color=(0.08, 0.12, 0.2), fill=(0.08, 0.12, 0.2))
    accent = fitz.Rect(0, 0, width, max(10, height * 0.025))
    page.draw_rect(accent, color=(0.1, 0.75, 0.55), fill=(0.1, 0.75, 0.55))
    font_args = {"fontname": "sample", "fontfile": str(font_path)} if font_path else {}
    page.insert_textbox(
        fitz.Rect(width * 0.08, height * 0.15, width * 0.92, height * 0.42),
        title,
        fontsize=title_size,
        color=(1, 1, 1),
        align=fitz.TEXT_ALIGN_CENTER,
        **font_args,
    )
    page.insert_textbox(
        fitz.Rect(width * 0.1, height * 0.45, width * 0.9, height * 0.82),
        body,
        fontsize=body_size,
        lineheight=1.35,
        color=(0.85, 0.9, 0.96),
        align=fitz.TEXT_ALIGN_CENTER,
        **font_args,
    )
    page.insert_text(
        fitz.Point(width * 0.9, height * 0.94),
        str(page_number),
        fontsize=max(10, body_size * 0.65),
        color=(0.55, 0.65, 0.75),
        **font_args,
    )


def generate_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    font = find_korean_font()
    pages = [
        (960, 540, "주일 예배", "마음과 뜻을 모아 함께 예배드립니다.", 52, 25),
        (800, 600, "오늘의 말씀", "여호와는 나의 목자시니 내게 부족함이 없으리로다.", 48, 23),
        (
            595,
            842,
            "세로형 안내",
            "휴대전화는 무음으로 전환해 주십시오.\n예배 중 이동은 안내를 따라 주십시오.",
            42,
            20,
        ),
        (960, 540, "찬양", "기쁨으로 노래하며 감사함으로 주 앞에 나아갑니다.", 78, 28),
        (
            960,
            540,
            "긴 본문 레이아웃",
            "말씀을 듣고 마음에 새기며 삶의 자리에서 사랑과 섬김을 실천하기로 "
            "다짐합니다. 서로를 돌아보고 평화를 이루는 한 주가 되기를 소망합니다.",
            40,
            20,
        ),
        (800, 600, "큰 글씨", "함께 기도하겠습니다", 82, 42),
        (
            960,
            540,
            "작은 글씨 검증",
            "공지 1. 다음 주 예배는 같은 시간에 시작합니다.\n"
            "공지 2. 교회학교는 교육관에서 모입니다.\n"
            "공지 3. 예배 후 교제 시간이 있습니다.",
            36,
            14,
        ),
        (
            595,
            842,
            "마침",
            "주님의 평안이 여러분과 함께하시기를 바랍니다.\n안전하게 돌아가십시오.",
            54,
            24,
        ),
    ]
    document = fitz.open()
    for index, (width, height, title, body, title_size, body_size) in enumerate(pages, 1):
        add_page(document, width, height, title, body, index, font, title_size, body_size)
    document.set_metadata(
        {
            "title": "Church Presenter Sample Service",
            "author": "Church Presenter",
            "subject": "Copyright-free generated test document",
        }
    )
    document.save(OUTPUT, garbage=4, deflate=True)
    document.close()
    print(f"Generated {OUTPUT} ({len(pages)} pages)")
    if font is None:
        print("No Korean system font found; PDF text fallback may be limited.", file=sys.stderr)


def generate_audio() -> list[Path]:
    audio_dir = SAMPLE_ROOT / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    sample_rate = 44_100
    tracks = ((440.0, 5), (523.25, 7), (659.25, 9))
    for index, (frequency, duration) in enumerate(tracks, 1):
        path = audio_dir / f"sample_track_{index:02d}.wav"
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(sample_rate)
            frames = bytearray()
            for sample in range(sample_rate * duration):
                fade = min(1.0, sample / 2205, (sample_rate * duration - sample) / 2205)
                value = round(
                    9000 * fade * math.sin(2 * math.pi * frequency * sample / sample_rate)
                )
                frames.extend(struct.pack("<h", value))
            stream.writeframes(frames)
        outputs.append(path)
        print(f"Generated {path} ({duration}s)")
    return outputs


def generate_playlist(tracks: list[Path]) -> None:
    playlist_dir = SAMPLE_ROOT / "playlists"
    playlist_dir.mkdir(parents=True, exist_ok=True)
    path = playlist_dir / "sample_playlist.json"
    payload = {
        "version": 2,
        "name": "sample_playlist",
        "current_index": 0,
        "repeat_mode": "none",
        "items": [
            {
                "id": f"sample-track-{index}",
                "source_type": "local_file",
                "source": f"../audio/{track.name}",
                "source_relative": True,
                "display_title": f"Sample Track {index:02d}",
                "duration_ms": duration * 1000,
                "availability": "ready",
                "error_message": "",
                "metadata": {},
                "fallback_path": None,
                "fallback_relative": False,
            }
            for index, (track, duration) in enumerate(zip(tracks, (5, 7, 9), strict=True), 1)
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {path}")


def generate_video_with_ffmpeg(path: Path) -> bool:
    executable = shutil.which("ffmpeg")
    if executable is None:
        return False
    command = [
        executable,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=10:duration=12",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=330:sample_rate=44100:duration=12",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode == 0:
        return True
    print(f"FFmpeg sample generation failed: {result.stderr}", file=sys.stderr)
    return False


def generate_video_with_qt(path: Path) -> bool:
    from PySide6.QtCore import QSize, QTimer, QUrl
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    from PySide6.QtMultimedia import (
        QMediaCaptureSession,
        QMediaFormat,
        QMediaRecorder,
        QVideoFrame,
        QVideoFrameInput,
    )

    application = QGuiApplication.instance() or QGuiApplication([])
    session = QMediaCaptureSession()
    frame_input = QVideoFrameInput()
    recorder = QMediaRecorder()
    session.setVideoFrameInput(frame_input)
    session.setRecorder(recorder)
    media_format = QMediaFormat()
    media_format.setFileFormat(QMediaFormat.FileFormat.MPEG4)
    # MPEG-4 Part 2 provides a software fallback when macOS VideoToolbox cannot
    # create an H.264 compression session in headless development environments.
    media_format.setVideoCodec(QMediaFormat.VideoCodec.MPEG4)
    recorder.setMediaFormat(media_format)
    recorder.setVideoResolution(QSize(640, 360))
    recorder.setVideoFrameRate(10.0)
    recorder.setOutputLocation(QUrl.fromLocalFile(str(path)))
    frame_index = 0
    finished = False

    def send_frame() -> None:
        nonlocal frame_index
        if frame_index >= 120:
            frame_input.sendVideoFrame(QVideoFrame())
            QTimer.singleShot(300, recorder.stop)
            return
        image = QImage(640, 360, QImage.Format.Format_RGB32)
        hue = (frame_index * 3) % 360
        image.fill(QColor.fromHsv(hue, 180, 110))
        painter = QPainter(image)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Arial", 32, QFont.Weight.Bold))
        painter.drawText(
            image.rect(),
            0x84,
            f"Church Presenter Sample\n{frame_index / 10:04.1f}s · frame {frame_index}",
        )
        painter.end()
        frame = QVideoFrame(image)
        frame.setStartTime(frame_index * 100_000)
        frame.setEndTime((frame_index + 1) * 100_000)
        if frame_input.sendVideoFrame(frame):
            frame_index += 1

    def state_changed(state: QMediaRecorder.RecorderState) -> None:
        nonlocal finished
        if state is QMediaRecorder.RecorderState.StoppedState and frame_index >= 120:
            finished = True
            application.quit()

    frame_input.readyToSendVideoFrame.connect(send_frame)
    recorder.recorderStateChanged.connect(state_changed)
    QTimer.singleShot(20_000, application.quit)
    recorder.record()
    application.exec()
    recorder.stop()
    return finished and path.is_file() and path.stat().st_size > 0


def generate_video() -> None:
    video_dir = SAMPLE_ROOT / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    path = video_dir / "sample_video.mp4"
    path.unlink(missing_ok=True)
    if generate_video_with_ffmpeg(path) or generate_video_with_qt(path):
        print(f"Generated {path} ({path.stat().st_size / (1024 * 1024):.1f} MB)")
        return
    print(
        "Could not generate sample_video.mp4. Install FFmpeg and rerun this script.",
        file=sys.stderr,
    )


def main() -> int:
    generate_pdf()
    tracks = generate_audio()
    generate_playlist(tracks)
    generate_video()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

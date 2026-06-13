"""YouTube 자막 추출 스크립트 v2
사용법:
    python scripts/yt_transcript.py "https://youtu.be/VIDEO_ID"
    python scripts/yt_transcript.py "https://youtu.be/VIDEO_ID" --lang en
    python scripts/yt_transcript.py "https://youtu.be/VIDEO_ID" --mode clean
    python scripts/yt_transcript.py "https://youtu.be/VIDEO_ID" --mode dialogue
    python scripts/yt_transcript.py "https://youtu.be/VIDEO_ID" --mode clean --smart-section
    python scripts/yt_transcript.py "https://youtu.be/VIDEO_ID" --list
    python scripts/yt_transcript.py "https://youtu.be/VIDEO_ID" --output transcript.txt

출력 모드:
    raw        타임스탬프 + 모든 세그먼트 그대로 (기본값)
    clean      세그먼트 병합, 타임스탬프 60초 간격, 문장 단위 정리
    dialogue   화자 태그 기반 대화 포맷, 챕터 구분
"""

import argparse
import re
import sys
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound, TranscriptsDisabled, VideoUnavailable
)

# ── 자주 등장하는 자동 생성 오인식 교정 사전 ──
TERM_FIX = {
    "오픈클로": "OpenClaude", "오픈 클로": "OpenClaude",
    "하네스 엔지니어링": "harness engineering",
    "나이트로": "Nitro", "바이브랩스": "VibeLabs",
    "x402": "X402 (XMTP 계열 추정)", "ERC-8004": "ERC-7804 (추정)",
    "Kaito": "Kaito", "카이토": "Kaito",
    "GPTO": "GPTO", "AEO": "AEO", "GEO": "GEO",
    "앤트로픽": "Anthropic", "에이전틱": "agentic",
    "네트워크 스테이트": "Network State", "네트워크 스쿨": "Network School",
    "에메랄드 캐슬": "Emerald Castle",
    "바이브 코딩": "vibe coding", "코파일럿": "Copilot",
    "발라지": "Balaji", "발라지라고": "Balaji Srinivasan",
    "어크로스": "Across", "아웃스탠딩": "Outstanding",
}

# ── 한국어 종결어미 (문장 경계 감지용) ──
SENTENCE_ENDS = re.compile(r'[다요죠네까며데게나지고서도은는을를의가에와과로](?:\s|$)')

# 화자 태그 패턴
SPEAKER_TAG = re.compile(r'\[(김서준|노정석|최승준|[A-Za-z\s]+)\]')


def extract_video_id(url: str) -> str:
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for p in patterns:
        m = re.search(p, url.strip())
        if m:
            return m.group(1)
    raise ValueError(f"URL에서 video ID를 찾을 수 없습니다: {url}")


def apply_term_fixes(text: str) -> str:
    for wrong, correct in TERM_FIX.items():
        text = text.replace(wrong, correct)
    return text


def merge_segments(segments, min_gap=2.0):
    """짧은 간격의 세그먼트를 병합하여 자연스러운 문장으로 만든다."""
    if not segments:
        return []

    merged = []
    current = segments[0]

    for seg in segments[1:]:
        gap = seg.start - (current.start + current.duration)
        if gap < min_gap:
            current.text += " " + seg.text
            current.duration = seg.start + seg.duration - current.start
        else:
            merged.append(current)
            current = seg
    merged.append(current)
    return merged


def detect_chapter_breaks(segments, min_gap=5.0):
    """긴 일시정지를 챕터 경계로 감지한다."""
    chapters = []
    for i, seg in enumerate(segments):
        if i == 0:
            continue
        prev = segments[i - 1]
        gap = seg.start - (prev.start + prev.duration)
        if gap >= min_gap:
            chapters.append((i, seg.start))
    return chapters


def format_raw(segments, language_code="?") -> str:
    lines = [f"[{s.start:.1f}s] {s.text}" for s in segments]
    return "\n".join(lines)


def format_clean(segments, language_code="?", term_fix=False):
    """세그먼트 병합 + 60초 간격 타임스탬프."""
    merged = merge_segments(segments, min_gap=2.0)
    lines = []
    last_ts = -999

    for s in merged:
        text = s.text.strip()
        if term_fix:
            text = apply_term_fixes(text)

        # 60초마다 타임스탬프 삽입
        mins = int(s.start // 60)
        secs = int(s.start % 60)
        ts_label = f"[{mins}:{secs:02d}]"

        if s.start - last_ts >= 60:
            lines.append(f"\n{ts_label} {text}")
            last_ts = s.start
        else:
            lines.append(text)

    return "\n".join(lines).strip()


def format_dialogue(segments, language_code="?", term_fix=False, smart_section=True):
    """화자 태그 기반 대화 포맷 + 챕터 구분선."""
    merged = merge_segments(segments, min_gap=1.5)
    chapters = detect_chapter_breaks(merged, min_gap=5.0) if smart_section else []

    chapter_indices = {idx: ts for idx, ts in chapters}

    lines = []
    current_speaker = None

    for i, s in enumerate(merged):
        text = s.text.strip()
        if term_fix:
            text = apply_term_fixes(text)

        # 챕터 경계
        if i in chapter_indices:
            mins = int(chapter_indices[i] // 60)
            secs = int(chapter_indices[i] % 60)
            lines.append(f"\n── [{mins}:{secs:02d}] ──")

        # 화자 태그 추출
        speaker_match = SPEAKER_TAG.search(text)
        speaker = speaker_match.group(1) if speaker_match else None

        # 화자 태그 제거한 본문
        clean_text = SPEAKER_TAG.sub("", text).strip()

        if speaker and speaker != current_speaker:
            current_speaker = speaker
            lines.append(f"\n[{speaker}] {clean_text}")
        elif speaker:
            lines.append(clean_text)
        else:
            lines.append(clean_text)

    return "\n".join(lines).strip()


def get_transcript_info(video_id: str, preferred_langs: list[str]):
    """자막 메타데이터 반환 (언어, 생성 여부 등)."""
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id, languages=preferred_langs)
    info = {
        "language_code": transcript.language_code,
        "language": transcript.language,
        "is_generated": transcript.is_generated,
        "snippet_count": len(transcript),
    }
    return info, list(transcript)


def list_transcripts(video_id: str):
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)
    result = []
    for t in transcript_list:
        result.append({
            "language": t.language,
            "language_code": t.language_code,
            "is_generated": t.is_generated,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description="YouTube 자막 추출 v2")
    parser.add_argument("url", help="YouTube URL 또는 video ID")
    parser.add_argument("--lang", default="ko,en", help="선호 언어, 쉼표 구분 (기본값: ko,en)")
    parser.add_argument("--mode", default="raw",
                        choices=["raw", "clean", "dialogue"],
                        help="출력 모드: raw(기본), clean(병합), dialogue(대화)")
    parser.add_argument("--output", "-o", help="출력 파일 경로")
    parser.add_argument("--list", action="store_true", help="사용 가능한 자막 목록만 출력")
    parser.add_argument("--no-term-fix", action="store_true", help="용어 자동 교정 비활성화")
    parser.add_argument("--no-smart-section", action="store_true", help="자동 챕터 구분 비활성화")
    parser.add_argument("--info", action="store_true", help="자막 메타데이터만 출력")
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    preferred = [l.strip() for l in args.lang.split(",")]

    # --list
    if args.list:
        try:
            transcripts = list_transcripts(video_id)
        except (VideoUnavailable, TranscriptsDisabled) as e:
            print(f"오류: {e}", file=sys.stderr)
            sys.exit(1)

        for t in transcripts:
            tag = "manual" if not t["is_generated"] else "auto"
            print(f"  {t['language']} ({t['language_code']}) [{tag}]")
        return

    # --info
    if args.info:
        try:
            info, _ = get_transcript_info(video_id, preferred)
        except (NoTranscriptFound, VideoUnavailable, TranscriptsDisabled) as e:
            print(f"오류: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"언어: {info['language']} ({info['language_code']})")
        print(f"자동생성: {'yes' if info['is_generated'] else 'no'}")
        print(f"세그먼트: {info['snippet_count']}개")
        return

    # 자막 가져오기
    try:
        info, segments_list = get_transcript_info(video_id, preferred)
    except NoTranscriptFound:
        print(f"'{preferred}' 언어 자막이 없습니다. 사용 가능한 자막:", file=sys.stderr)
        try:
            for t in list_transcripts(video_id):
                tag = "manual" if not t["is_generated"] else "auto"
                print(f"  - {t['language']} ({t['language_code']}) [{tag}]", file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)
    except (VideoUnavailable, TranscriptsDisabled) as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)

    # 데이터클래스 객체를 dict로 변환
    segments = []
    for s in segments_list:
        segments.append(type('Segment', (), {
            'text': s.text,
            'start': s.start,
            'duration': s.duration,
        }))

    term_fix = not args.no_term_fix
    smart_section = not args.no_smart_section and args.mode == "dialogue"

    if args.mode == "raw":
        output = format_raw(segments)
    elif args.mode == "clean":
        output = format_clean(segments, info["language_code"], term_fix)
    elif args.mode == "dialogue":
        output = format_dialogue(segments, info["language_code"], term_fix, smart_section)
    else:
        output = format_raw(segments)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"{args.output}에 저장됨 ({len(output)} 자, 언어: {info['language_code']}, 모드: {args.mode})")
    else:
        print(output)


if __name__ == "__main__":
    main()

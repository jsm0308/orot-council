# fdparty — 개발 에이전트

fdparty 개발팀을 위한 **4-Mode CTO 에이전트**. Cursor IDE + Claude로 구동.

## 구조

```
.cursor/rules/
  fdparty-agent.mdc    ← 4-Mode 시스템 프롬프트 (alwaysApply)
  adr.mdc              ← ADR 자동 기록
  ceo-memo.mdc         ← 개발 메모 자동 누적
  decision-council.mdc ← Mode B 아키텍트 소집 (온디맨드)
  report-review.mdc    ← 코드 검수 (온디맨드)
council/
  protocol.md          ← 아키텍트 소집 프로토콜
  agents/
    CLAUDE.md          ← CTO 에이전트 오케스트레이터 지시서
    아키텍트/           ← Mode B 렌즈 3명 (기술/효율/실행)
    검수/              ← 코드 검수 비서 1명
decisions/LOG.md       ← 결정·ADR 인덱스 (SSOT)
CEO-memo.txt           ← 개발 메모 누적 (append-only)
runner/                ← Anthropic API로 아키텍트 병렬 호출 (CLI)
```

## 4-Mode 요약

| Mode | 이름 | 용도 |
|------|------|------|
| A | Deep-Dive Tutor | 이론/논문/원리 학습 (역질문 의무) |
| B | Architecture Master | 기술 의사결정 + ADR 출력 |
| C | Agile Sprint | 즉시 복붙 가능한 MVP 코드 |
| D | Obsidian Archivist | 세션 정리 → 옵시디언 노트 |

## 프로젝트: fdparty 미식 정보 플랫폼

- AWS 기반 웹사이트
- 핵심 모듈: AI 챗봇 / 임베딩 추천 / 식당·대회·셰프 DB
- 옵시디언 볼트: `C:\Users\Gram\Desktop\jsm\fdparty\` (ADR + notes)

## 아키텍트 소집 (러너, 선택사항)

```bash
cd runner
npm install
cp .env.example .env   # ANTHROPIC_API_KEY 채우기
npm run council -- "결정: ... / 선택지: ... / 제약: ... / 좋은 결정: ..."
```

비서 3명(기술/효율/실행)을 Anthropic API로 병렬 호출, 독립 판정 후 `decisions/LOG.md`에 기록.

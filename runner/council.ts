import { readFileSync, writeFileSync } from "node:fs";
import type Anthropic from "@anthropic-ai/sdk";
import {
  loadAgents,
  PROTOCOL_PATH,
  LOG_PATH,
  type CouncilAgent,
} from "./agents.ts";
import { loadDotEnv } from "./lib/env.ts";
import { ask, createClient } from "./lib/anthropic.ts";

/** CLI 인자에서 결정 인테이크 텍스트를 얻는다: --file <path> 또는 따옴표 문자열. */
function readDecision(): string {
  const args = process.argv.slice(2);
  const fi = args.indexOf("--file");
  if (fi !== -1 && args[fi + 1]) return readFileSync(args[fi + 1], "utf8").trim();
  const positional = args.filter((a) => !a.startsWith("--")).join(" ").trim();
  if (positional) return positional;
  console.error(
    '결정을 입력하세요.\n  예) npm run council -- "결정: ... / 선택지: ... / 제약: ... / 좋은 결정: ..."\n  또는) npm run council -- --file ../council/decision-template.md\n  인사 모드) npm run council -- --greet',
  );
  process.exit(1);
}

function buildDecisionPrompt(protocol: string, decision: string): string {
  return [
    "## 위원회 프로토콜 (참고)\n",
    protocol,
    "\n---\n## 회부된 결정\n",
    decision,
    "\n---\n위 프로토콜 §3 출력 계약(핵심 진단 / 가장 치명적인 지점·레버리지 / 구체적 권고 / 판정)을 정확히 지켜 한국어로 답하라. 다른 비서를 흉내내지 말고 너의 페르소나에만 충실하라. 군더더기 금지.",
  ].join("");
}

/** 비서 답에서 판정(GO/GO-IF/NO-GO) 한 줄을 추출. 못 찾으면 "?". */
function extractVerdict(text: string): string {
  const m = text.match(/판정[:：]?\s*(NO-GO|GO-IF[^\n]*|GO)/i);
  return m ? m[1].replace(/\|/g, "/").trim() : "?";
}

function appendToLog(decision: string, sections: { agent: CouncilAgent; text: string }[]): void {
  const date = new Date().toISOString().slice(0, 10);
  const firstLine = decision.split("\n").find((l) => l.trim())?.trim() ?? "(무제)";
  const verdictTable = sections
    .map((s) => `| ${s.agent.name} | ${extractVerdict(s.text)} |`)
    .join("\n");

  const block = [
    `\n## ${date} — ${firstLine}`,
    "",
    "**회부 내용:**",
    "```",
    decision,
    "```",
    "",
    "**판정 요약:**",
    "",
    "| 비서 | 판정 |",
    "|------|------|",
    verdictTable,
    "",
    ...sections.map((s) => `${s.text}\n`),
    "> 결정관(Synthesizer) 비활성 — 최종 통합은 사용자 판단.\n",
  ].join("\n");

  const log = readFileSync(LOG_PATH, "utf8");
  const marker = "<!-- 새 결정은 이 줄 바로 아래에 추가됨 (최신이 위) -->";
  const next = log.includes(marker)
    ? log.replace(marker, `${marker}\n${block}`)
    : `${log}\n${block}`;
  writeFileSync(LOG_PATH, next, "utf8");
}

/** 인사 모드: 각 비서가 동료들에게 자기 페르소나 톤으로 짧게 자기소개 + 한마디. */
async function runGreet(client: Anthropic, model: string, agents: CouncilAgent[]): Promise<void> {
  const roster = agents.map((a) => `- ${a.name} (${a.id})`).join("\n");
  console.error(`▶ 위원회 상견례: 비서 ${agents.length}명\n`);
  const intros = await Promise.all(
    agents.map(async (a) => {
      const user = [
        "너는 의사결정 위원회의 한 자리다. 오늘 위원회가 처음 소집됐다. 동료 명단:\n",
        roster,
        "\n\n너의 페르소나 톤 그대로, 동료들에게 **3~5문장**으로 자기소개하라. 마지막 한 문장은 동료 중 한 명을 콕 집어 한마디 건네라(견제든 협력이든 너답게). 군더더기·자기 역할 나열식 설명 금지, 캐릭터로 말하라.",
      ].join("");
      return { agent: a, text: await ask(client, model, a.body, user) };
    }),
  );
  for (const i of intros) {
    console.log(`\n${"─".repeat(60)}\n## ${i.agent.name}\n${i.text}`);
  }
  console.log(`\n${"─".repeat(60)}`);
}

async function main(): Promise<void> {
  loadDotEnv();
  const { client, model } = createClient();
  const agents = loadAgents();

  if (process.argv.slice(2).includes("--greet")) {
    await runGreet(client, model, agents);
    return;
  }

  const decision = readDecision();
  const protocol = readFileSync(PROTOCOL_PATH, "utf8");
  const userPrompt = buildDecisionPrompt(protocol, decision);
  console.error(`▶ 위원회 소집: 비서 ${agents.length}명 병렬 호출 (${agents.map((a) => a.name).join(", ")})\n`);

  // 비서들은 서로의 답을 보지 않고 병렬 독립 검토 (집단사고 차단).
  const sections = await Promise.all(
    agents.map(async (a) => ({ agent: a, text: await ask(client, model, a.body, userPrompt) })),
  );

  for (const s of sections) {
    console.log(`\n${"=".repeat(60)}`);
    console.log(s.text);
  }
  console.log(`\n${"=".repeat(60)}`);

  appendToLog(decision, sections);
  console.error(`\n✔ decisions/LOG.md 에 기록 완료.`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

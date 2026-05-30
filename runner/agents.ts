import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = join(HERE, "..");
export const AGENTS_DIR = join(REPO_ROOT, "council", "agents", "아키텍트");
export const PROTOCOL_PATH = join(REPO_ROOT, "council", "protocol.md");
export const LOG_PATH = join(REPO_ROOT, "decisions", "LOG.md");

export interface CouncilAgent {
  id: string;
  name: string;
  order: number;
  body: string;
}

export function parse(raw: string): { meta: Record<string, string>; body: string } {
  const m = raw.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/);
  if (!m) return { meta: {}, body: raw };
  const meta: Record<string, string> = {};
  for (const line of m[1].split("\n")) {
    const i = line.indexOf(":");
    if (i === -1) continue;
    meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return { meta, body: m[2].trim() };
}

/**
 * council/agents/아키텍트/*.md 를 로드한다 (SSOT).
 * - `_` 로 시작하는 파일 제외
 * - frontmatter `enabled: false` 제외
 * - `order` 오름차순 정렬
 */
export function loadAgents(): CouncilAgent[] {
  const files = readdirSync(AGENTS_DIR).filter(
    (f) => f.endsWith(".md") && !f.startsWith("_"),
  );
  const agents: CouncilAgent[] = [];
  for (const f of files) {
    const { meta, body } = parse(readFileSync(join(AGENTS_DIR, f), "utf8"));
    if (meta.enabled === "false") continue;
    agents.push({
      id: meta.id ?? f.replace(/\.md$/, ""),
      name: meta.name ?? meta.id ?? f,
      order: Number(meta.order ?? 999),
      body,
    });
  }
  return agents.sort((a, b) => a.order - b.order);
}

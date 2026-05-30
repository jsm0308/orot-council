import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { REPO_ROOT } from "../agents.ts";

/**
 * 최소 .env 로더 (추가 의존성 없이). 이미 설정된 환경변수는 덮어쓰지 않음.
 * GitHub Actions에서는 .env가 없고 시크릿이 환경변수로 주입되므로 그대로 동작한다.
 */
export function loadDotEnv(): void {
  const p = join(REPO_ROOT, "runner", ".env");
  if (!existsSync(p)) return;
  for (const line of readFileSync(p, "utf8").split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const i = t.indexOf("=");
    if (i === -1) continue;
    const k = t.slice(0, i).trim();
    const v = t.slice(i + 1).trim().replace(/^["']|["']$/g, "");
    if (!(k in process.env)) process.env[k] = v;
  }
}

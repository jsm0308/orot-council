import Anthropic from "@anthropic-ai/sdk";

/** ANTHROPIC_API_KEY/모델을 읽어 클라이언트를 만든다. 키가 없으면 던진다. */
export function createClient(): { client: Anthropic; model: string } {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey || apiKey.includes("xxxx")) {
    throw new Error(
      "ANTHROPIC_API_KEY 미설정. runner/.env 또는 환경변수(GitHub Secrets)에 실제 키를 넣으세요.",
    );
  }
  const model = process.env.COUNCIL_MODEL || "claude-opus-4-8";
  return { client: new Anthropic({ apiKey }), model };
}

/** 클로드를 1회 호출해 텍스트를 받는다. system = 페르소나, user = 과업. */
export async function ask(
  client: Anthropic,
  model: string,
  system: string,
  user: string,
  maxTokens = 2048,
): Promise<string> {
  try {
    const msg = await client.messages.create({
      model,
      max_tokens: maxTokens,
      system,
      messages: [{ role: "user", content: user }],
    });
    return msg.content
      .filter((b): b is Extract<typeof b, { type: "text" }> => b.type === "text")
      .map((b) => b.text)
      .join("")
      .trim();
  } catch (err) {
    if (err instanceof Anthropic.APIError) {
      return `> ⚠️ 클로드 호출 실패 (status=${err.status}): ${err.message}. ANTHROPIC_API_KEY/모델/네트워크 확인.`;
    }
    throw err;
  }
}

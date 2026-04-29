import type { ChatResponse, HealthResponse } from "./types";

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const r = await fetch("/api/health", { signal });
  if (!r.ok) throw new Error(`/api/health → HTTP ${r.status}`);
  return r.json();
}

export async function postChat(
  prompt: string,
  sessionId: string | null,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, session_id: sessionId }),
    signal,
  });
  if (!r.ok) {
    let detail: string;
    try {
      const body = await r.json();
      detail =
        typeof body.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      detail = await r.text();
    }
    throw new Error(`HTTP ${r.status}: ${detail}`);
  }
  return r.json();
}

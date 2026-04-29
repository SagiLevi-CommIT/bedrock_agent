import { useEffect, useRef, useState } from "react";
import { ChatMessage } from "./components/ChatMessage";
import { MessageInput } from "./components/MessageInput";
import { getHealth, postChat } from "./api";
import type { HealthResponse, Message } from "./types";

const SUGGESTIONS = [
  "List the Glue databases.",
  "How many rows are in migrated_data.pc_results_part for date = DATE '2026-03-24'?",
  "Describe the columns of migrated_data.timeseries.",
  "What S3 buckets does the agent see?",
];

export function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const scroller = useRef<HTMLDivElement | null>(null);

  // Auto-scroll on new content
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  // Health probe at startup so the badge shows the live model + tool count.
  useEffect(() => {
    const ctrl = new AbortController();
    getHealth(ctrl.signal)
      .then(setHealth)
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setHealthError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, []);

  async function send(prompt: string) {
    setError(null);
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      text: prompt,
    };
    setMessages((m) => [...m, userMsg]);
    setLoading(true);
    try {
      const r = await postChat(prompt, sessionId);
      setSessionId(r.session_id);
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: r.text,
          tool_trace: r.tool_trace,
          usage: r.usage,
          iterations: r.iterations,
          latency_ms: r.latency_ms,
          request_id: r.request_id,
          stop_reason: r.stop_reason,
        },
      ]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function newSession() {
    if (loading) return;
    setMessages([]);
    setSessionId(null);
    setError(null);
  }

  return (
    <div className="flex h-full flex-col">
      <Header
        health={health}
        healthError={healthError}
        sessionId={sessionId}
        onNewSession={newSession}
        canReset={messages.length > 0 && !loading}
      />

      <main
        ref={scroller}
        className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-4 py-6"
      >
        {messages.length === 0 && !loading && (
          <Empty
            onPick={(text) => {
              void send(text);
            }}
          />
        )}

        <div className="space-y-3">
          {messages.map((m) => (
            <ChatMessage key={m.id} message={m} />
          ))}
          {loading && <ThinkingBubble />}
          {error && <ErrorBanner message={error} />}
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto w-full max-w-3xl px-4 py-3">
          <MessageInput onSend={(t) => void send(t)} disabled={loading} />
          <p className="mt-2 text-center text-[11px] text-slate-400">
            Read-only · staging data only · WAF IP allowlist
          </p>
        </div>
      </footer>
    </div>
  );
}

function Header({
  health,
  healthError,
  sessionId,
  onNewSession,
  canReset,
}: {
  health: HealthResponse | null;
  healthError: string | null;
  sessionId: string | null;
  onNewSession: () => void;
  canReset: boolean;
}) {
  return (
    <header className="border-b border-slate-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold text-slate-900">
            CardiacSense Data Agent
          </h1>
          <p className="truncate text-xs text-slate-500">
            {healthError ? (
              <span className="text-red-600">backend unreachable</span>
            ) : health ? (
              <>
                <span className="font-mono">{health.model}</span>
                <span> · </span>
                <span>{health.region}</span>
                <span> · </span>
                <span>{health.tools} tools</span>
              </>
            ) : (
              <>checking backend…</>
            )}
            {sessionId && (
              <>
                <span> · </span>
                <span className="font-mono text-slate-400">
                  session {sessionId.slice(0, 8)}…
                </span>
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={onNewSession}
          disabled={!canReset}
          className="shrink-0 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300"
          title="Clear chat and start a new session"
        >
          New chat
        </button>
      </div>
    </header>
  );
}

function Empty({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="mx-auto max-w-2xl py-10 text-center">
      <p className="text-slate-500">Ask anything about the staging data.</p>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-sm text-slate-700 shadow-sm transition hover:border-blue-300 hover:bg-blue-50"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function ThinkingBubble() {
  return (
    <div className="flex justify-start">
      <div className="rounded-2xl rounded-tl-sm bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200">
        <div className="flex items-center gap-1.5">
          <Dot delay={0} />
          <Dot delay={150} />
          <Dot delay={300} />
        </div>
      </div>
    </div>
  );
}

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="inline-block h-2 w-2 animate-bounce rounded-full bg-slate-400"
      style={{ animationDelay: `${delay}ms` }}
    />
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      <div className="font-semibold">Request failed</div>
      <div className="mt-0.5 break-all font-mono text-[12px]">{message}</div>
    </div>
  );
}

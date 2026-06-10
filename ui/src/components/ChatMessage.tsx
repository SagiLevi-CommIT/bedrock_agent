import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Action, Message } from "../types";
import { ToolTrace } from "./ToolTrace";

interface Props {
  message: Message;
}

/**
 * Custom renderers for model prose. The model must never emit download/viewer
 * URLs (those come from the deterministic action buttons), but if it does, this
 * makes a stray link harmless: http(s) links open in a NEW tab (never navigating
 * the SPA away and wiping chat history), and any other scheme (e.g. s3://, a
 * relative path) renders as plain inert text instead of a navigating anchor.
 */
const MARKDOWN_COMPONENTS: Components = {
  a({ href, children, ...props }) {
    const safe = typeof href === "string" && /^https?:\/\//i.test(href);
    if (!safe) {
      return <span {...props}>{children}</span>;
    }
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
        {children}
      </a>
    );
  },
};

/** Icon + emphasis per action type. Unknown types fall back to a plain link. */
const ACTION_STYLE: Record<string, { icon: string; primary: boolean }> = {
  download_standalone: { icon: "📈", primary: true },
  download_csv: { icon: "⬇️", primary: false },
  open_cardiolys_raw: { icon: "🧾", primary: false },
  open_report_pdf: { icon: "📄", primary: false },
  // Reserved for the future hosted viewer / tool web UI:
  open_visualization: { icon: "📈", primary: true },
  open_tool_ui: { icon: "🛠️", primary: false },
};

/**
 * Deterministic buttons built server-side from real tool results (viewer
 * links, presigned downloads, deep links). Rendered as new-tab links so the
 * chat session is never navigated away.
 */
function ActionButtons({ actions }: { actions?: Action[] }) {
  if (!actions || actions.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {actions.map((a, i) => {
        const style = ACTION_STYLE[a.type] ?? { icon: "🔗", primary: false };
        return (
          <a
            key={`${a.type}-${i}`}
            href={a.url}
            target="_blank"
            rel="noopener noreferrer"
            className={
              style.primary
                ? "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-blue-700"
                : "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
            }
          >
            <span aria-hidden>{style.icon}</span>
            {a.label}
          </a>
        );
      })}
    </div>
  );
}

export function ChatMessage({ message }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[78%] rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2.5 text-white shadow-sm">
          <p className="whitespace-pre-wrap text-[0.95rem] leading-snug">
            {message.text}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-white px-4 py-3 text-slate-900 shadow-sm ring-1 ring-slate-200">
        <div className="prose-tight">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
            {message.text || "_(empty response)_"}
          </ReactMarkdown>
        </div>
        <ActionButtons actions={message.actions} />
        <ToolTrace trace={message.tool_trace} />
        <Footer message={message} />
      </div>
    </div>
  );
}

function Footer({
  message,
}: {
  message: Extract<Message, { role: "assistant" }>;
}) {
  const cost =
    message.usage.input_tokens + message.usage.output_tokens > 0
      ? `${message.usage.input_tokens} in · ${message.usage.output_tokens} out`
      : null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
      <span>{message.latency_ms} ms</span>
      <span>·</span>
      <span>
        {message.iterations} iter{message.iterations === 1 ? "" : "s"}
      </span>
      {cost && (
        <>
          <span>·</span>
          <span>{cost}</span>
        </>
      )}
      <span>·</span>
      <span className="font-mono">{message.request_id}</span>
    </div>
  );
}

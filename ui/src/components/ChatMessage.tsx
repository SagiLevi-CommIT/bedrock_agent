import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message } from "../types";
import { ToolTrace } from "./ToolTrace";

interface Props {
  message: Message;
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
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.text || "_(empty response)_"}
          </ReactMarkdown>
        </div>
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

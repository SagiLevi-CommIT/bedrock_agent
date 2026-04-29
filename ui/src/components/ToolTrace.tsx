import { useState } from "react";
import type { ToolCall } from "../types";

interface Props {
  trace: ToolCall[];
}

export function ToolTrace({ trace }: Props) {
  const [open, setOpen] = useState(false);
  if (trace.length === 0) return null;

  const total = trace.reduce((acc, t) => acc + t.latency_ms, 0);

  return (
    <div className="mt-2 border-t border-slate-200/70 pt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-xs font-medium text-slate-500 hover:text-slate-700 transition-colors"
        aria-expanded={open}
      >
        <span
          className={`inline-block transition-transform ${open ? "rotate-90" : ""}`}
        >
          ▸
        </span>
        Tool trace · {trace.length} call{trace.length === 1 ? "" : "s"} · {total}{" "}
        ms
      </button>
      {open && (
        <ol className="mt-2 space-y-2 pl-4 border-l-2 border-slate-200">
          {trace.map((t, i) => (
            <li key={i} className="text-xs">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono font-semibold text-slate-700">
                  {t.name}
                </span>
                <span className="text-slate-400">{t.latency_ms} ms</span>
              </div>
              {Object.keys(t.args || {}).length > 0 && (
                <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-700">
                  {JSON.stringify(t.args, null, 2)}
                </pre>
              )}
              <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-100 max-h-64 overflow-auto">
                {t.result}
              </pre>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

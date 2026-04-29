import { useEffect, useRef, useState } from "react";

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
}

export function MessageInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!disabled) ref.current?.focus();
  }, [disabled]);

  // Auto-grow up to ~6 lines
  useEffect(() => {
    const ta = ref.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 168)}px`;
  }, [value]);

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
  }

  return (
    <form
      className="flex items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        rows={1}
        placeholder={
          disabled
            ? "Agent is thinking…"
            : "Ask about CardiacSense data — Glue tables, Athena queries, S3 prefixes…"
        }
        className="flex-1 resize-none rounded-xl border border-slate-300 bg-white px-3 py-2 text-[0.95rem] text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 disabled:bg-slate-100"
        disabled={disabled}
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="shrink-0 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        Send
      </button>
    </form>
  );
}

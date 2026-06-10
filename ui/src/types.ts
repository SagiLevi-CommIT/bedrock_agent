export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: string;
  latency_ms: number;
}

/**
 * Deterministic clickable action built server-side from REAL tool results
 * (presigned downloads: standalone viewer HTML, CSVs, raw Cardiolys JSON).
 * The LLM never fabricates these URLs — see app/src/tools/actions.py.
 * open_visualization / open_tool_ui are reserved for the future hosted
 * viewer and /tool-ui web app.
 */
export interface Action {
  type:
    | "download_standalone"
    | "download_csv"
    | "open_cardiolys_raw"
    | "open_report_pdf"
    | "open_visualization"
    | "open_tool_ui"
    | string;
  label: string;
  url: string;
}

export interface ChatResponse {
  session_id: string;
  request_id: string;
  text: string;
  tool_trace: ToolCall[];
  usage: { input_tokens: number; output_tokens: number };
  iterations: number;
  stop_reason: string;
  latency_ms: number;
  actions?: Action[];
}

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  text: string;
  tool_trace: ToolCall[];
  usage: { input_tokens: number; output_tokens: number };
  iterations: number;
  latency_ms: number;
  request_id: string;
  stop_reason: string;
  actions?: Action[];
}

export type Message = UserMessage | AssistantMessage;

export interface HealthResponse {
  status: string;
  region: string;
  model: string;
  tools: number;
}

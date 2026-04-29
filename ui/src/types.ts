export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: string;
  latency_ms: number;
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
}

export type Message = UserMessage | AssistantMessage;

export interface HealthResponse {
  status: string;
  region: string;
  model: string;
  tools: number;
}

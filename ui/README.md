# UI

Vite + React + TypeScript + Tailwind 4 SPA. Built once and baked into the
FastAPI container so it shares the same ALB target — no separate ECS service,
no CORS.

## Local dev

```bash
# in one terminal — run the backend
cd app && uvicorn src.main:app --reload --port 8000

# in another — run the UI dev server with /api proxied to :8000
cd ui && npm install && npm run dev
# → http://localhost:5173
```

## Production build

`npm run build` produces `ui/dist/`, which the multi-stage `app/Dockerfile`
copies into the runtime image at `/app/ui_dist`. FastAPI serves it via
`StaticFiles` mounted at `/`. The CodeBuild pipeline runs the Node build for
us; no local Docker required.

## What's there

- `App.tsx` — top-level chat container, session id, error/loading state.
- `components/ChatMessage.tsx` — bubbles, markdown rendering, footer with
  tokens / latency / request id.
- `components/ToolTrace.tsx` — collapsible debug section per assistant turn,
  showing tool name, args, result, and latency.
- `components/MessageInput.tsx` — auto-growing textarea with Enter-to-send,
  Shift+Enter for newline.
- `api.ts` — fetch wrappers for `/api/health` and `/api/chat`.

## What's deliberately out of scope

- No client-side persistence yet. Refreshing the page clears the chat (the
  backend keeps the DDB session for 7 days, but the UI doesn't surface a
  "load past session" picker).
- No streaming. Backend `/api/chat` is request/response only. Streaming would
  require either SSE or Bedrock `ConverseStream` with chunked transfer.
- No auth — same posture as the rest of the staging stack (WAF IP allowlist
  only).

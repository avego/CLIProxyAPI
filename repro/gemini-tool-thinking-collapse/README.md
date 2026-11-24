# Gemini 3.8 Tool Continuation 0-Thinking Collapse Reproduction & Proposals

This repository subfolder provides a complete, deterministic reproduction of the **Gemini 3.8 Flash reasoning collapse (0-thinking)** during tool-calling agentic loops in CLIProxyAPI, accompanied by official core debug logs, wire captures, and architectural proposals.

---

## 1. Executive Summary

When OpenAI-compatible agentic clients (such as Roo-Code, Cline, Cursor, or custom agents) execute tools against `gemini-3.8-flash-high` via the Antigravity upstream:
* The client sends `messages: [user, assistant (tool_calls), tool (result)]`.
* Standard OpenAI protocols do **not** append a subsequent `user` turn after a `tool` result.
* CLIProxyAPI translates this into a Google `request.contents` payload ending on a `functionResponse` turn.
* **On Upstream v8.1.2 (and previous official releases):** Google Cloud Code / Gemini 3.8 backend treats an ending `functionResponse` as a terminal data return without an explicit user prompt. The reasoning engine collapses into **0-thinking** (`thought: false`, 0 reasoning tokens).
* **With Tool Continuation User Turn:** When a trailing user turn is appended to `request.contents` after reasoning replay capture, Gemini 3.8 immediately activates chain-of-thought reasoning (**246+ characters of thoughts**).

---

## 2. Benchmark Comparison (100% Identical Payload)

Both tests were executed using [`benchmark_single_payload.py`](./benchmark_single_payload.py) targeting `gemini-3.8-flash-high` with `stream: true`.

| Metric | Upstream v8.1.2 (`85225381`) | Patched Core (`1440a230`) |
| :--- | :--- | :--- |
| **HTTP Status** | `200 OK` | `200 OK` |
| **Elapsed Time** | 2.50s | 3.53s |
| **Total SSE Chunks** | 25 | 28 |
| **Thought Chunks** | **0** | **1** |
| **Reasoning Length** | **0 chars (0-THINKING COLLAPSE)** | **246 chars (ACTIVE REASONING)** |
| **First Content Text** | `"Based on the \`config.json\` file..."` | `"Thinking Process:\n\n1.  **Analyze...**"` |
| **Wire Outbound Contents** | 3 turns (ends on `functionResponse`) | 4 turns (ends on user continuation) |
| **Google Upstream Response** | All chunks `thought: false` | Initial chunk `thought: true` |

---

## 3. Evidence Files

All raw logs and wire dumps are included in [`evidence/`](./evidence/):

### Upstream v8.1.2:
* [`evidence/upstream_v812/main.log`](./evidence/upstream_v812/main.log): Official core debug log.
* [`evidence/upstream_v812/v1-chat-completions-2026-11-24T080217-fee620cb.log`](./evidence/upstream_v812/v1-chat-completions-2026-11-24T080217-fee620cb.log): Official request log recording SSE chunks with `reasoning_content: null`.
* [`evidence/upstream_v812/upstream_v812_identical_test.json`](./evidence/upstream_v812/upstream_v812_identical_test.json): Wire request and response dump.

### Patched Core:
* [`evidence/stable_core/main.log`](./evidence/stable_core/main.log): Official core debug log.
* [`evidence/stable_core/v1-chat-completions-2026-11-24T080310-0ab0f423.log`](./evidence/stable_core/v1-chat-completions-2026-11-24T080310-0ab0f423.log): Official request log recording full `reasoning_content`.
* [`evidence/stable_core/stable_core_identical_test.json`](./evidence/stable_core/stable_core_identical_test.json): Wire request and response dump.

---

## 4. Architectural Proposals

### Proposal 1 (Recommended): Add `UpstreamPayloadInterceptor` to Plugin SDK

Hardcoding synthetic user text (e.g. static prompt strings) directly into the core engine has several drawbacks:
1. It introduces a static fingerprint in upstream Google telemetry.
2. Different models or provider endpoints may require different continuation semantics (e.g., empty turn `{"text": ""}` vs custom directive).

Instead, adding an **Upstream Payload Hook** in `sdk/pluginapi` gives full flexibility to external plugins without touching core business logic:

```go
// sdk/pluginapi/types.go

type UpstreamPayloadInterceptor interface {
    InterceptUpstreamPayload(ctx context.Context, req UpstreamPayloadRequest) (UpstreamPayloadResponse, error)
}

type UpstreamPayloadRequest struct {
    Provider string
    Model    string
    Doc      *ojson.Doc
    Stream   bool
    Metadata map[string]any
}
```

In `AntigravityExecutor` (and others), right before dispatching the HTTP request:
```go
if hook := e.pluginHost.UpstreamPayloadInterceptor(); hook != nil {
    // Allows plugins to normalize, append continuation turns, or inspect outbound wire payloads
}
```

### Proposal 2: Native Normalization via Config Toggle

Alternatively, or in addition, provide an optional configuration switch in `config.yaml`:
```yaml
antigravity:
  tool-continuation:
    enabled: true
    prompt: "" # empty string uses native emptyGeminiUserTurnJSON, or custom text
```
This allows users to enable continuation turns safely while retaining full control over prompt signatures.


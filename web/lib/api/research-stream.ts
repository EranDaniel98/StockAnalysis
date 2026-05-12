/**
 * EventSource wrapper for /api/research/ask/stream.
 *
 * EventSource is GET-only, so we POST via fetch + read the response as an
 * SSE stream manually. Each "event:" + "data:" pair becomes one
 * `ResearchEvent` object dispatched to the consumer.
 */

import { API_BASE } from "./client";

export type ResearchEvent =
  | { event: "started"; run_id: number; question: string }
  | { event: "turn_start"; turn: number }
  | { event: "assistant_text"; turn: number; text: string }
  | {
      event: "tool_call";
      turn: number;
      tool: string;
      input: Record<string, unknown>;
    }
  | {
      event: "tool_result";
      turn: number;
      tool: string;
      is_error: boolean;
      summary: string;
    }
  | {
      event: "usage";
      turn: number;
      input_tokens: number;
      output_tokens: number;
      cost_usd: number;
    }
  | { event: "final_answer"; text: string }
  | { event: "complete"; run_id: number; status: string }
  | { event: "error"; detail: string; kind?: string }
  | { event: "heartbeat" };

export interface ResearchStreamRequest {
  question: string;
  max_turns?: number;
  model?: string | null;
  notes?: string | null;
}

/**
 * Drives one research run over SSE. Returns an AbortController so the
 * caller can cancel. Each parsed event is handed to `onEvent`.
 */
export function streamResearch(
  body: ResearchStreamRequest,
  onEvent: (e: ResearchEvent) => void,
  onClose?: (reason: "complete" | "abort" | "error") => void,
): AbortController {
  const ctrl = new AbortController();

  (async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/research/ask/stream`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          question: body.question,
          max_turns: body.max_turns ?? 8,
          model: body.model ?? null,
          notes: body.notes ?? null,
        }),
        signal: ctrl.signal,
      });

      if (!resp.ok || !resp.body) {
        onEvent({
          event: "error",
          detail: `HTTP ${resp.status}`,
          kind: "http",
        });
        onClose?.("error");
        return;
      }

      const reader = resp.body
        .pipeThrough(new TextDecoderStream())
        .getReader();

      let buffer = "";
      let finalStatus: "complete" | "error" = "complete";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;

        // SSE messages are separated by blank lines.
        let split = buffer.indexOf("\n\n");
        while (split !== -1) {
          const raw = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          const parsed = parseSseFrame(raw);
          if (parsed) {
            if (parsed.event === "error") finalStatus = "error";
            onEvent(parsed);
            if (parsed.event === "complete") finalStatus = "complete";
          }
          split = buffer.indexOf("\n\n");
        }
      }

      onClose?.(finalStatus);
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        onClose?.("abort");
      } else {
        onEvent({
          event: "error",
          detail: (err as Error).message ?? String(err),
          kind: "network",
        });
        onClose?.("error");
      }
    }
  })();

  return ctrl;
}

function parseSseFrame(raw: string): ResearchEvent | null {
  // Each frame is `event: <name>\ndata: <json>`. Spec says missing event
  // name defaults to "message"; the server names every frame so we trust it.
  let eventName = "message";
  let dataLine = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      // Multiple `data:` lines should concatenate with \n; SSE-Starlette
      // sends single-line payloads, so a simple slice is enough.
      dataLine += line.slice(5).trim();
    }
  }
  if (!dataLine) return null;
  try {
    const payload = JSON.parse(dataLine) as Record<string, unknown>;
    return { event: eventName, ...payload } as ResearchEvent;
  } catch {
    return null;
  }
}

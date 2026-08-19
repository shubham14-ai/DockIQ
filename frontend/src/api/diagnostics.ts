import { apiGet, apiPost } from "./client";
import type { DiagnosticAskResponse, DiagnosticStatus } from "./types";

// The ask endpoint runs a multi-step LLM tool-use loop against live metrics,
// logs, and topology data, so it can take significantly longer than a normal
// API call.
const ASK_TIMEOUT_MS = 90000;

export function getDiagnosticStatus(): Promise<DiagnosticStatus> {
  return apiGet<DiagnosticStatus>("/diagnostics/status");
}

export function askDiagnostic(question: string, context?: string): Promise<DiagnosticAskResponse> {
  return apiPost<DiagnosticAskResponse>(
    "/diagnostics/ask",
    context !== undefined ? { question, context } : { question },
    ASK_TIMEOUT_MS,
  );
}

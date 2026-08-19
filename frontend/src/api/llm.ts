import { apiGet } from "./client";
import type { LlmStatus, PromVectorResponse } from "./types";

export function getLlmStatus(): Promise<LlmStatus> {
  return apiGet<LlmStatus>("/llm/status");
}

export function getLlmCost(): Promise<PromVectorResponse> {
  return apiGet<PromVectorResponse>("/llm/cost");
}

export function getLlmLatency(): Promise<PromVectorResponse> {
  return apiGet<PromVectorResponse>("/llm/latency");
}

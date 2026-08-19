import { originGet } from "./client";

export interface HealthzResponse {
  status: string;
}

export interface ReadyzResponse {
  status: string;
  checks: Record<string, string>;
}

export function getHealthz(): Promise<HealthzResponse> {
  return originGet<HealthzResponse>("/healthz");
}

export function getReadyz(): Promise<ReadyzResponse> {
  return originGet<ReadyzResponse>("/readyz");
}

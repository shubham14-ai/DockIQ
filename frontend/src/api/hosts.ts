import { apiGet } from "./client";
import type { Host } from "./types";

export function listHosts(): Promise<Host[]> {
  return apiGet<Host[]>("/hosts");
}

export function getHost(id: string): Promise<Host> {
  return apiGet<Host>(`/hosts/${encodeURIComponent(id)}`);
}

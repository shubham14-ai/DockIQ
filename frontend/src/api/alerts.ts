import { apiGet, apiPost } from "./client";
import type { Alert, AlertFilters } from "./types";

export function listAlerts(filters?: AlertFilters): Promise<Alert[]> {
  return apiGet<Alert[]>("/alerts", filters);
}

export function ackAlert(id: string): Promise<Alert> {
  return apiPost<Alert>(`/alerts/${encodeURIComponent(id)}/ack`);
}

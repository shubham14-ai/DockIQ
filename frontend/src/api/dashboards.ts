import { apiGet, apiPost } from "./client";
import type { Dashboard, DashboardRegenerateResponse } from "./types";

export function listDashboards(): Promise<Dashboard[]> {
  return apiGet<Dashboard[]>("/dashboards");
}

export function regenerateDashboards(): Promise<DashboardRegenerateResponse> {
  return apiPost<DashboardRegenerateResponse>("/dashboards/regenerate");
}

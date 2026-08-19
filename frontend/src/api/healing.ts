import { apiGet, apiPut } from "./client";
import type { HealingAction, HealingMode, HealingPolicy } from "./types";

export function listHealingPolicies(): Promise<HealingPolicy[]> {
  return apiGet<HealingPolicy[]>("/healing-policies");
}

export function updateHealingPolicy(id: string, mode: HealingMode): Promise<HealingPolicy> {
  return apiPut<HealingPolicy>(`/healing-policies/${encodeURIComponent(id)}`, { mode });
}

export function listHealingActions(): Promise<HealingAction[]> {
  return apiGet<HealingAction[]>("/healing-actions");
}

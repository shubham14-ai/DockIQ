import { apiPost } from "./client";

// Cache-maintenance targets. Volumes are offered but must be opted into
// explicitly (pruning them can destroy data), so it is not in the default set.
export const CACHE_TARGETS = ["build-cache", "images", "containers", "networks", "volumes"] as const;
export type CacheTarget = (typeof CACHE_TARGETS)[number];

export const DEFAULT_CACHE_TARGETS: CacheTarget[] = ["build-cache", "images", "containers", "networks"];

export interface CacheTargetResult {
  count?: number;
  removed?: number;
  reclaimable_bytes?: number;
  reclaimed_bytes?: number;
}

export interface CacheResult {
  ok: boolean;
  host_id: string;
  dry_run: boolean;
  reclaimable_bytes?: number | null;
  reclaimed_bytes?: number | null;
  targets?: Record<string, CacheTargetResult> | null;
  error?: string | null;
  action_id?: number | null;
}

// Step 1: report what could be freed. Removes nothing.
export function scanCache(hostId: string, targets?: CacheTarget[]): Promise<CacheResult> {
  return apiPost<CacheResult>(`/hosts/${encodeURIComponent(hostId)}/cache/scan`, { targets });
}

// Step 2: actually reclaim. The backend refuses this unless `approve` is true —
// that flag is the human-in-the-loop approval the panel collects.
export function pruneCache(
  hostId: string,
  opts: { targets?: CacheTarget[]; dangling_only?: boolean; approve: boolean },
): Promise<CacheResult> {
  // Prune can take a while on a full host; give it a longer client timeout.
  return apiPost<CacheResult>(`/hosts/${encodeURIComponent(hostId)}/cache/prune`, opts, 130000);
}

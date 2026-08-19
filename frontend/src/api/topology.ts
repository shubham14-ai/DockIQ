import { apiGet } from "./client";
import type { Topology, TopologyFilters } from "./types";

export function getTopology(filters?: TopologyFilters): Promise<Topology> {
  return apiGet<Topology>("/topology", filters);
}

import { apiGet } from "./client";
import type { Container, ContainerFilters } from "./types";

export function listContainers(filters?: ContainerFilters): Promise<Container[]> {
  return apiGet<Container[]>("/containers", filters);
}

export function getContainer(id: string): Promise<Container> {
  return apiGet<Container>(`/containers/${encodeURIComponent(id)}`);
}

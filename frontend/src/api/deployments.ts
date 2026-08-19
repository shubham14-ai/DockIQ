import { apiGet, apiPost } from "./client";
import type { Deployment, DeploymentCreateRequest, Release } from "./types";

export function listDeployments(): Promise<Deployment[]> {
  return apiGet<Deployment[]>("/deployments");
}

export function createDeployment(req: DeploymentCreateRequest): Promise<Deployment> {
  return apiPost<Deployment>("/deployments", req);
}

export function rollbackDeployment(id: string): Promise<Deployment> {
  return apiPost<Deployment>(`/deployments/${encodeURIComponent(id)}/rollback`);
}

export function listReleases(service?: string): Promise<Release[]> {
  return apiGet<Release[]>("/releases", { service });
}

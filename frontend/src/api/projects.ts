import { apiGet } from "./client";
import type { ProjectDetail, ProjectSummary } from "./types";

export function listProjects(filters?: { host_id?: string }): Promise<ProjectSummary[]> {
  return apiGet<ProjectSummary[]>("/projects", filters);
}

export function getProject(project: string, filters?: { host_id?: string }): Promise<ProjectDetail> {
  return apiGet<ProjectDetail>(`/projects/${encodeURIComponent(project)}`, filters);
}

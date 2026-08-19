// Types mirroring the DockIQ backend API (see docs/api-design.md and
// docs/layers/05-frontend.md). The backend currently returns bare JSON
// (list or object), not the documented {data, meta} envelope, so these
// client types model the flat shapes.

export type AgentStatus = "online" | "offline" | "degraded" | "unknown" | string;

export interface Host {
  id: string;
  tenant_id: string;
  name: string;
  agent_status: AgentStatus;
  last_heartbeat: string | null;
  agent_version: string | null;
  os: string | null;
  arch: string | null;
  docker_version: string | null;
}

export type ContainerRole =
  | "web"
  | "api"
  | "db"
  | "cache"
  | "queue"
  | "proxy"
  | "worker"
  | "unknown"
  | string;

export interface ContainerClassification {
  role: ContainerRole;
  tech: string;
  confidence: number;
}

export type ContainerState = "running" | "exited" | "paused" | "restarting" | "created" | string;

export interface Container {
  id: string;
  host_id: string;
  host_name?: string;
  name: string;
  image: string;
  image_ref?: string | null;
  state: ContainerState;
  compose_project?: string | null;
  compose_service?: string | null;
  role?: ContainerRole;
  tech?: string;
  classification?: ContainerClassification | null;
  created_at?: string | null;
}

export interface ContainerFilters {
  [key: string]: string | undefined;
  host_id?: string;
  role?: string;
  tech?: string;
  state?: string;
}

// --- Projects (compose-stack grouping) ---

export interface ProjectSummary {
  project: string;
  standalone: boolean;
  hosts: string[];
  service_count: number;
  container_count: number;
  state_counts: Record<string, number>;
  health: Record<string, number>;
  image_count: number;
  techs: string[];
  last_seen: string | null;
}

export interface ProjectService {
  service: string;
  container_count: number;
  state_counts: Record<string, number>;
  containers: Container[];
}

export interface ProjectImage {
  image_ref: string | null;
  image_digest: string | null;
  services: string[];
  container_count: number;
}

export interface ProjectConfig {
  config_files: string | null;
  working_dir: string | null;
  networks: string[];
}

export interface ProjectDetail extends ProjectSummary {
  services: ProjectService[];
  images: ProjectImage[];
  config: ProjectConfig;
}

// --- Prometheus / VictoriaMetrics query_range response ---

export interface PromMatrixResult {
  metric: Record<string, string>;
  values: [number, string][]; // [unix_seconds, value]
}

export interface PromQueryRangeResponse {
  status: "success" | "error";
  data?: {
    resultType: "matrix" | "vector" | "scalar" | "string";
    result: PromMatrixResult[];
  };
  error?: string;
}

// --- Loki query_range response (subset used for container logs) ---

export interface LokiStreamResult {
  stream: Record<string, string>;
  values: [string, string][]; // [unix_nanoseconds, line]
}

export interface LokiQueryRangeResponse {
  status: "success" | "error";
  data?: {
    resultType: "streams";
    result: LokiStreamResult[];
  };
}

export interface LogLine {
  timestampNs: string;
  line: string;
}

// --- Alerts ---

export type AlertSeverity = "critical" | "warning" | "info" | string;
export type AlertState = "firing" | "acked" | "resolved" | string;

export interface Alert {
  id: string;
  severity: AlertSeverity;
  target: string;
  summary: string;
  state: AlertState;
  started_at: string;
  ended_at?: string | null;
}

export interface AlertFilters {
  [key: string]: string | undefined;
  state?: string;
  severity?: string;
}

// --- Topology ---

export interface TopologyNode {
  id: string;
  service: string;
  role: ContainerRole;
  tech: string;
  host_id: string;
  state: ContainerState;
}

export type TopologyEdgeKind = "declared" | "inferred" | string;

export interface TopologyEdge {
  source: string;
  target: string;
  kind: TopologyEdgeKind;
  confidence: number;
  port?: number | null;
}

export interface Topology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

export interface TopologyFilters {
  [key: string]: string | undefined;
  host_id?: string;
}

// --- Diagnostics ("Ask DockIQ") ---

export interface DiagnosticStatus {
  enabled: boolean;
  model: string;
}

export interface DiagnosticStep {
  tool: string;
  input: Record<string, unknown>;
}

export interface DiagnosticAskResponse {
  answer: string | null;
  error: string | null;
  steps: DiagnosticStep[];
  model: string;
}

// --- Dashboards ---

export interface Dashboard {
  id: string;
  title: string;
  tech: string;
  tier: string;
  grafana_url: string;
  generated: boolean;
}

export interface DashboardRegenerateResponse {
  count: number;
}

// --- LLM Observability ---

export interface LlmStatus {
  enabled: boolean;
  price_table_models: string[];
}

export interface PromVectorSample {
  metric: Record<string, string>;
  value: [number, string]; // [unix_seconds, value]
}

export interface PromVectorResponse {
  status?: "success" | "error";
  data?: {
    resultType?: string;
    result: PromVectorSample[];
  };
}

// --- Self-Healing ---

export type HealingMode = "off" | "auto" | "semi" | string;

export interface HealingPolicy {
  id: string;
  name: string;
  mode: HealingMode;
  allowed_actions: string[];
  max_per_hour: number;
  enabled: boolean;
}

export interface HealingAction {
  id: string;
  trigger: string;
  action: string;
  target: string;
  outcome: string;
  detail?: string | null;
  host_id?: string | null;
  started_at: string;
}

// --- Deployments ---

export type DeploymentStatus = "promoted" | "rolledback" | "failed" | string;

export interface Deployment {
  id: string;
  service: string;
  from_version: string | null;
  to_version: string;
  status: DeploymentStatus;
  strategy: string;
  started_at: string;
}

export interface DeploymentCreateRequest {
  target: string;
  image: string;
  strategy?: string;
}

export interface Release {
  [key: string]: unknown;
  service?: string;
  version?: string;
  image?: string;
  created_at?: string;
}

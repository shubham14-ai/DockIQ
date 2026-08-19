import dagre from "dagre";
import { useCallback, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  ConnectionLineType,
  Controls,
  type Edge,
  Handle,
  type Node,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";
import { getTopology } from "../api/topology";
import { LoadingError } from "../components/LoadingError";
import { RoleTechBadge } from "../components/RoleTechBadge";
import { StatusBadge } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";
import type { TopologyEdge, TopologyNode } from "../api/types";

const POLL_MS = 10000;
const NODE_WIDTH = 180;
const NODE_HEIGHT = 56;

function layout(nodes: TopologyNode[], edges: TopologyEdge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 90 });

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const e of edges) {
    if (g.hasNode(e.source) && g.hasNode(e.target)) {
      g.setEdge(e.source, e.target);
    }
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      id: n.id,
      position: { x: (pos?.x ?? 0) - NODE_WIDTH / 2, y: (pos?.y ?? 0) - NODE_HEIGHT / 2 },
      data: { node: n },
      type: "service",
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    };
  });
}

function ServiceNode({ data, selected }: { data: { node: TopologyNode }; selected: boolean }) {
  const n = data.node;
  return (
    <div className={"topology-node" + (selected ? " topology-node-selected" : "")}>
      <Handle type="target" position={Position.Left} />
      <div className="topology-node-title">{n.service}</div>
      <div className="topology-node-badges">
        <RoleTechBadge role={n.role} tech={n.tech} />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const NODE_TYPES = { service: ServiceNode };

export function Topology() {
  const [hostFilter, setHostFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);

  const topology = usePolling(() => getTopology({ host_id: hostFilter || undefined }), POLL_MS, [hostFilter]);

  const nodes = topology.data?.nodes ?? [];
  const edges = topology.data?.edges ?? [];

  const flowNodes: Node[] = useMemo(() => layout(nodes, edges), [nodes, edges]);

  const flowEdges: Edge[] = useMemo(
    () =>
      edges
        .filter((e) => nodes.some((n) => n.id === e.source) && nodes.some((n) => n.id === e.target))
        .map((e, i) => ({
          id: `${e.source}-${e.target}-${i}`,
          source: e.source,
          target: e.target,
          animated: e.kind === "declared",
          style: {
            stroke: "var(--accent)",
            strokeDasharray: e.kind === "inferred" ? "5 4" : undefined,
          },
          label: e.port ? String(e.port) : undefined,
          labelStyle: { fill: "var(--text-muted)", fontSize: 11 },
          labelBgStyle: { fill: "var(--bg-elevated)" },
        })),
    [edges, nodes],
  );

  const styledNodes: Node[] = useMemo(
    () =>
      flowNodes.map((n) => ({
        ...n,
        data: { ...n.data, selected: n.id === selectedId },
        selected: n.id === selectedId,
      })),
    [flowNodes, selectedId],
  );

  const selectedNode = nodes.find((n) => n.id === selectedId);
  const dependencies = selectedId ? edges.filter((e) => e.source === selectedId) : [];
  const dependents = selectedId ? edges.filter((e) => e.target === selectedId) : [];
  const nodeById = useMemo(() => {
    const map: Record<string, TopologyNode> = {};
    for (const n of nodes) map[n.id] = n;
    return map;
  }, [nodes]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedId((prev) => (prev === node.id ? undefined : node.id));
  }, []);

  return (
    <div className="page page-wide">
      <header className="page-header">
        <h1>Topology</h1>
      </header>

      <div className="filter-bar">
        <label>
          Host ID
          <input
            type="text"
            value={hostFilter}
            onChange={(e) => setHostFilter(e.target.value)}
            placeholder="filter by host_id"
          />
        </label>
      </div>

      <LoadingError
        loading={topology.loading && !topology.data}
        error={topology.error}
        empty={topology.data?.nodes.length === 0}
        emptyLabel="No topology data available"
      />

      {topology.data && topology.data.nodes.length > 0 && (
        <div className="topology-layout">
          <div className="topology-canvas">
            <ReactFlow
              nodes={styledNodes}
              edges={flowEdges}
              nodeTypes={NODE_TYPES}
              onNodeClick={onNodeClick}
              connectionLineType={ConnectionLineType.SmoothStep}
              fitView
              proOptions={{ hideAttribution: true }}
            >
              <Background color="var(--border)" gap={20} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>

          <aside className="topology-panel">
            {!selectedNode && <div className="state">Select a node to inspect its dependencies.</div>}
            {selectedNode && (
              <>
                <h2 className="topology-panel-title">{selectedNode.service}</h2>
                <div className="detail-item">
                  <div className="detail-label">Classification</div>
                  <RoleTechBadge role={selectedNode.role} tech={selectedNode.tech} />
                </div>
                <div className="detail-item">
                  <div className="detail-label">Host</div>
                  <div className="mono">{selectedNode.host_id}</div>
                </div>
                <div className="detail-item">
                  <div className="detail-label">State</div>
                  <StatusBadge status={selectedNode.state} />
                </div>

                <h2>Dependencies ({dependencies.length})</h2>
                {dependencies.length === 0 && <div className="state">None</div>}
                <ul className="topology-list">
                  {dependencies.map((e, i) => (
                    <li key={i}>
                      <span className={"badge " + (e.kind === "declared" ? "badge-ok" : "badge-muted")}>
                        {e.kind}
                      </span>{" "}
                      {nodeById[e.target]?.service ?? e.target}
                      {e.port ? <span className="mono"> :{e.port}</span> : null}
                    </li>
                  ))}
                </ul>

                <h2>Dependents ({dependents.length})</h2>
                {dependents.length === 0 && <div className="state">None</div>}
                <ul className="topology-list">
                  {dependents.map((e, i) => (
                    <li key={i}>
                      <span className={"badge " + (e.kind === "declared" ? "badge-ok" : "badge-muted")}>
                        {e.kind}
                      </span>{" "}
                      {nodeById[e.source]?.service ?? e.source}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

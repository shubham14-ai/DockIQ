import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Login } from "./pages/Login";
import { Layout } from "./components/Layout";
import { Alerts } from "./pages/Alerts";
import { ContainerDetail } from "./pages/ContainerDetail";
import { Containers } from "./pages/Containers";
import { HostDetail } from "./pages/HostDetail";
import { Hosts } from "./pages/Hosts";
import { Overview } from "./pages/Overview";
import { ProjectDetail } from "./pages/ProjectDetail";
import { Projects } from "./pages/Projects";

// Lazy-loaded: pulls in reactflow/dagre, which are sizeable, so keep them
// out of the main bundle.
const Topology = lazy(() => import("./pages/Topology").then((m) => ({ default: m.Topology })));
const Diagnostics = lazy(() => import("./pages/Diagnostics").then((m) => ({ default: m.Diagnostics })));
const Dashboards = lazy(() => import("./pages/Dashboards").then((m) => ({ default: m.Dashboards })));
const LlmObservability = lazy(() =>
  import("./pages/LlmObservability").then((m) => ({ default: m.LlmObservability })),
);
const SelfHealing = lazy(() => import("./pages/SelfHealing").then((m) => ({ default: m.SelfHealing })));
const Deployments = lazy(() => import("./pages/Deployments").then((m) => ({ default: m.Deployments })));

export function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="page state">Loading…</div>;
  }
  if (!user) {
    return <Login />;
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="hosts" element={<Hosts />} />
        <Route path="hosts/:hostId" element={<HostDetail />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:project" element={<ProjectDetail />} />
        <Route path="containers" element={<Containers />} />
        <Route path="containers/:containerId" element={<ContainerDetail />} />
        <Route path="alerts" element={<Alerts />} />
        <Route
          path="topology"
          element={
            <Suspense fallback={<div className="page state">Loading…</div>}>
              <Topology />
            </Suspense>
          }
        />
        <Route
          path="diagnostics"
          element={
            <Suspense fallback={<div className="page state">Loading…</div>}>
              <Diagnostics />
            </Suspense>
          }
        />
        <Route
          path="dashboards"
          element={
            <Suspense fallback={<div className="page state">Loading…</div>}>
              <Dashboards />
            </Suspense>
          }
        />
        <Route
          path="llm"
          element={
            <Suspense fallback={<div className="page state">Loading…</div>}>
              <LlmObservability />
            </Suspense>
          }
        />
        <Route
          path="healing"
          element={
            <Suspense fallback={<div className="page state">Loading…</div>}>
              <SelfHealing />
            </Suspense>
          }
        />
        <Route
          path="deployments"
          element={
            <Suspense fallback={<div className="page state">Loading…</div>}>
              <Deployments />
            </Suspense>
          }
        />
      </Route>
    </Routes>
  );
}

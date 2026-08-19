import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { roleAtLeast } from "../auth/roles";

const NAV_ITEMS = [
  { to: "/diagnostics", label: "✦ Ask DockIQ", flagship: true },
  { to: "/", label: "Overview", end: true },
  { to: "/hosts", label: "Hosts" },
  { to: "/projects", label: "Projects" },
  { to: "/containers", label: "Containers" },
  { to: "/topology", label: "Topology" },
  { to: "/alerts", label: "Alerts" },
  { to: "/dashboards", label: "Dashboards" },
  { to: "/llm", label: "LLM Observability" },
  // Operator-gated (backend returns 403 for viewers).
  { to: "/healing", label: "Self-Healing", minRole: "operator" },
  { to: "/deployments", label: "Deployments", minRole: "operator" },
];

export function Layout() {
  const { user, logout } = useAuth();
  const role = user?.role ?? "viewer";
  const items = NAV_ITEMS.filter((i) => !i.minRole || roleAtLeast(role, i.minRole));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">DockIQ</span>
        </div>
        <nav className="nav">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                "nav-link" + (item.flagship ? " nav-link-flagship" : "") + (isActive ? " nav-link-active" : "")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="user-box">
            <span className="user-name">{user?.username}</span>
            <span className="user-role">{role}</span>
          </div>
          <button className="btn-secondary logout-btn" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}

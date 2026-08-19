# DockIQ Frontend (Phase 1)

React + TypeScript + Vite web UI for DockIQ: fleet Overview, Hosts, Containers
(metrics + logs + classification), and Alerts. See
`../docs/layers/05-frontend.md` for the design and `../docs/api-design.md`
for the API conventions.

## Stack

- React 18 + TypeScript, bundled with Vite
- react-router-dom for client-side routing
- recharts for the CPU/memory sparkline charts
- Plain CSS (dark-first, `prefers-color-scheme`-aware), no UI kit
- No WebSocket in Phase 1 — lists and detail views poll on `setInterval`

## Requirements

- Node.js 20+
- The DockIQ backend reachable at `http://localhost:8080` (health at
  `/healthz`/`/readyz`, API at `/api/v1`)

## Run locally (dev)

```bash
cd frontend
npm install
npm run dev
```

Opens on `http://localhost:5173`. The Vite dev server proxies `/api`,
`/healthz`, and `/readyz` to `http://localhost:8080` (see `vite.config.ts`),
so no `.env` is needed for local development against a backend running on
its default port.

To point at a different API base, copy `.env.example` to `.env` and set
`VITE_API_BASE`.

## Build

```bash
npm run build
```

Type-checks (`tsc -b`) and produces a production bundle in `dist/`.

## Preview a production build

```bash
npm run preview
```

## Docker

The included `Dockerfile` is a multi-stage build: `node:20-alpine` builds the
static bundle, then `nginx:alpine` serves `dist/` and reverse-proxies
`/api`, `/healthz`, and `/readyz` to the `backend` service (see
`nginx.conf`). It expects to run alongside a Docker Compose service named
`backend` listening on port 8080.

```bash
docker build -t dockiq-frontend .
docker run -p 8080:80 dockiq-frontend
```

### docker-compose service

Add to `../docker-compose.yml`:

```yaml
  frontend:
    build:
      context: ./frontend
    ports:
      - "5173:80"
    depends_on:
      - backend
```

## Project structure

```
src/
  api/            typed fetch client + one module per resource (hosts,
                   containers, metrics, alerts, health)
  components/     shared UI (Layout/Nav, badges, tables, charts, loading/error)
  hooks/          usePolling — the setInterval-based polling hook
  pages/          one component per route (Overview, Hosts, HostDetail,
                   Containers, ContainerDetail, Alerts)
  App.tsx         react-router route table
  main.tsx        entry point
  index.css       theme + layout styles
```

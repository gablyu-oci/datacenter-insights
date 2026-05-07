# Frontend — Strategic Insights Tool

React 19 + Vite + TypeScript dashboard for the datacenter & power
competitive-intel tool. See the repo root [`README.md`](../README.md)
for product context, the data backend, and end-to-end setup
instructions.

## Local development

```bash
npm install
npm run dev          # Vite dev server on http://localhost:5173
npm run build        # tsc -b && vite build
npm run lint
npm run test         # Vitest run
```

The app expects the FastAPI backend on the same origin by default
(empty base URL). Override at build time with `VITE_API_BASE_URL`.

## Layout

- `src/App.tsx` — tab registry and shell.
- `src/components/tabs/` — one file per top-level tab (Power, Sites,
  GPU, NICs, TSMC, Permits, Triangulation, Companies, Sources,
  AI Insights).
- `src/components/agentchat/` — streaming chat primitives (used by
  `ChatPanel` for Q&A and the AI Insights chat dock).
- `src/components/shared/` — reusable error / empty / coverage / citation
  components.
- `src/hooks/` — `useApi` (REST), `useInsightStream` (SSE),
  `useLatestInsightSession`, `useQA` (chat SSE).
- `src/styles/insightTokens.ts` — design tokens for the AI Insights tab.

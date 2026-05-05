# Vitest + React Testing Library setup (Vite 8 / React 19 / TS 6)

Minimal recipe to add unit tests to `frontend/`. Target time: ~10 minutes.

## 1. devDependencies to add

Add to `frontend/package.json` `devDependencies` (then `npm install`):

```jsonc
"vitest": "^4.1.0",
"@vitest/coverage-v8": "^4.1.0",      // optional; only if you want `--coverage`
"@testing-library/react": "^16.3.1",   // v16 is the line that supports React 19
"@testing-library/jest-dom": "^6.6.3",
"@testing-library/user-event": "^14.5.2",
"@testing-library/dom": "^10.4.0",     // peer of @testing-library/react v16
"jsdom": "^25.0.1"
```

Notes:
- `@types/jsdom` is **not** needed — Vitest's `jsdom` environment wires globals; `@types/node ^24` is already installed.
- Vitest 4.1+ explicitly lists Vite 8 as a supported peer. Vitest 3.x targets Vite ^5 || ^6 and will not resolve cleanly against `vite ^8.0.9`.
- `@testing-library/react@16` supports React 19; earlier majors will not.

Add scripts:

```jsonc
"scripts": {
  "test": "vitest run",
  "test:watch": "vitest",
  "test:coverage": "vitest run --coverage"
}
```

## 2. Config: extend `vite.config.ts` (don't create a separate file)

Why: project is small, the React plugin and `server` config are reused for free, and a single `defineConfig` from `vitest/config` keeps types correct.

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ['datacenter.oci-incubations.com'],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
    css: false,
    restoreMocks: true,
  },
})
```

## 3. Setup file

Create `frontend/src/setupTests.ts`:

```ts
import '@testing-library/jest-dom/vitest'
```

(Use the `/vitest` subpath so matchers register against Vitest's `expect`.)

## 4. TypeScript: declare globals + jest-dom matchers

In `frontend/tsconfig.app.json`, append to the `types` array:

```jsonc
"types": ["vite/client", "google.maps", "vitest/globals", "@testing-library/jest-dom"]
```

`setupTests.ts` is already covered by `include: ["src"]`.

## 5. Gotchas

- **React 19 + RTL**: must be `@testing-library/react ^16`.
- **Vite 8 peer**: only Vitest **4.1+** declares Vite 8 in its peerDependencies range.
- **`jest-dom` import path**: use `@testing-library/jest-dom/vitest`, not the bare path.
- **`globals: true` + TS**: without `vitest/globals` in `types`, you'll get red squiggles even though tests run.
- **`verbatimModuleSyntax: true`** is set: use `import type` for type-only RTL imports.
- **Recharts / Leaflet**: stub `ResizeObserver` and `matchMedia` in `setupTests.ts` only when you test those components.
- **EventSource**: not provided by jsdom. Stub via `vi.stubGlobal('EventSource', class { ... })` in tests that mount components which open SSE streams.

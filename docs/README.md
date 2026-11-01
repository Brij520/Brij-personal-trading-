# Documentation

| Document | What it answers |
|---|---|
| [architecture.md](architecture.md) | How the layers fit together, why the arithmetic is isolated, and the exact sequence of a research run. |
| [agents.md](agents.md) | The fourteen agents: inputs, outputs, scoring, and what each one refuses to do. |
| [risk-management.md](risk-management.md) | Position sizing, heat, exposure, the veto rule, and the limits nobody can override. |
| [data-sources.md](data-sources.md) | Providers, provenance, freshness, the synthetic engine, and how data quality caps confidence. |
| [backtesting.md](backtesting.md) | The event-driven engine, the Indian cost model, walk-forward, and why results are not promises. |
| [api.md](api.md) | Every endpoint, its contract, and the errors it can return. |
| [frontend.md](frontend.md) | The terminal: structure, page modules, charting, and the no-build constraint. |
| [development.md](development.md) | Setup, tests, style, extending the platform, and the release checklist. |

Project-level files:

- [`../README.md`](../README.md) — what this is, honest capability table, quick start.
- [`../DEVELOPMENT_STATUS.md`](../DEVELOPMENT_STATUS.md) — what works, what does not, and why.
- [`../CHANGELOG.md`](../CHANGELOG.md) — release history.
- [`../skills/`](../skills/README.md) — Brij's own operator runbooks (how to *use* the tool).
- [`../examples/`](../examples/README.md) — runnable scripts against the API.
- [`../integrations/`](../integrations/README.md) — broker/data adapters, read-only by design.

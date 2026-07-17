# Test suggestions

Machine-readable robot test plans derived from monorepo release deltas
(`chore_release-*` cherry-picks). These files are the source of truth for the
public GitHub Pages site.

## Add a suggestion

1. Copy an existing YAML file in this directory.
2. Use a unique `id` (filename should match: `<id>.yaml`).
3. Fill `release`, `hardware_required`, `harness`, and `tests`.
4. Set `status`:
   - `draft` — WIP, not featured
   - `suggested` — ready for operators to run
   - `validated` — run against a physical Flex and recorded
5. Locally preview: `make pages` then open `pages/index.html`.
6. Merge to `main`; CI publishes to GitHub Pages.

## Schema

See [SCHEMA.md](SCHEMA.md). Validated example:
`9.1.2-module-usb-reconnect.yaml`.

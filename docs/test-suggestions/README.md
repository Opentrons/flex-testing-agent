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

See [SCHEMA.md](SCHEMA.md). Validated examples:

- `9.1.2-module-usb-reconnect.yaml`
- `10.0.0-alpha.1-release-delta.yaml` (install-ready checklist for fixes merged
  into `chore_release-10.0.0` since `v10.0.0-alpha.0`; parent epic RQA-5847)
- `10.0.0-alpha.0-pyro-subprocess.yaml` (Pyro / protocol-subprocess baseline;
  narrative in [../pyro-testing.md](../pyro-testing.md); sample protocols under
  `protocols/`)
- `4.0.0-alpha.10-pyro-subprocess.yaml` (historical internal-line results)
- `crs-auth-settings-behavior.yaml` (CRS auth settings per-field + combination
  matrix; maps [QA Test Checklist §8](https://opentrons.atlassian.net/wiki/spaces/~712020ac583a1878a5430aaf1db6793f399ca1/pages/6195970453))

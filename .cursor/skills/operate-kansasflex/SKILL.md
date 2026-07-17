---
name: operate-kansasflex
description: >-
  Operates the local Opentrons Flex KansasFLEX through flex-testing-agent CLI
  and Python APIs. Use when inspecting robot state, probing read-only endpoints,
  taking camera pictures, listing Flex OS releases, or installing a robot OS
  build with ALLOW_MUTATIONS.
---

# Operate KansasFLEX

## Prerequisites

- `.env` with `ROBOT_HOST` (and usually `ROBOT_NAME=KansasFLEX`)
- `uv sync --all-extras`
- Mutations only when `.env` has `ALLOW_MUTATIONS=true`

## Preferred commands

```bash
# Read-only snapshot
uv run flex-test inspect

# Full read-only endpoint probe + optional camera JPEG
uv run flex-test probe
uv run flex-test probe --no-picture
uv run flex-test probe --picture ./artifacts/camera/kansasflex.jpg

# Published Flex robot OS versions (CDN manifests)
uv run flex-test releases

# Install OS build (mutates; needs ALLOW_MUTATIONS=true)
uv run flex-test put 9.1.2-alpha.0
```

## Python entrypoints

```python
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.robots.flex import FlexRobot
from flex_testing_agent.capabilities.probe import probe_robot
from flex_testing_agent.capabilities.inspect import inspect_robot
```

Use `FlexRobot` as async context manager. Prefer capabilities over raw clients for multi-step work.

## Safety reminders

- Never enable access control
- Do not run physical motion
- Default pytest excludes `requires_robot` / `mutates_robot`
- Live robot tests: `uv run pytest -m requires_robot`

## Artifacts

Evidence and photos land under `ARTIFACT_DIRECTORY` (default `./artifacts/`).

## Test suggestions (GitHub Pages)

Author YAML under `docs/test-suggestions/`. Preview with `make pages`. Pushing to `main` publishes https://opentrons.github.io/flex-testing-agent/.

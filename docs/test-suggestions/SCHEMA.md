# Test suggestion YAML schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Stable slug; matches filename |
| `title` | string | yes | Human title |
| `summary` | string | yes | One short paragraph |
| `status` | enum | yes | `draft` \| `suggested` \| `validated` |
| `updated` | date | yes | ISO date `YYYY-MM-DD` |
| `release.monorepo_branch` | string | yes | e.g. `chore_release-9.1.2` |
| `release.compared_to_tag` | string | no | Prior tag, e.g. `v9.1.1` |
| `release.robot_os` | string | no | Bare robot OS key tested |
| `release.prs` | list | no | `{number, title, url}` |
| `hardware_required` | list[string] | no | Module/pipette needs |
| `harness.commands` | list[string] | no | `flex-test` commands |
| `tests` | list | yes | Suite entries |
| `tests[].id` | string | yes | e.g. `B1` |
| `tests[].name` | string | yes | Short name |
| `tests[].why` | string | yes | Maps to monorepo fix |
| `tests[].steps` | list[string] | yes | Operator / harness steps |
| `tests[].result` | enum | no | `pass` \| `fail` \| `blocked` \| `skipped` |
| `tests[].notes` | string | no | Outcome notes |

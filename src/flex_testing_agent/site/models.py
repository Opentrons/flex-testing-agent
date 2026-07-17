"""Pydantic models for test-suggestion YAML catalogs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SuggestionStatus = Literal["draft", "suggested", "validated"]
TestResult = Literal["pass", "fail", "blocked", "skipped"]


class PullRequestRef(BaseModel):
    """Monorepo PR referenced by a suggestion."""

    number: int
    title: str
    url: str


class ReleaseContext(BaseModel):
    """Monorepo / robot OS context for a suggestion."""

    monorepo_branch: str
    compared_to_tag: str | None = None
    robot_os: str | None = None
    prs: list[PullRequestRef] = Field(default_factory=list)


class HarnessHints(BaseModel):
    """CLI commands operators can run."""

    commands: list[str] = Field(default_factory=list)


class SuggestionTest(BaseModel):
    """One test item inside a suggestion suite."""

    id: str
    name: str
    why: str
    steps: list[str]
    result: TestResult | None = None
    notes: str | None = None


class TestSuggestion(BaseModel):
    """One published test-suggestion document."""

    id: str
    title: str
    summary: str
    status: SuggestionStatus
    updated: str
    release: ReleaseContext
    hardware_required: list[str] = Field(default_factory=list)
    harness: HarnessHints = Field(default_factory=HarnessHints)
    tests: list[SuggestionTest]

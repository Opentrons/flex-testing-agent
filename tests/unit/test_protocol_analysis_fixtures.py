"""Unit tests for protocol analysis fixtures."""

from __future__ import annotations

from flex_testing_agent.fixtures.protocol_analysis import (
    analysis_request_data,
    duolink_reanalysis_runtime_parameter_values,
    duolink_upload_runtime_parameter_values,
)


def test_duolink_rtp_overrides_differ_from_upload_defaults() -> None:
    upload = duolink_upload_runtime_parameter_values()
    reanalysis = duolink_reanalysis_runtime_parameter_values()
    assert upload["num_sample"] != reanalysis["num_sample"]
    assert upload["dry_run"] != reanalysis["dry_run"]


def test_analysis_request_data_includes_rtps() -> None:
    body = analysis_request_data(
        run_time_parameter_values={"num_sample": 48},
        force_re_analyze=True,
    )
    assert body["runTimeParameterValues"]["num_sample"] == 48
    assert body["forceReAnalyze"] is True

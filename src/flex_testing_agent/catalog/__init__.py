"""Flex HTTP API catalog for CRS-off / CRS-on endpoint matrix testing."""

from flex_testing_agent.catalog.endpoints import (
    FLEX_HTTP_ENDPOINTS,
    ApiService,
    EndpointSpec,
    HttpMethod,
    endpoint_count_by_method,
    endpoints_for_crs_off_get_probe,
)

__all__ = [
    "FLEX_HTTP_ENDPOINTS",
    "ApiService",
    "EndpointSpec",
    "HttpMethod",
    "endpoint_count_by_method",
    "endpoints_for_crs_off_get_probe",
]

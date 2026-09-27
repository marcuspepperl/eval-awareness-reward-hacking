"""Inspect entry point: registers our extensions (see [project.entry-points.inspect_ai])."""

from inspect_ai.model import modelapi


@modelapi(name="deepinfra-raw")
def deepinfra_raw():
    """Register the deepinfra-raw provider (imported lazily so Inspect startup stays fast)."""
    from earh.inspect_provider import DeepInfraRawAPI

    return DeepInfraRawAPI

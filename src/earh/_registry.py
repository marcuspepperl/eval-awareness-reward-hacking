"""Inspect entry point: registers our extensions (see [project.entry-points.inspect_ai])."""

from inspect_ai.model import modelapi


@modelapi(name="deepinfra-raw")
def deepinfra_raw():
    from earh.inspect_provider import DeepInfraRawAPI

    return DeepInfraRawAPI

from typing import Literal

from pydantic import BaseModel, Field


ReasoningLevel = Literal["none", "low", "medium", "medium_high", "high"]


class ModelConfig(BaseModel):
    role: str
    hf: str
    binary: str | None = None
    model_path: str | None = None
    flash_attention: bool = False
    context: int = Field(default=8192, ge=1024)
    reasoning: ReasoningLevel = "medium"


class ModelsConfig(BaseModel):
    models: dict[str, ModelConfig]


class OrchestratorSettings(BaseModel):
    task_retry_limit: int = Field(default=2, ge=0)
    model_start_timeout: int = Field(default=120, ge=1)
    model_stop_timeout: int = Field(default=20, ge=1)


class ResourceSettings(BaseModel):
    minimum_free_ram_gb: float = Field(default=2.0, ge=0)
    minimum_free_vram_gb: float = Field(default=1.0, ge=0)


class PathSettings(BaseModel):
    runs: str = "runs"


class Settings(BaseModel):
    orchestrator: OrchestratorSettings
    resources: ResourceSettings
    paths: PathSettings

from pathlib import Path

import yaml

from local_agent_orchestrator.models.config import ModelsConfig, Settings


REQUIRED_MODEL_ENTRIES = frozenset(
    {
        "qwen_coder",
        "gpt_oss",
        "bonsai2",
        "devstral",
    }
)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML config: {path}")

    return data


def load_settings(path: str | Path = "config/settings.yaml") -> Settings:
    return Settings.model_validate(_load_yaml(Path(path)))


def load_models(path: str | Path = "config/models.yaml") -> ModelsConfig:
    models = ModelsConfig.model_validate(_load_yaml(Path(path)))
    missing = sorted(REQUIRED_MODEL_ENTRIES - models.models.keys())

    if missing:
        raise ValueError(
            "Model config is missing required entries: "
            + ", ".join(missing)
        )

    return models

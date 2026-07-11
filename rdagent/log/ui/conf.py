from pathlib import Path

from pydantic_settings import SettingsConfigDict

from rdagent.core.conf import ExtendedBaseSettings

# Project root: rdagent/log/ui/conf.py -> ui -> log -> rdagent -> <project root>
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class UIBasePropSetting(ExtendedBaseSettings):
    model_config = SettingsConfigDict(env_prefix="UI_", protected_namespaces=())

    default_log_folders: list[str] = ["./log"]

    baseline_result_path: str = "./baseline.csv"

    aide_path: str = "./aide"

    amlt_path: str = "/data/share_folder_local/amlt"

    static_path: str = str(_PROJECT_ROOT / "git_ignore_folder" / "static")

    trace_folder: str = "./git_ignore_folder/traces"

    enable_cache: bool = True


UI_SETTING = UIBasePropSetting()

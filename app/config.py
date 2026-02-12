from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "data/poe_builds.db"
    cache_dir: str = "data/cache"
    project_root: Path = Path(__file__).resolve().parent.parent

    @property
    def db_path(self) -> Path:
        return self.project_root / self.database_path

    @property
    def cache_path(self) -> Path:
        return self.project_root / self.cache_dir

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

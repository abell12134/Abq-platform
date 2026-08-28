from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = DATA_DIR
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    primary_llm_base_url: str = "http://118.195.177.58:8001/v1"
    primary_llm_api_key: str = ""
    primary_llm_model: str = "nemotron-3.5-lightning:30b-a3b-mlx-bf16"
    primary_llm_provider_id: str = "local-nemotron"
    primary_llm_label: str = "本地 Nemotron"

    local_llm_base_url: str = "http://118.195.177.58:8001/v1"
    local_llm_api_key: str = ""
    local_llm_model: str = "nemotron-3.5-lightning:30b-a3b-mlx-bf16"
    local_llm_provider_id: str = "local-nemotron"
    local_llm_label: str = "本地 Nemotron"

    llm_health_timeout_s: float = 3.0

    qlib_tar_path: Path = DATA_DIR / "qib" / "qlib_bin.tar.gz"
    qlib_root: Path = DATA_DIR / "qib" / "qlib_bin"

    ohlcv_backfill_enabled: bool = True
    ohlcv_backfill_baostock: bool = True

    embedding_enabled: bool = True
    embedding_base_url: str = "http://118.195.177.58:8001/v1"
    embedding_api_key: str = ""
    embedding_model: str = "qwen3-embedding:8b"
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 16
    embedding_timeout_s: float = 60.0

    reranker_enabled: bool = True
    reranker_model: str = "awenleven/Qwen3-Reranker-4B:Q4_K_M"
    reranker_timeout_s: float = 60.0

    memory_db_path: Path = DATA_DIR / "memory.db"
    knowledge_archive_enabled: bool = True
    knowledge_dedup_by_hash: bool = True

    # Knowledge graph (R3): SQLite graph.db, throttled sample sync
    graph_enabled: bool = True
    graph_db_path: Path = DATA_DIR / "graph" / "graph.db"
    graph_fetch_min_interval_s: float = 3.0
    graph_sync_cooldown_hours: float = 6.0
    graph_sentiment_limit: int = 5
    graph_sync_sample_symbols: str = "sh600519,sh601318,sz000858,sh600036,sz300750"
    graph_announcement_limit: int = 8
    graph_announcement_days: int = 90
    graph_rollup_llm_enabled: bool = True

    # Policy URL fetch (R3.2): whitelist hosts in data/policy_sources.yaml
    policy_sources_path: Path = DATA_DIR / "policy_sources.yaml"
    policy_fetch_min_interval_s: float = 2.0
    policy_fetch_timeout_s: float = 30.0
    policy_allowed_hosts_extra: str = ""
    policy_sync_max_per_run: int = 5

    graph_extract_triples_enabled: bool = True
    graph_jsonl_rotate_enabled: bool = True
    graph_scheduler_enabled: bool = True
    graph_scheduler_on_startup: bool = False

    # Context compaction: trigger when persisted steps exceed this token estimate (default 128k).
    context_compact_threshold_tokens: int = 128_000


settings = Settings()

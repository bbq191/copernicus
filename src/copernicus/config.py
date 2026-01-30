from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ASR model paths (ModelScope IDs)
    asr_model_dir: str = (
        "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    )
    vad_model_dir: str = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
    punc_model_dir: str = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
    asr_device: str = "auto"
    asr_batch_size: int = 300

    # LLM configuration
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model_name: str = "deepseek-chat"
    llm_temperature: float = 0.1
    llm_timeout: float = 600.0

    # Text correction chunking
    correction_chunk_size: int = 800
    correction_overlap: int = 100

    # Hotwords file (optional)
    hotwords_file: Path | None = None

    # Upload settings
    upload_dir: Path = Path("./uploads")
    max_upload_size_mb: int = 500

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def resolve_asr_device(self) -> str:
        if self.asr_device != "auto":
            return self.asr_device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"


settings = Settings()

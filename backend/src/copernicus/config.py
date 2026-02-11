from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ASR 模式: paraformer (说话人分离) | sensevoice (抗噪增强)
    asr_mode: str = "paraformer"

    # Paraformer 模型配置 (ModelScope IDs)
    # 使用 seaco_paraformer + 分离 VAD/PUNC 模型，支持时间戳和说话人分离
    asr_model_dir: str = (
        "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    )
    vad_model_dir: str = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
    punc_model_dir: str = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
    spk_model_dir: str = "iic/speech_campplus_sv_zh-cn_16k-common"

    # SenseVoice 模型配置 (仅 asr_mode=sensevoice 时生效)
    sensevoice_model_dir: str = "iic/SenseVoiceSmall"
    sensevoice_language: str = "zh"  # auto | zh | en | yue | ja | ko
    sensevoice_max_segment_ms: int = 15000  # 单段最大时长（毫秒），超过则后处理分割

    # 说话人分离滑动窗口配置 (基于声纹相似度聚类)
    spk_sliding_window_ms: int = 1500    # 声纹提取窗口大小（毫秒）
    spk_sliding_step_ms: int = 750       # 窗口滑动步长（毫秒）
    spk_sliding_threshold_ms: int = 3000 # 超过此时长启用滑动窗口（毫秒）
    spk_distance_threshold: float = 0.5  # 余弦距离阈值（0-1，越小越严格）

    # 噪声过滤
    filter_noise_segments: bool = True   # 是否过滤纯语气词段落

    # ASR 通用配置
    asr_device: str = "auto"
    asr_batch_size: int = 3000  # 16GB 显存推荐 3000-5000
    asr_dtype: str = "float16"  # float32 | float16 | bfloat16
    asr_disable_pbar: bool = True  # 关闭推理进度条

    # 音频增强 (ffmpeg loudnorm + 降噪)
    audio_enhance: bool = True

    # LLM configuration
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model_name: str = "deepseek-chat"
    llm_temperature: float = 0.1
    llm_timeout: float = 120.0  # 单次 LLM 请求超时，超时后使用原文作为 fallback
    llm_max_retries: int = 2  # LLM 调用失败重试次数（指数退避）
    llm_retry_delay: float = 2.0  # 首次重试延迟（秒），后续 2x 递增
    llm_max_concurrent: int = 3  # 全局 LLM 并发上限
    ollama_num_ctx: int = 32768
    ollama_num_ctx_correction: int = 4096

    # Text correction chunking
    correction_chunk_size: int = 800
    correction_overlap: int = 50
    correction_max_concurrency: int = 3

    # 热词后处理替换（阶段 2）
    hotword_replacer_enabled: bool = True

    # pycorrector 轻量级纠错（阶段 3）
    pycorrector_enabled: bool = True
    pycorrector_model: str = "macbert"  # macbert | kenlm

    # Confidence-based filtering
    confidence_threshold: float = 0.95
    confidence_run_merge_gap: int = 3

    # Segment pre-merge
    pre_merge_gap_ms: int = 1000

    # Evaluation (Map-Reduce)
    evaluation_max_text_chars: int = 50000  # 总上限，超过则截断
    evaluation_chunk_size: int = 6000       # Map 分段大小（字符），短于此直接评估
    evaluation_num_ctx: int = 8192          # 评估专用 num_ctx，控制显存占用

    # Compliance Audit (Map-Reduce)
    compliance_max_text_chars: int = 50000
    compliance_chunk_size: int = 4000
    compliance_num_ctx: int = 8192

    # Cognitive Audit (Phase 3)
    compliance_confidence_threshold: float = 0.7
    compliance_dedup_window_ms: int = 30000
    compliance_group_by_source: bool = True
    compliance_ocr_margin_ms: int = 5000

    # Hotwords file (optional)
    hotwords_file: Path | None = None

    # Task execution
    task_timeout_seconds: int = 3600  # 单任务超时（秒），防止 ASR/LLM 卡住
    task_max_in_memory: int = 500  # 内存中最大任务数，超出时淘汰最早的已完成任务

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Video processing
    video_extensions: str = ".mp4,.avi,.mov,.mkv,.flv,.wmv"

    # Keyframe extraction
    keyframe_strategy: str = "interval"  # "interval" | "scene"
    keyframe_interval_s: float = 2.0
    keyframe_scene_threshold: float = 0.3
    keyframe_max_count: int = 500
    keyframe_format: str = "jpg"
    keyframe_quality: int = 85

    # OCR (RapidOCR)
    ocr_enabled: bool = True
    ocr_confidence_threshold: float = 0.6
    ocr_min_text_length: int = 2

    # Face Detection (YOLO)
    face_detect_enabled: bool = True
    face_detect_model: str = "models/yolov8n-face.pt"
    face_detect_confidence: float = 0.5
    face_missing_threshold_ms: int = 10000

    # Upload settings
    upload_dir: Path = Path("./uploads")
    max_upload_size_mb: int = 500

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def resolve_asr_device(self) -> str:
        import logging
        _logger = logging.getLogger(__name__)

        if self.asr_device != "auto":
            return self.asr_device
        try:
            import torch

            if torch.cuda.is_available():
                _logger.info(
                    "CUDA available: %s (VRAM: %.1f GB)",
                    torch.cuda.get_device_name(0),
                    torch.cuda.get_device_properties(0).total_memory / 1024**3,
                )
                return "cuda"
            _logger.warning(
                "CUDA not available. Check: 1) torch+cu12x installed 2) NVIDIA driver"
            )
            return "cpu"
        except ImportError:
            _logger.warning("PyTorch not installed, falling back to CPU")
            return "cpu"


settings = Settings()

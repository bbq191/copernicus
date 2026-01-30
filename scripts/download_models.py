"""Pre-download FunASR models to local cache.

Run this script once before starting the service to avoid
downloading models on first request:

    python scripts/download_models.py
"""

from copernicus.config import settings


def main() -> None:
    from funasr import AutoModel

    device = settings.resolve_asr_device()
    print(f"Downloading FunASR models (device={device}) ...")

    AutoModel(
        model=settings.asr_model_dir,
        vad_model=settings.vad_model_dir,
        punc_model=settings.punc_model_dir,
        device=device,
    )

    print("All models downloaded successfully.")


if __name__ == "__main__":
    main()

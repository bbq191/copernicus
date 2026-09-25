"""预下载当前 ASR 模式所需的 ModelScope 模型到 models/funasr/。

首次启动时后端也会自动下载，但会阻塞第一个任务数分钟，且离线环境（HF_HUB_OFFLINE=1）
下会直接失败。部署时先执行一次：

    python scripts/download_models.py

只下载权重文件，不加载模型，不占用显存，可在没有 GPU 的机器上执行。
"""

import os
import sys

from copernicus.config import settings

# 必须在导入 modelscope 之前设置，与 copernicus.main 保持一致
os.environ.setdefault("MODELSCOPE_CACHE", str(settings.funasr_cache_dir.resolve()))


def main() -> int:
    from modelscope import snapshot_download

    model_ids = settings.required_asr_model_ids
    print(f"ASR 模式：{settings.asr_mode}；缓存目录：{os.environ['MODELSCOPE_CACHE']}")

    failed: list[str] = []
    for model_id in model_ids:
        print(f"  下载 {model_id} ...", flush=True)
        try:
            snapshot_download(model_id)
        except Exception as exc:  # 网络/磁盘错误：继续下载其余模型，最后统一报告
            print(f"  [失败] {model_id}: {exc}", file=sys.stderr)
            failed.append(model_id)

    if failed:
        print(f"\n{len(failed)}/{len(model_ids)} 个模型下载失败：{failed}", file=sys.stderr)
        return 1
    print(f"\n{len(model_ids)} 个模型已就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""启动脚本 - 修复 Windows 下 joblib 问题"""
import os

# 必须在任何其他导入之前设置
os.environ["LOKY_MAX_CPU_COUNT"] = str(os.cpu_count() or 8)
os.environ["OMP_NUM_THREADS"] = str(os.cpu_count() or 8)

import uvicorn

if __name__ == "__main__":
    uvicorn.run("copernicus.main:app", host="0.0.0.0", port=8000, reload=True)

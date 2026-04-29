# Copernicus 生产环境部署指南（Rocky Linux 10.1）

> 作者: afu
>
> 本文档面向在 Rocky Linux 10.1 服务器上首次部署 Copernicus 的运维人员，覆盖从裸机到服务上线的完整步骤。

**目标机器规格**

| 参数     | 值                                      |
| -------- | --------------------------------------- |
| 操作系统 | Rocky Linux 10.1                        |
| GPU      | NVIDIA GeForce RTX 2080 Ti（11GB VRAM） |
| CPU      | Intel Xeon Gold 5218 × 2（64 线程）     |
| 内存     | 251 GB                                  |
| 存储     | 752 GB                                  |

> Rocky Linux 10.1 默认使用 **DNF 5**。`config-manager` 插件已内置；若提示命令不存在，执行 `dnf install -y dnf5-command(config-manager)`。

---

## 一、准备工作

### 1.1 创建部署用户

所有服务以专用用户 `bht_admin` 运行，避免以 root 身份长期运行进程。

以 root 身份执行：

```
useradd -m -d /home/bht_admin -s /bin/bash bht_admin
passwd bht_admin
usermod -aG wheel bht_admin
```

创建部署目录并授权：

```
mkdir -p /opt/copernicus /data/copernicus/uploads
chown -R bht_admin:bht_admin /opt/copernicus /data/copernicus
```

后续所有安装和配置步骤均切换至 `bht_admin` 执行：

```
su - bht_admin
```

> 需要 root 权限的步骤（驱动安装、防火墙、systemd 服务注册）会在各节开头单独说明，其余步骤默认以 `bht_admin` 身份运行。

### 1.2 配置软件源

Rocky Linux 10.1 默认使用 `mirrors.rockylinux.org` 镜像列表，在无公网 DNS 的环境下会报 `Could not resolve host` 错误。需先修复 DNS，再将 repo 文件替换为国内镜像。

**步骤一：修复 DNS**

```
# 以 root 执行
cat > /etc/resolv.conf << 'EOF'
nameserver 114.114.114.114
nameserver 223.5.5.5
EOF
```

**步骤二：替换 repo 文件（中科大 USTC 镜像）**

```
# 以 root 执行
cp -r /etc/yum.repos.d/ /etc/yum.repos.d.bak/
rm /etc/yum.repos.d/rocky*.repo

cat > /etc/yum.repos.d/rocky10.repo << 'EOF'
[baseos]
name=Rocky Linux 10 - BaseOS
baseurl=https://mirrors.ustc.edu.cn/rocky/10/BaseOS/x86_64/os/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10
enabled=1

[appstream]
name=Rocky Linux 10 - AppStream
baseurl=https://mirrors.ustc.edu.cn/rocky/10/AppStream/x86_64/os/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10
enabled=1

[crb]
name=Rocky Linux 10 - CRB
baseurl=https://mirrors.ustc.edu.cn/rocky/10/CRB/x86_64/os/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10
enabled=0

[extras]
name=Rocky Linux 10 - Extras
baseurl=https://mirrors.ustc.edu.cn/rocky/10/extras/x86_64/os/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-Rocky-10
enabled=0
EOF
```

**步骤三：验证并更新**

```
dnf makecache
dnf update -y
dnf config-manager --set-enabled crb
```

### 1.3 安装基础编译依赖

```
# 以 root 执行
dnf groupinstall -y "Development Tools"
dnf install -y curl wget git bzip2 openssl-devel libffi-devel \
    zlib-devel readline-devel sqlite-devel xz-devel
```

### 1.4 开放防火墙端口

```
# 以 root 执行
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --permanent --add-port=3000/tcp
firewall-cmd --reload
```

若使用 Nginx 反代（推荐），只需开放 80 端口即可。

### 1.5 关闭 SELinux（可选，排查权限问题用）

生产环境建议按需配置 SELinux 策略，暂不需要时可临时关闭：

```
# 以 root 执行
setenforce 0
sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config
```

---

## 二、NVIDIA 驱动与 CUDA

### 2.1 安装 NVIDIA 驱动

```
# 以 root 执行
dnf install -y epel-release
dnf config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel10/x86_64/cuda-rhel10.repo
dnf install -y "kernel-devel-$(uname -r)" kernel-headers
dnf install -y nvidia-driver cuda-toolkit-13-0 nvidia-driver-cuda
```

> RHEL 10 的 CUDA repo 仅提供 CUDA 13.x，不含 12.x。`cuda-toolkit-13-0` 是当前 RHEL 10 可用的最低稳定版本。
>
> 若仓库尚未收录当前内核对应的 `kernel-devel`，改用 `dnf install -y kernel-devel kernel-headers` 安装最新可用版，然后 `reboot` 切换至匹配内核再安装驱动。

验证驱动：

```
nvidia-smi
```

预期输出（RTX 2080 Ti，11264MiB VRAM，CUDA 12.2）：

```
+---------------------------------------------------------------------------------------+
| NVIDIA-SMI 535.183.01             Driver Version: 535.183.01   CUDA Version: 12.2    |
|-----------------------------------------+----------------------+----------------------+
|   0  NVIDIA GeForce RTX 2080 Ti     Off | 00000000:AF:00.0 Off |                  N/A |
|                                         |      0MiB / 11264MiB |      0%      Default |
+---------------------------------------------------------------------------------------+
```

### 2.2 设置持久化模式（防止 GPU 在空闲时降频导致首次推理慢）

```
# 以 root 执行
nvidia-smi -pm 1
echo 'nvidia-smi -pm 1' >> /etc/rc.d/rc.local
chmod +x /etc/rc.d/rc.local
```

---

## 三、ffmpeg

```
# 以 root 执行
dnf install -y \
    https://download1.rpmfusion.org/free/el/rpmfusion-free-release-10.noarch.rpm \
    https://download1.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-10.noarch.rpm
dnf install -y ffmpeg ffmpeg-devel
```

> 若安装时报 GPG 错误，追加 `--nogpgcheck` 临时跳过，验证包来源后手动导入密钥。

验证：

```
ffmpeg -version
```

---

## 四、Python 环境（pyenv + Python 3.12）

### 4.1 安装 pyenv

以 `bht_admin` 身份执行：

```
curl https://pyenv.run | bash

echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init -)"' >> ~/.bashrc
source ~/.bashrc
```

### 4.2 安装 Python 3.12

Rocky Linux 10.1 预装 OpenSSL 3.x，直接编译：

```
pyenv install 3.12.9
pyenv global 3.12.9
source ~/.bashrc
python --version        # 应输出 Python 3.12.9
python -c "import ssl; print(ssl.OPENSSL_VERSION)"
```

### 4.3 创建项目虚拟环境

```
cd /opt/copernicus/backend
python -m venv .venv
source .venv/bin/activate
```

---

## 五、Ollama 与 LLM 模型

### 5.1 安装 Ollama

从 GitHub Releases 下载 `ollama-linux-amd64.tar.zst`，通过 scp 传至服务器后手动安装：

```
# 以 root 执行

# 解压到 /usr（tar 自动识别 zstd，Rocky Linux 10 自带 tar 1.34+）
tar -C /usr -xf /root/ollama-linux-amd64.tar.zst

# 创建系统用户
useradd -r -s /bin/false -m -d /usr/share/ollama ollama
usermod -aG video ollama

# 创建 systemd 服务
cat > /etc/systemd/system/ollama.service << 'EOF'
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/usr/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=default.target
EOF

systemctl daemon-reload
systemctl enable --now ollama
```

### 5.2 配置 Ollama 服务

默认 Ollama 仅监听 127.0.0.1，若后端与 Ollama 同机部署无需修改。如需跨机访问：

```
# 以 root 执行
systemctl edit ollama
```

在编辑器中添加：

```
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

启用并启动服务：

```
# 以 root 执行
systemctl daemon-reload
systemctl enable --now ollama
```

### 5.3 导入 LLM 模型

#### 方式 A：有公网访问（直接拉取）

以 `bht_admin` 身份执行：

```
ollama pull qwen3:latest
ollama list
# 应看到 qwen3:latest
```

#### 方式 B：离线导入（已打包上传至服务器）

根据打包方式不同，选择对应导入步骤。

**B-1：打包的是 Ollama 模型目录（推荐，完整保留量化格式和元数据）**

在有网络的机器上执行打包：

```
# 有网机器执行
ollama pull qwen3:latest
tar -czf qwen3_ollama.tar.gz -C ~/.ollama/models .
# 通过 scp 上传到服务器 /root/qwen3_ollama.tar.gz
```

在服务器上导入：

```
# 以 root 执行
systemctl stop ollama

mkdir -p /usr/share/ollama/.ollama/models
tar -xzf /root/qwen3_ollama.tar.gz -C /usr/share/ollama/.ollama/models
chown -R ollama:ollama /usr/share/ollama/.ollama

systemctl start ollama
```

以 `bht_admin` 验证：

```
ollama list
# 应看到 qwen3:latest
```

> Ollama 系统服务的模型目录默认为 `/usr/share/ollama/.ollama/models`（由 `OLLAMA_MODELS` 环境变量控制）。若 `ollama list` 为空，执行 `systemctl show ollama | grep OLLAMA_MODELS` 确认实际路径，将解压目标改为该路径。

**B-2：打包的是 GGUF 文件**

```
# 将 qwen3.gguf 上传到服务器，例如 /opt/models/qwen3.gguf

# 以 bht_admin 执行
cat > /tmp/Modelfile << 'EOF'
FROM /opt/models/qwen3.gguf
EOF

ollama create qwen3:latest -f /tmp/Modelfile
ollama list
# 应看到 qwen3:latest
```

> GGUF 导入方式不携带原始量化标签（tag 为自定义），功能上与 pull 的版本等价。

**显存预估**（qwen3:7B Q4_K_M）：

| 组件                         | 显存占用           |
| ---------------------------- | ------------------ |
| 模型权重（Q4_K_M）           | ~4.5 GB            |
| KV Cache（num_ctx=16384）    | ~2.0 GB            |
| ASR 模型（Paraformer Large） | ~1.5 GB            |
| 系统余量                     | ~3.0 GB            |
| 合计                         | ~11 GB（刚好满载） |

若推理过程中出现 OOM，调低 `OLLAMA_NUM_CTX` 至 8192。

---

## 六、后端部署

### 6.1 克隆代码

以 `bht_admin` 身份执行：

```
git clone <仓库地址> /opt/copernicus
```

### 6.2 安装 Python 依赖

```
cd /opt/copernicus/backend
source .venv/bin/activate

# 安装 CUDA 12.x 版 PyTorch（必须先装，不能用 CPU 默认版）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 安装项目依赖
pip install -e ".[all]"
```

验证 CUDA 可用：

```
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 应输出 True NVIDIA GeForce RTX 2080 Ti
```

### 6.3 应用 FunASR 源码补丁（必须执行）

本项目对 FunASR 安装包打了三处补丁，缺少这些补丁会导致置信度过滤完全失效（所有片段都会送 LLM 纠错，耗时从 3 分钟退化为 2 小时以上）。补丁通过项目内的脚本幂等应用：

```
cd /opt/copernicus/backend
source .venv/bin/activate
python scripts/patch_funasr.py
```

成功输出示例：

```
FunASR root: /opt/copernicus/backend/.venv/lib/python3.12/site-packages/funasr

Applying patches ...
  [patched] paraformer/model.py :: _token_confidence extraction
  [patched] paraformer/model.py :: result_i token_confidence injection
  [patched] seaco_paraformer/model.py :: hotword list cache
  [patched] seaco_paraformer/model.py :: _token_confidence extraction
  [patched] seaco_paraformer/model.py :: result_i token_confidence injection

Verifying patches ...
  [OK] model.py :: # Compute per-token confidence (am_scores is log_softmax, exp ...
  [OK] model.py :: # hotword (with cache to avoid repeated parsing across VAD seg...
  [OK] model.py :: result_i["token_confidence"] = _token_confidence

All patches applied successfully.
```

重复执行会输出 `[already applied]` 而非报错，安全幂等。

**补丁说明**（三处改动均在 FunASR 的 `site-packages` 内）：

| 文件                               | 补丁内容                                                                                  | 作用                                                                             |
| ---------------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `models/paraformer/model.py`       | greedy decode 分支新增 `_token_confidence` 提取；结果组装阶段注入 `token_confidence` 字段 | 使 Paraformer 输出逐 token 置信度，供上层跳过高置信度片段                        |
| `models/seaco_paraformer/model.py` | 同上两处改动                                                                              | 使 SeacoParaformer（项目实际使用的模型）同样输出置信度                           |
| `models/seaco_paraformer/model.py` | `inference` 方法添加 `_cached_hw_input` 缓存热词列表                                      | 热词解析从每个 VAD 片段都执行一次（44 分钟音频触发 105 次）降为仅变更时触发 1 次 |

**注意**：每次 `pip install --upgrade funasr` 后需重新执行此脚本，因为升级会覆盖已打补丁的文件。

### 6.4 导入 ASR 模型

#### 方式 A：有公网访问（自动下载）

```
source .venv/bin/activate
python - <<'EOF'
from modelscope import snapshot_download
snapshot_download('iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch')
snapshot_download('iic/speech_fsmn_vad_zh-cn-16k-common-pytorch')
snapshot_download('iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch')
snapshot_download('iic/speech_campplus_sv_zh-cn_16k-common')
EOF
```

#### 方式 B：离线导入（已从开发机打包上传）

ModelScope 缓存目录结构为 `~/.cache/modelscope/hub/iic/<model_name>/`。假设已将 `iic/` 目录上传至服务器 `~/iic`，执行：

```
mkdir -p ~/.cache/modelscope/hub
mv ~/iic ~/.cache/modelscope/hub/
```

验证目录结构：

```
ls ~/.cache/modelscope/hub/iic/
# 应看到以下四个目录：
# speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch
# speech_fsmn_vad_zh-cn-16k-common-pytorch
# punc_ct-transformer_zh-cn-common-vocab272727-pytorch
# speech_campplus_sv_zh-cn_16k-common
```

验证每个模型目录内有实际权重文件（非空）：

```
du -sh ~/.cache/modelscope/hub/iic/*/
# speech_seaco_paraformer 约 2.2 GB，其余各约 100-500 MB
```

> 若目录存在但文件不完整（下载中断），FunASR 启动时会尝试联网补全。确认服务器无公网访问后，需重新从开发机打包完整目录。

### 6.5 下载 YOLO 人脸检测模型

```
mkdir -p /opt/copernicus/backend/models
cd /opt/copernicus/backend/models

# 方法 A：有公网访问
python - <<'EOF'
from ultralytics import YOLO
YOLO('yolov8n-face.pt')
EOF

# 方法 B：手动下载后放入 models/ 目录
# 文件名：yolov8n-face.pt
```

### 6.6 配置 .env

```
cp /opt/copernicus/backend/.env.example /opt/copernicus/backend/.env
```

根据生产机器（RTX 2080 Ti 11GB）调整以下参数：

```
# LLM 服务
LLM_BASE_URL=http://localhost:11434
LLM_MODEL_NAME=qwen3:latest
LLM_MAX_CONCURRENT=3

# 关键：降低 num_ctx 适配 11GB 显存
OLLAMA_NUM_CTX=16384
OLLAMA_NUM_CTX_CORRECTION=4096

# ASR 批次大小（11GB 下保守值）
ASR_BATCH_SIZE=30
ASR_DEVICE=auto
ASR_DTYPE=float16

# 评估与合规 num_ctx（已在安全范围）
EVALUATION_NUM_CTX=8192
COMPLIANCE_NUM_CTX=8192

# CORS（替换为前端实际访问地址）
CORS_ORIGINS=["http://130.100.100.167:3000"]

# 上传目录（生产建议绝对路径）
UPLOAD_DIR=/data/copernicus/uploads
MAX_UPLOAD_SIZE_MB=15000

# YOLO 模型路径（相对后端工作目录）
FACE_DETECT_MODEL=models/yolov8n-face.pt

```

系统服务无法解析注释，需要做如下操作：

```
# 剥离行内注释（保留纯值行）
sed -i 's/[[:blank:]]*#.*$//' /opt/copernicus/backend/.env

# 清除处理后产生的空行（可选，不影响启动）
sed -i '/^[[:blank:]]*$/d' /opt/copernicus/backend/.env
```

模型下载完成后，将以下变量写入 `~/.bashrc` 开启离线模式，避免每次启动时联网检查。**不要**写入 `.env`，该变量不是应用配置字段，写入会导致 Pydantic 校验报错。

```
echo 'export HF_HUB_OFFLINE=1' >> ~/.bashrc
source ~/.bashrc
```

### 6.7 验证后端启动

```
cd /opt/copernicus/backend
source .venv/bin/activate

uvicorn copernicus.main:app --host 0.0.0.0 --port 8000
```

观察启动日志，确认以下几行出现后说明服务就绪：

```
INFO  CUDA available: NVIDIA GeForce RTX 2080 Ti (VRAM: 11.0 GB)
INFO  ASR model loaded successfully
INFO  Application startup complete.
```

健康检查：

```
curl http://localhost:8000/api/v1/health
# 预期：{"asr_loaded": true, "llm_reachable": true}
```

---

## 七、前端部署

### 7.1 安装 Node.js

以 `bht_admin` 身份执行：

```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc

nvm install 22
nvm use 22
node --version   # v22.x.x
```

### 7.2 构建前端

```
cd /opt/copernicus/frontend
npm install
npm run build
```

构建产物输出到 `frontend/dist/`。

### 7.3 配置 API 地址

若前端与后端同机部署，`vite.config.ts` 中的代理配置无需修改。

若前后端分离部署，需修改前端环境变量（构建前设置）：

```
# frontend/.env.production
VITE_API_BASE_URL=http://130.100.100.167:8000
```

---

## 八、Nginx 反向代理（推荐）

使用 Nginx 统一入口，将前端静态资源和后端 API 合并到同一端口，避免跨域问题。

### 8.1 安装 Nginx

```
# 以 root 执行
dnf install -y nginx
```

### 8.2 配置文件

以 root 身份创建 `/etc/nginx/conf.d/copernicus.conf`：

```
server {
    listen 80;
    server_name 130.100.100.167;

    # 前端静态资源
    location / {
        root /opt/copernicus/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;

        # 支持大文件上传
        client_max_body_size 15000m;
    }

    # 媒体文件（大文件，关闭缓冲）
    location /api/v1/tasks/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_buffering off;
        proxy_read_timeout 3600;
        client_max_body_size 15000m;
    }
}
```

若使用 Nginx 反代，CORS 配置可简化为：

```
# .env 中的 CORS_ORIGINS 改为同源（通过 Nginx 统一入口）
CORS_ORIGINS=["http://130.100.100.167"]
```

启动 Nginx：

```
# 以 root 执行
nginx -t
```

---

## 九、Systemd 服务管理

### 9.1 后端服务

以 root 身份创建 `/etc/systemd/system/copernicus-backend.service`：

```
[Unit]
Description=Copernicus Backend (FastAPI)
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=bht_admin
Group=bht_admin
WorkingDirectory=/opt/copernicus/backend
Environment="PATH=/home/bht_admin/.pyenv/shims:/home/bht_admin/.pyenv/bin:/opt/copernicus/backend/.venv/bin:/usr/local/bin:/usr/bin"
EnvironmentFile=/opt/copernicus/backend/.env
ExecStart=/opt/copernicus/backend/.venv/bin/uvicorn copernicus.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --timeout-keep-alive 120
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**注意**：FastAPI 使用 asyncio，`--workers 1` 是正确配置。多 worker 会导致 GPU 锁和内存 TaskStore 无法共享。

### 9.2 启用服务

```
# 以 bht_admin 执行
# 剥离所有行内注释（# 前有空白字符的部分）
sed -i 's/[[:space:]]\+#.*$//' /opt/copernicus/backend/.env

# 验证几个关键行是否正常
grep -E '^(ASR_BATCH_SIZE|LLM_TIMEOUT|OLLAMA_NUM_CTX)' /opt/copernicus/backend/.env

预期输出应为纯值，无注释：
ASR_BATCH_SIZE=30
LLM_TIMEOUT=180
OLLAMA_NUM_CTX=16384
```

```
# 以 root 执行
systemctl daemon-reload
systemctl enable --now copernicus-backend

systemctl enable --now nginx

# 查看实时日志
journalctl -u copernicus-backend -f
```

---

## 十、启动顺序与依赖关系

服务之间存在依赖，按以下顺序启动：

```
1. ollama              （LLM 推理服务）
       |
       v
2. copernicus-backend  （FastAPI，启动时加载 ASR 模型，约需 30-60 秒）
       |
       v
3. nginx               （反向代理，前端静态资源服务）
```

全部启动后，通过健康检查确认就绪：

```
curl http://130.100.100.167/api/v1/health
```

预期返回：

```json
{ "asr_loaded": true, "llm_reachable": true }
```

---

## 十一、关键配置对照表

以下列出与开发环境（RTX 5080 16GB）差异较大的参数，确认已按生产机器调整：

| 配置项                    | 开发环境值     | 生产机器推荐值           | 原因                   |
| ------------------------- | -------------- | ------------------------ | ---------------------- |
| OLLAMA_NUM_CTX            | 32768          | 16384                    | 11GB 显存限制          |
| OLLAMA_NUM_CTX_CORRECTION | 16384          | 4096                     | 同上                   |
| ASR_BATCH_SIZE            | 60             | 30                       | 防 OOM                 |
| CORS_ORIGINS              | localhost:3000 | 服务器实际 IP            | 跨域访问               |
| UPLOAD_DIR                | ./uploads      | /data/copernicus/uploads | 生产绝对路径           |
| HF_HUB_OFFLINE            | 未设置         | 1                        | 离线模式，避免联网检查 |
| EVALUATION_NUM_CTX        | 8192           | 8192（不变）             | 已在安全范围           |
| COMPLIANCE_NUM_CTX        | 8192           | 8192（不变）             | 已在安全范围           |

---

## 十二、常见问题排查

### DNS 解析失败导致所有 dnf 命令报错

现象：`Could not resolve host: mirrors.rockylinux.org` 或 `Cannot find a valid baseurl for repo`。

```
# 检查当前 DNS
cat /etc/resolv.conf

# 写入国内公共 DNS
cat > /etc/resolv.conf << 'EOF'
nameserver 114.114.114.114
nameserver 223.5.5.5
EOF

# 验证解析正常后重新执行 1.2 节的 repo 替换步骤
nslookup mirrors.ustc.edu.cn
```

### config-manager 命令不存在

现象：执行 `dnf config-manager` 时提示 `unknown command`。

```
dnf install -y dnf5-command(config-manager)
```

### GPU OOM（显存溢出）

现象：后端日志出现 `CUDA out of memory`，任务状态变为 failed。

```
nvidia-smi

# 在 .env 中调低 num_ctx
OLLAMA_NUM_CTX=8192
OLLAMA_NUM_CTX_CORRECTION=4096
ASR_BATCH_SIZE=20

# 以 root 执行
systemctl restart copernicus-backend
```

### ASR 模型加载失败

现象：健康检查返回 `"asr_loaded": false`。

```
journalctl -u copernicus-backend -n 100 | grep -i "asr\|error\|exception"

# 常见原因 1：ModelScope 模型未下载完整，删除缓存目录重新下载
rm -rf ~/.cache/modelscope/hub/iic/

# 常见原因 2：CUDA 版 PyTorch 未正确安装
python -c "import torch; print(torch.cuda.is_available())"
```

### LLM 不可达

现象：健康检查返回 `"llm_reachable": false`。

```
systemctl status ollama
journalctl -u ollama -n 50
curl http://localhost:11434/api/tags
```

### 文件上传失败（413 错误）

```
grep client_max_body_size /etc/nginx/conf.d/copernicus.conf
# 检查 .env 中 MAX_UPLOAD_SIZE_MB 是否匹配
```

### ffmpeg 命令不存在

```
which ffmpeg
rpm -qa | grep rpmfusion
```

### 权限错误（bht_admin 无法写入目录）

现象：后端日志出现 `PermissionError`，通常是上传目录所有权未正确设置。

```
# 以 root 执行
chown -R bht_admin:bht_admin /data/copernicus /opt/copernicus
```

---

## 十三、日志与监控

### 实时日志

```
# 后端日志
journalctl -u copernicus-backend -f

# Ollama 日志
journalctl -u ollama -f

# Nginx 访问日志
tail -f /var/log/nginx/access.log
```

### GPU 监控

```
watch -n 1 nvidia-smi
```

### 磁盘占用

上传文件持久化在 `/data/copernicus/uploads/`，每个任务目录包含音视频文件和关键帧图片，长期运行需定期清理已处理的历史任务：

```
du -sh /data/copernicus/uploads/

# 清理 30 天前的任务目录（谨慎操作，先确认无需保留）
find /data/copernicus/uploads/ -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \;
```

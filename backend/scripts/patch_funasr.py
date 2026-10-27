"""给已安装的 FunASR 打补丁（幂等）。

三处补丁：
  1. paraformer/model.py       输出逐 token 置信度（token_confidence）
  2. seaco_paraformer/model.py 输出逐 token 置信度
  3. seaco_paraformer/model.py 缓存热词解析结果（44 分钟音频的 VAD 片段会重复解析 105 次）

置信度是"跳过高置信度片段、只把可疑片段送 LLM 纠错"的前提；缺少补丁时全部片段都会送 LLM，
纠错耗时从约 3 分钟退化为 2 小时以上。

每次 `uv sync` 重装或升级 funasr 后，补丁都会被覆盖，需要重新执行：

    uv run python scripts/patch_funasr.py          # 打补丁
    uv run python scripts/patch_funasr.py --check  # 只检查，不修改

已打过补丁的文件报告"已应用"并正常退出；某处锚点找不到（FunASR 版本变化）或 --check 发现
未打补丁时退出码为 1。首次修改前会在同目录保存 model.py.orig 备份。

写入方式是"先写临时文件再改名"：uv 从缓存安装包时会用写时复制或硬链接，原地改写可能
连带改坏 uv 缓存里的同一份文件。
"""

import argparse
import importlib.util
import os
import shutil
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

CONFIDENCE_MARKER = "# Compute per-token confidence (am_scores is log_softmax, exp to get probabilities)"
INJECT_MARKER = 'result_i["token_confidence"] = _token_confidence'
HOTWORD_MARKER = "# hotword (with cache to avoid repeated parsing across VAD segments)"

_GREEDY_ARGMAX = (
    "                yseq = am_scores.argmax(dim=-1)\n"
    "                score = am_scores.max(dim=-1)[0]\n"
    "                score = torch.sum(score, dim=-1)\n"
)
_INJECT_BLOCK = (
    "                # Inject per-token confidence scores (computed in non-beam-search path)\n"
    "                try:\n"
    "                    result_i[\"token_confidence\"] = _token_confidence\n"
    "                except NameError:\n"
    "                    pass\n"
    "\n"
)
_HOTWORD_CACHED = (
    f"        {HOTWORD_MARKER}\n"
    "        _hw_input = kwargs.get(\"hotword\", None)\n"
    "        if not hasattr(self, \"_cached_hw_input\") or self._cached_hw_input != _hw_input:\n"
    "            self.hotword_list = self.generate_hotwords_list(\n"
    "                _hw_input, tokenizer=tokenizer, frontend=frontend\n"
    "            )\n"
    "            self._cached_hw_input = _hw_input\n"
)


@dataclass(frozen=True)
class Patch:
    file: str                     # 相对 funasr 包根目录
    label: str
    marker: str                   # 文件中已含此文本即视为已应用
    anchors: tuple[tuple[str, str], ...]  # (旧文本, 新文本)，按 FunASR 版本从新到旧依次尝试


def _confidence_extraction(file: str) -> Patch:
    return Patch(
        file, "token_confidence 提取", CONFIDENCE_MARKER,
        ((_GREEDY_ARGMAX,
          _GREEDY_ARGMAX
          + f"                {CONFIDENCE_MARKER}\n"
          "                _token_confidence = torch.exp(am_scores).max(dim=-1)[0].tolist()\n"),),
    )


_PARAFORMER = "models/paraformer/model.py"
_SEACO = "models/seaco_paraformer/model.py"

_IBEST = (
    "                    if ibest_writer is not None:\n"
    "                        ibest_writer[\"token\"][key[i]] = \" \".join(token)\n"
)

PATCHES: tuple[Patch, ...] = (
    _confidence_extraction(_PARAFORMER),
    Patch(
        _PARAFORMER, "token_confidence 注入结果", INJECT_MARKER,
        ((_IBEST, textwrap.indent(_INJECT_BLOCK, "    ") + _IBEST),),  # 此处比 seaco 深一层缩进
    ),
    Patch(
        _SEACO, "热词列表缓存", HOTWORD_MARKER,
        (
            # FunASR 1.3.1+：kwargs.get() 直接内联在调用里
            ("        # hotword\n"
             "        self.hotword_list = self.generate_hotwords_list(\n"
             "            kwargs.get(\"hotword\", None), tokenizer=tokenizer, frontend=frontend\n"
             "        )\n", _HOTWORD_CACHED),
            # 1.3.1 之前：经 _hw_input 中间变量
            ("        _hw_input = kwargs.get(\"hotword\", None)\n"
             "        self.hotword_list = self.generate_hotwords_list(\n"
             "            _hw_input, tokenizer=tokenizer, frontend=frontend\n"
             "        )\n", _HOTWORD_CACHED),
        ),
    ),
    _confidence_extraction(_SEACO),
    Patch(
        _SEACO, "token_confidence 注入结果", INJECT_MARKER,
        (("                results.append(result_i)\n", _INJECT_BLOCK + "                results.append(result_i)\n"),),
    ),
)


def find_funasr_root() -> Path:
    # 只定位不导入：import funasr 会连带加载 torch，耗时数秒且可能因显卡环境失败
    spec = importlib.util.find_spec("funasr")
    if spec is None or not spec.submodule_search_locations:
        sys.exit("错误：当前 Python 环境未安装 funasr")
    return Path(next(iter(spec.submodule_search_locations)))


def _replace_file(path: Path, text: str) -> None:
    # 新建 inode 再改名，不与 uv 缓存共享数据块
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    shutil.copymode(path, tmp)
    os.replace(tmp, path)


def apply(root: Path, patch: Patch, check_only: bool = False) -> bool:
    path = root / patch.file
    text = path.read_text(encoding="utf-8")
    name = f"{patch.file} :: {patch.label}"
    if patch.marker in text:
        print(f"  [已应用] {name}")
        return True
    if check_only:
        print(f"  [未应用] {name}", file=sys.stderr)
        return False
    for old, new in patch.anchors:
        if old in text:
            backup = path.with_name(path.name + ".orig")
            if not backup.exists():
                shutil.copy2(path, backup)
            _replace_file(path, text.replace(old, new, 1))
            print(f"  [已打补丁] {name}")
            return True
    print(f"  [失败] 找不到锚点（FunASR 版本可能已变化）：{name}", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="给已安装的 FunASR 打补丁（幂等）")
    parser.add_argument("--check", action="store_true", help="只检查补丁是否已应用，不修改文件")
    args = parser.parse_args(argv)

    root = find_funasr_root()
    print(f"FunASR 目录：{root}\n")
    # 不用 all([...])：即使某项失败也要继续，一次性报告全部结果
    results = [apply(root, patch, check_only=args.check) for patch in PATCHES]
    if all(results):
        print("\n全部补丁就绪。")
        return 0
    if args.check:
        print("\n补丁未全部应用，运行 scripts/patch_funasr.py（不带 --check）补上。", file=sys.stderr)
    else:
        print("\n部分补丁未能应用，置信度过滤将失效，请检查上面的失败项。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

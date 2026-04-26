"""Apply custom patches to the installed FunASR package.

Three patches are applied:
  1. paraformer/model.py      -- token_confidence injection
  2. seaco_paraformer/model.py -- token_confidence injection
  3. seaco_paraformer/model.py -- hotword list cache

Run once after every `pip install funasr` or version upgrade:

    python scripts/patch_funasr.py

The script is idempotent: running it again on an already-patched install
reports "already applied" and exits cleanly.
"""

import sys
from pathlib import Path


def _find_funasr_root() -> Path:
    try:
        import funasr
        return Path(funasr.__file__).parent
    except ImportError:
        print("ERROR: funasr is not installed in the current Python environment.", file=sys.stderr)
        sys.exit(1)


def _apply(path: Path, marker: str, old: str, new: str, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"  [already applied] {label}")
        return True
    if old not in text:
        print(f"  [WARN] anchor not found, skipping: {label}", file=sys.stderr)
        print(f"         File: {path}", file=sys.stderr)
        return False
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  [patched] {label}")
    return True


def patch_paraformer(funasr_root: Path) -> None:
    path = funasr_root / "models" / "paraformer" / "model.py"

    # Patch: inject token_confidence after argmax in greedy-decode branch
    _apply(
        path,
        marker="# Compute per-token confidence (am_scores is log_softmax, exp to get probabilities)",
        old=(
            "                yseq = am_scores.argmax(dim=-1)\n"
            "                score = am_scores.max(dim=-1)[0]\n"
            "                score = torch.sum(score, dim=-1)\n"
        ),
        new=(
            "                yseq = am_scores.argmax(dim=-1)\n"
            "                score = am_scores.max(dim=-1)[0]\n"
            "                score = torch.sum(score, dim=-1)\n"
            "                # Compute per-token confidence (am_scores is log_softmax, exp to get probabilities)\n"
            "                _token_confidence = torch.exp(am_scores).max(dim=-1)[0].tolist()\n"
        ),
        label="paraformer/model.py :: _token_confidence extraction",
    )

    # Patch: inject token_confidence into result dict
    _apply(
        path,
        marker='result_i["token_confidence"] = _token_confidence',
        old=(
            "                    if ibest_writer is not None:\n"
            "                        ibest_writer[\"token\"][key[i]] = \" \".join(token)\n"
        ),
        new=(
            "                    # Inject per-token confidence scores (computed in non-beam-search path)\n"
            "                    try:\n"
            "                        result_i[\"token_confidence\"] = _token_confidence\n"
            "                    except NameError:\n"
            "                        pass\n"
            "\n"
            "                    if ibest_writer is not None:\n"
            "                        ibest_writer[\"token\"][key[i]] = \" \".join(token)\n"
        ),
        label="paraformer/model.py :: result_i token_confidence injection",
    )


def patch_seaco_paraformer(funasr_root: Path) -> None:
    path = funasr_root / "models" / "seaco_paraformer" / "model.py"

    # Patch 1: hotword cache
    # Try pre-1.3.1 style first (uses _hw_input intermediate variable)
    if not _apply(
        path,
        marker="# hotword (with cache to avoid repeated parsing across VAD segments)",
        old=(
            "        _hw_input = kwargs.get(\"hotword\", None)\n"
            "        self.hotword_list = self.generate_hotwords_list(\n"
            "            _hw_input, tokenizer=tokenizer, frontend=frontend\n"
            "        )\n"
        ),
        new=(
            "        # hotword (with cache to avoid repeated parsing across VAD segments)\n"
            "        _hw_input = kwargs.get(\"hotword\", None)\n"
            "        if not hasattr(self, \"_cached_hw_input\") or self._cached_hw_input != _hw_input:\n"
            "            self.hotword_list = self.generate_hotwords_list(\n"
            "                _hw_input, tokenizer=tokenizer, frontend=frontend\n"
            "            )\n"
            "            self._cached_hw_input = _hw_input\n"
        ),
        label="seaco_paraformer/model.py :: hotword list cache",
    ):
        # FunASR 1.3.1+: kwargs.get() inlined directly into the call
        _apply(
            path,
            marker="# hotword (with cache to avoid repeated parsing across VAD segments)",
            old=(
                "        # hotword\n"
                "        self.hotword_list = self.generate_hotwords_list(\n"
                "            kwargs.get(\"hotword\", None), tokenizer=tokenizer, frontend=frontend\n"
                "        )\n"
            ),
            new=(
                "        # hotword (with cache to avoid repeated parsing across VAD segments)\n"
                "        _hw_input = kwargs.get(\"hotword\", None)\n"
                "        if not hasattr(self, \"_cached_hw_input\") or self._cached_hw_input != _hw_input:\n"
                "            self.hotword_list = self.generate_hotwords_list(\n"
                "                _hw_input, tokenizer=tokenizer, frontend=frontend\n"
                "            )\n"
                "            self._cached_hw_input = _hw_input\n"
            ),
            label="seaco_paraformer/model.py :: hotword list cache (1.3.1+)",
        )

    # Patch 2: token_confidence extraction
    _apply(
        path,
        marker="# Compute per-token confidence (am_scores is log_softmax, exp to get probabilities)",
        old=(
            "                yseq = am_scores.argmax(dim=-1)\n"
            "                score = am_scores.max(dim=-1)[0]\n"
            "                score = torch.sum(score, dim=-1)\n"
        ),
        new=(
            "                yseq = am_scores.argmax(dim=-1)\n"
            "                score = am_scores.max(dim=-1)[0]\n"
            "                score = torch.sum(score, dim=-1)\n"
            "                # Compute per-token confidence (am_scores is log_softmax, exp to get probabilities)\n"
            "                _token_confidence = torch.exp(am_scores).max(dim=-1)[0].tolist()\n"
        ),
        label="seaco_paraformer/model.py :: _token_confidence extraction",
    )

    # Patch 3: token_confidence injection into result dict
    _apply(
        path,
        marker='result_i["token_confidence"] = _token_confidence',
        old=(
            "                # Inject per-token confidence scores (computed in non-beam-search path)\n"
        ),
        new=(
            "                # Inject per-token confidence scores (computed in non-beam-search path)\n"
        ),
        label="seaco_paraformer/model.py :: result_i token_confidence injection (already structured)",
    )

    # Fallback: check if injection block needs to be inserted before results.append
    text = path.read_text(encoding="utf-8")
    if 'result_i["token_confidence"] = _token_confidence' not in text:
        _apply(
            path,
            marker='result_i["token_confidence"] = _token_confidence',
            old="                results.append(result_i)\n",
            new=(
                "                # Inject per-token confidence scores (computed in non-beam-search path)\n"
                "                try:\n"
                "                    result_i[\"token_confidence\"] = _token_confidence\n"
                "                except NameError:\n"
                "                    pass\n"
                "\n"
                "                results.append(result_i)\n"
            ),
            label="seaco_paraformer/model.py :: result_i token_confidence injection",
        )


def verify(funasr_root: Path) -> bool:
    markers = [
        (
            funasr_root / "models" / "paraformer" / "model.py",
            "# Compute per-token confidence (am_scores is log_softmax, exp to get probabilities)",
        ),
        (
            funasr_root / "models" / "seaco_paraformer" / "model.py",
            "# hotword (with cache to avoid repeated parsing across VAD segments)",
        ),
        (
            funasr_root / "models" / "seaco_paraformer" / "model.py",
            'result_i["token_confidence"] = _token_confidence',
        ),
    ]
    ok = True
    for path, marker in markers:
        found = marker in path.read_text(encoding="utf-8")
        status = "OK" if found else "MISSING"
        print(f"  [{status}] {path.name} :: {marker[:60]}")
        if not found:
            ok = False
    return ok


def main() -> None:
    funasr_root = _find_funasr_root()
    print(f"FunASR root: {funasr_root}\n")

    print("Applying patches ...")
    patch_paraformer(funasr_root)
    patch_seaco_paraformer(funasr_root)

    print("\nVerifying patches ...")
    if verify(funasr_root):
        print("\nAll patches applied successfully.")
    else:
        print("\nSome patches could not be verified. Check warnings above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

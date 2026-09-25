"""部署工具链：模型清单、打包白名单、FunASR 补丁与 deploy/ 脚本的静态检查。"""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from copernicus.config import Settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, BACKEND_DIR / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRequiredModelIds:
    def test_paraformer_mode_lists_four_models(self):
        ids = Settings(asr_mode="paraformer").required_asr_model_ids
        assert len(ids) == 4 and "iic/SenseVoiceSmall" not in ids

    def test_sensevoice_mode_swaps_main_model_and_drops_punc(self):
        s = Settings(asr_mode="sensevoice")
        ids = s.required_asr_model_ids
        assert s.sensevoice_model_dir in ids and s.asr_model_dir not in ids
        assert s.punc_model_dir not in ids

    def test_unset_models_are_skipped(self):
        assert Settings(vad_model_dir="", spk_model_dir="").required_asr_model_ids == [
            Settings().asr_model_dir, Settings().punc_model_dir,
        ]


class TestBuildPackage:
    @pytest.fixture(scope="class")
    def mod(self):
        return _load_script("build_package")

    @pytest.mark.parametrize("rel", [
        "src/copernicus/__pycache__/x.pyc", "tests/test_a.py", ".env", "scripts/build_package.py",
    ])
    def test_excluded(self, mod, rel):
        assert mod._is_excluded(Path(rel))

    @pytest.mark.parametrize("rel", ["src/copernicus/main.py", ".env.prod", "scripts/patch_funasr.py"])
    def test_included(self, mod, rel):
        assert not mod._is_excluded(Path(rel))


class TestPatchFunasr:
    @pytest.fixture(scope="class")
    def mod(self):
        return _load_script("patch_funasr")

    def test_apply_is_idempotent_and_keeps_backup(self, mod, tmp_path):
        patch = mod.Patch("m.py", "demo", "# done", ((" old\n", " old\n # done\n"),))
        target = tmp_path / "m.py"
        target.write_text("x\n old\ny\n", encoding="utf-8")

        assert mod.apply(tmp_path, patch) is True
        assert "# done" in target.read_text(encoding="utf-8")
        assert (tmp_path / "m.py.orig").read_text(encoding="utf-8") == "x\n old\ny\n"

        before = target.read_text(encoding="utf-8")
        assert mod.apply(tmp_path, patch) is True
        assert target.read_text(encoding="utf-8") == before

    def test_missing_anchor_reports_failure(self, mod, tmp_path):
        (tmp_path / "m.py").write_text("nothing here", encoding="utf-8")
        patch = mod.Patch("m.py", "demo", "# done", (("absent", "x"),))
        assert mod.apply(tmp_path, patch) is False


@pytest.mark.skipif(shutil.which("bash") is None, reason="需要 bash")
class TestDeployScripts:
    @pytest.mark.parametrize("script", ["lib.sh", "install.sh", "uninstall.sh"])
    def test_syntax(self, script):
        subprocess.run(["bash", "-n", str(REPO_DIR / "deploy" / script)], check=True)

    def test_templates_render_without_leftover_placeholders(self, tmp_path):
        cmd = (
            f"source {REPO_DIR}/deploy/lib.sh; SERVER_NAME=demo.local; "
            f"for t in {REPO_DIR}/deploy/templates/*.in; do "
            f'render_template "$t" "{tmp_path}/$(basename "$t" .in)"; done'
        )
        subprocess.run(["bash", "-c", cmd], check=True)
        rendered = list(tmp_path.iterdir())
        assert len(rendered) == 2
        assert all("@" not in f.read_text(encoding="utf-8") for f in rendered)

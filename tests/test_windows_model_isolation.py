"""Offline regression: fake vault credentials; never runs Claude or calls APIs."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "spider_core/core/windows_utils.py"
spec = importlib.util.spec_from_file_location("windows_utils_under_test", MODULE_PATH)
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)


class ClaudianEnvironmentTests(unittest.TestCase):
    def load(self, variables, parent=None):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            settings = vault / ".claudian" / "claudian-settings.json"
            settings.parent.mkdir()
            provider = {"environmentVariables": variables,
                        "cliPathsByHost": {"TEST_HOST": "configured-cli"}}
            settings.write_text(json.dumps({"providerConfigs": {"claude": provider}}),
                                encoding="utf-8")
            env = {"COMPUTERNAME": "TEST_HOST", **(parent or {})}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(utils, "_resolve_claude_exe", return_value="resolved-cli") as resolve:
                executable, config = utils.read_claudian_config(vault)
                resolve.assert_called_once_with("configured-cli")
                return executable, config, utils.resolve_model(), dict(os.environ)

    def test_stale_plugin_model_cannot_override_flash(self):
        _, _, model, env = self.load("ANTHROPIC_MODEL=deepseek-v4-pro")
        self.assertEqual(model, "deepseek-flash")
        self.assertNotIn("ANTHROPIC_MODEL", env)

    def test_credentials_endpoint_and_cli_still_work(self):
        executable, config, _, env = self.load(
            "ANTHROPIC_API_KEY=fake-key=with-equals\n"
            "ANTHROPIC_AUTH_TOKEN=fake-token\n"
            "ANTHROPIC_BASE_URL=https://provider.invalid/anthropic")
        self.assertEqual(executable, "resolved-cli")
        self.assertEqual(config["cliPathsByHost"]["TEST_HOST"], "configured-cli")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "fake-key=with-equals")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "fake-token")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://provider.invalid/anthropic")

    def test_explicit_operator_model_survives_plugin_config(self):
        _, _, model, env = self.load("ANTHROPIC_MODEL=deepseek-v4-pro",
                                     {"ANTHROPIC_MODEL": "operator-model"})
        self.assertEqual(model, "operator-model")
        self.assertEqual(env["ANTHROPIC_MODEL"], "operator-model")

    def test_spider_override_survives_plugin_config(self):
        _, _, model, _ = self.load("SPIDER_MODEL=plugin-model\nANTHROPIC_MODEL=deepseek-v4-pro",
                                   {"SPIDER_MODEL": "spider-model", "ANTHROPIC_MODEL": "operator-model"})
        self.assertEqual(model, "spider-model")

    def test_plugin_cannot_inject_auxiliary_models_or_cli_controls(self):
        _, _, _, env = self.load(
            "ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-pro\n"
            "ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro\n"
            "ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro\n"
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS=1\nPATH=plugin-path",
            {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "parent-model", "PATH": "parent-path"})
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "parent-model")
        self.assertNotIn("ANTHROPIC_DEFAULT_SONNET_MODEL", env)
        self.assertNotIn("ANTHROPIC_DEFAULT_OPUS_MODEL", env)
        self.assertNotIn("CLAUDE_CODE_MAX_OUTPUT_TOKENS", env)
        self.assertEqual(env["PATH"], "parent-path")

    def test_missing_plugin_configuration_preserves_defaults(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            self.assertEqual(utils.read_claudian_config(Path(directory)), ("claude", None))
            self.assertEqual(utils.resolve_model(), "deepseek-flash")


if __name__ == "__main__":
    unittest.main()

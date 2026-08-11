#!/usr/bin/env python3
"""确定性成熟度测试：不调模型、不连网、秒级。锁住结构、契约和已修复的 bug。
运行：python3 -m unittest tests/test_maturity.py -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["opportunity-researcher", "product-shaper", "user-experience-reviewer", "independent-critic"]
CORE_SKILLS = ["pmf-bet-brief", "prd-writing"]


def manifest(agent):
    return json.loads((ROOT / "agent-packages" / agent / "agent-package.json").read_text(encoding="utf-8"))


class StaticInventory(unittest.TestCase):
    def test_exactly_four_agents(self):
        found = sorted(p.name for p in (ROOT / "agent-packages").iterdir()
                       if p.is_dir() and not p.name.startswith("_"))
        self.assertEqual(found, sorted(AGENTS), "对外必须严格是 4 个 Agent 包")

    def test_two_core_skills(self):
        for s in CORE_SKILLS:
            self.assertTrue((ROOT / "skills" / s / "SKILL.md").is_file(), f"缺核心 skill: {s}")

    def test_one_workflow(self):
        self.assertTrue((ROOT / "workflows" / "pm-idea-to-delivery.json").is_file(), "缺唯一 workflow")


class ManifestContract(unittest.TestCase):
    REQUIRED = ["id", "runtime_agent_id", "name", "mission", "modes", "tools",
                "protocols", "domain_knowledge", "output_schema", "runtime", "capability"]

    def test_manifests_have_required_keys(self):
        for a in AGENTS:
            m = manifest(a)
            for k in self.REQUIRED:
                self.assertIn(k, m, f"{a} manifest 缺字段 {k}")

    def test_referenced_files_exist(self):
        """协议 / 领域知识 / 输出 schema 引用的文件必须真实存在（防悬空引用）。"""
        for a in AGENTS:
            m = manifest(a)
            for rel in m["protocols"] + m["domain_knowledge"] + [m["output_schema"]]:
                self.assertTrue((ROOT / rel).is_file(), f"{a} 引用了不存在的文件: {rel}")

    def test_capability_has_operating_loop_and_checks(self):
        for a in AGENTS:
            cap = manifest(a)["capability"]
            self.assertTrue(cap.get("operating_loop"), f"{a} 缺 operating_loop")
            self.assertTrue(cap.get("verification_checks"), f"{a} 缺 verification_checks")


class DeclaredToolsCallable(unittest.TestCase):
    def test_declared_tools_are_registered(self):
        """声明=可调用：manifest 声明的每个工具都必须在 runtime/tools.json 注册。"""
        known = {t["id"] for t in json.loads((ROOT / "runtime" / "tools.json").read_text())["tools"]}
        for a in AGENTS:
            for tool in manifest(a)["tools"]:
                self.assertIn(tool, known, f"{a} 声明了未注册的工具: {tool}")


class RegressionLocks(unittest.TestCase):
    def test_gateway_client_uses_curl_with_ua(self):
        """403 修复回归锁：网关必须走 curl + User-Agent，不能退回裸 urllib。"""
        src = (ROOT / "scripts" / "gateway_client.py").read_text(encoding="utf-8")
        self.assertIn('shutil.which("curl")', src, "gateway_client 必须用 curl")
        self.assertIn("User-Agent", src, "必须带 User-Agent（否则 Cloudflare 403）")

    def test_ensure_project_preserves_binding(self):
        """binding 覆盖 bug 回归锁：ensure_project 不能冲掉已有 data_gateway binding。"""
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "agent-packages" / "_shared"))
        from standalone_server import ensure_project
        tmp = Path(tempfile.mkdtemp())
        (tmp / "agent-config.json").write_text(
            json.dumps({"tool_overrides": {"data_gateway": {"binding": "IDOL102"}}}), encoding="utf-8")
        ensure_project(tmp, {"runtime_agent_id": "product_shaper"})
        cfg = json.loads((tmp / "agent-config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            (cfg.get("tool_overrides", {}).get("data_gateway") or {}).get("binding"), "IDOL102",
            "ensure_project 不能冲掉已有 binding")

    def test_protocols_have_evidence_priority(self):
        """外部优先回归锁：四个协议都要有'证据优先级'条款。"""
        for a in AGENTS:
            p = ROOT / "agent-packages" / a / "skills" / a / "references" / "operating-protocol.md"
            self.assertIn("证据优先级", p.read_text(encoding="utf-8"), f"{a} 协议缺'证据优先级'")


if __name__ == "__main__":
    unittest.main(verbosity=2)

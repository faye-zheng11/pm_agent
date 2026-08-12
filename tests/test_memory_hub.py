import tempfile
import unittest
from pathlib import Path

from runtime.memory_hub import MemoryHub


class MemoryHubIsolationTests(unittest.TestCase):
    def test_project_memories_and_turns_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = MemoryHub(Path(directory) / "memory.db")
            hub.append_turn("idol101", "user", "101 的目标是验证粉丝留存", source="codex", external_session_id="chat-1")
            memory = hub.propose_memory("idol101", "decision", "先验证留存，不直接进入正式开发", status="active")
            hub.append_turn("idol102", "user", "102 只做竞品研究", source="codex", external_session_id="chat-2")
            hub.propose_memory("idol102", "decision", "先做竞品研究", status="active")

            result = hub.search("idol101", "验证 留存", limit=20)
            self.assertEqual([item["project_id"] for item in result["memories"]], ["idol101"])
            self.assertEqual([item["project_id"] for item in result["turns"]], ["idol101"])
            self.assertEqual(memory["status"], "active")

    def test_unconfirmed_memory_is_not_in_context(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = MemoryHub(Path(directory) / "memory.db")
            hub.propose_memory("idol101", "fact", "未经确认的项目事实", status="candidate")
            hub.propose_memory("idol101", "fact", "PM 已确认的项目事实", status="active")
            context = hub.context("idol101")
            self.assertIn("PM 已确认的项目事实", context)
            self.assertNotIn("未经确认的项目事实", context)

    def test_user_memory_is_separate_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            project_hub = MemoryHub(Path(directory) / "project.db")
            user_hub = MemoryHub(Path(directory) / "user.db")
            user_hub.propose_memory("__user__", "preference", "输出默认使用中文", scope="user", status="active")
            project_hub.propose_memory("idol101", "decision", "101 先验证留存", status="active")
            self.assertIn("输出默认使用中文", user_hub.context("__user__"))
            self.assertNotIn("输出默认使用中文", project_hub.context("idol101"))
            self.assertNotIn("101 先验证留存", user_hub.context("__user__"))


if __name__ == "__main__":
    unittest.main()

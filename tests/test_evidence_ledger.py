import tempfile
import unittest
from pathlib import Path

from runtime.evidence_ledger import EvidenceLedger


class EvidenceLedgerTests(unittest.TestCase):
    def test_source_then_claim_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = EvidenceLedger(Path(directory) / ".workbench" / "evidence-ledger.json", "idol101")
            source = ledger.upsert_source({
                "id": "src-1",
                "url": "https://example.com/post",
                "title": "公开讨论",
                "source_type": "community",
                "accessed_at": "2026-08-19",
                "access_status": "verified",
                "evidence_grade": "B",
                "summary": "实际读取到用户的 workaround",
                "limitations": ["单一社区样本"],
            })
            self.assertEqual(source["operation"], "created")
            claim = ledger.upsert_claim({
                "id": "claim-1",
                "text": "目标用户已经在用替代方案解决问题",
                "classification": "evidence",
                "evidence_grade": "B",
                "source_ids": ["src-1"],
                "status": "active",
            })
            self.assertEqual(claim["claim"]["source_ids"], ["src-1"])
            result = ledger.list()
            self.assertEqual(len(result["sources"]), 1)
            self.assertEqual(len(result["claims"]), 1)

    def test_claim_cannot_reference_unknown_source(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = EvidenceLedger(Path(directory) / "evidence-ledger.json", "idol101")
            with self.assertRaises(ValueError):
                ledger.upsert_claim({
                    "id": "claim-1",
                    "text": "未有来源的判断",
                    "classification": "fact",
                    "evidence_grade": "A",
                    "source_ids": ["missing"],
                    "status": "active",
                })

    def test_project_binding_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence-ledger.json"
            first = EvidenceLedger(path, "idol101")
            first.upsert_source({
                "id": "src-1", "url": "https://example.com", "source_type": "official",
                "accessed_at": "2026-08-19", "access_status": "verified", "evidence_grade": "A",
            })
            with self.assertRaises(ValueError):
                EvidenceLedger(path, "idol102").list()


if __name__ == "__main__":
    unittest.main()

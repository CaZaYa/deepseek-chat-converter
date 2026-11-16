import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dsc2any.core import Options, convert  # noqa: E402


def build_export(path: Path) -> None:
    session = {
        "id": "s1",
        "title": "测试/会话",
        "current_message_id": 2,
        "inserted_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "messages": [
            {
                "id": 1, "parent_id": None, "role": "USER",
                "inserted_at": "2026-01-01T00:00:01Z",
                "fragments": [{"type": "REQUEST", "content": "你好"}],
            },
            {
                "id": 2, "parent_id": 1, "role": "ASSISTANT",
                "inserted_at": "2026-01-01T00:00:02Z",
                "fragments": [
                    {"type": "THINK", "content": "想一想"},
                    {"type": "RESPONSE", "content": "你好呀"},
                ],
            },
        ],
    }
    index = [{"id": "s1", "title": "测试/会话", "updated_at": "2026-01-02T00:00:00Z"}]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"export_format_version": 3}))
        archive.writestr("chat_session_index.json", json.dumps(index))
        archive.writestr("chat_sessions/s1.json", json.dumps(session))


class ConvertTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.zip = self.root / "export.zip"
        build_export(self.zip)

    def tearDown(self):
        self.tmp.cleanup()

    def test_markdown(self):
        report = convert(self.zip, self.root / "md", fmt="markdown")
        self.assertEqual(report.conversations, 1)
        files = list((self.root / "md" / "markdown").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        self.assertIn("# 测试/会话", text)
        self.assertIn("你好呀", text)
        self.assertNotIn("想一想", text)  # 默认不含思考

    def test_markdown_with_thinking(self):
        convert(self.zip, self.root / "md2", fmt="markdown", options=Options(with_thinking=True))
        text = next((self.root / "md2" / "markdown").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("想一想", text)

    def test_jsonl(self):
        report = convert(self.zip, self.root / "jl", fmt="jsonl")
        self.assertEqual(report.messages, 2)
        lines = (self.root / "jl" / "conversations.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        record = json.loads(lines[1])
        self.assertEqual(record["role"], "assistant")
        self.assertEqual(record["content"], "你好呀")

    def test_chatgpt(self):
        convert(self.zip, self.root / "cg", fmt="chatgpt", options=Options(chunk_size=0))
        data = json.loads((self.root / "cg" / "conversations.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        mapping = data[0]["mapping"]
        self.assertEqual(mapping["1"]["children"], ["2"])
        self.assertIn(data[0]["current_node"], mapping)

    def test_chatbox(self):
        convert(self.zip, self.root / "cb", fmt="chatbox", options=Options(with_thinking=True))
        zips = list((self.root / "cb").glob("chatbox-backup-*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("complete.json", names)
            sessions = [name for name in names if name.startswith("sessions/")]
            self.assertEqual(len(sessions), 1)
            raw = archive.read(sessions[0])
            self.assertTrue(raw.endswith(b"\n"))
            rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["formatVersion"], 3)
        self.assertRegex(manifest["createdAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
        self.assertEqual([row["type"] for row in rows[:2]], ["session", "thread"])
        messages = [row["message"] for row in rows if row["type"] == "message"]
        self.assertEqual(len(messages), 2)
        self.assertIsNone(messages[0]["parentMessageId"])
        self.assertEqual(messages[0]["activeChildId"], messages[1]["messageId"])
        self.assertEqual(messages[1]["message"]["contentParts"][0]["type"], "reasoning")
        self.assertEqual(messages[1]["message"]["contentParts"][1]["text"], "你好呀")

    def test_invalid_package(self):
        bad = self.root / "bad.zip"
        bad.write_bytes(b"nope")
        with self.assertRaises(Exception):
            convert(bad, self.root / "x", fmt="markdown")


if __name__ == "__main__":
    unittest.main()

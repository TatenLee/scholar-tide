import json
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from engine.core.type import InfoItem, Link
from engine.local_daily import write_json
from engine.publish_local import PublishError, git, publish_local
from engine.render.json import dump_json
from engine.translate_papers import prune


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.origin = self.folder / "origin.git"
        self.seed = self.folder / "seed"
        self.root = self.folder / "local"
        self.run_git(self.folder, "init", "--bare", "--initial-branch=main", str(self.origin))
        self.run_git(self.folder, "clone", str(self.origin), str(self.seed))
        self.article = {"title": "A paper", "content": "Original abstract", "source": "arxiv", "subject": "paper",
                        "published_at": "2026-10-12T01:00:00+00:00", "links": [{"label": "arxiv", "url": "https://arxiv.org/abs/2610.00001v1"}],
                        "title_zh": "旧译文", "content_zh": "旧摘要"}
        self.report = {"generated_at": "2026-10-12T02:00:00+00:00", "count": 2, "subjects": ["paper"],
                       "articles": [self.article, {**self.article, "title": "Untouched paper", "links": [{"url": "https://arxiv.org/abs/2610.00002v1"}]}]}
        write_json(self.seed / "data/report-2026-10-12.json", self.report)
        write_json(self.seed / "data/report.json", self.report)
        (self.seed / ".gitignore").write_text(".local/\nconfig/llm.local.*\n")
        (self.seed / "code.txt").write_text("original code")
        self.commit(self.seed)
        self.run_git(self.seed, "push", "origin", "main")
        self.run_git(self.folder, "clone", str(self.origin), str(self.root))
        self.local_article = {**self.article, "title_zh": "大模型标题", "content_zh": "大模型摘要", "access_token": "do-not-publish",
                              "study": {"overview": "学习笔记", "basis": "full_text", "model": "test-model", "generated_at": "2026-10-12T03:00:00+00:00", "private_field": "do-not-publish"}}
        write_json(self.root / ".local/data/report-2026-10-12.json", {**self.report, "articles": [self.local_article]})
        write_json(self.root / ".local/data/papers/2610.00001v1.json", {
            "id": "2610.00001v1", "status": "complete", "archive_date": "2026-10-12", "private_field": "do-not-publish",
            "blocks": [{"type": "paragraph", "en": "Text", "zh": "文本", "translation_engine": "llm:test-model", "secret": "do-not-publish"}]})
        (self.root / "code.txt").write_text("user's uncommitted changes")

    def tearDown(self):
        self.temp.cleanup()

    def run_git(self, root, *args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
        return result.stdout

    def commit(self, root):
        self.run_git(root, "add", ".")
        self.run_git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "test fixture")

    def remote_report(self):
        return json.loads(self.run_git(self.origin, "show", "main:data/report-2026-10-12.json"))

    def test_publish_is_selective_preserves_user_changes_and_is_idempotent(self):
        result = publish_local(self.root, tokens=("do-not-publish",))
        self.assertTrue(result["changed"])
        articles = self.remote_report()["articles"]
        self.assertEqual(articles[0]["title_zh"], "大模型标题")
        self.assertEqual(articles[1]["title"], "Untouched paper")
        self.assertNotIn("do-not-publish", json.dumps(articles))
        self.assertEqual((self.root / "code.txt").read_text(), "user's uncommitted changes")
        self.assertEqual(self.run_git(self.origin, "show", "main:code.txt"), "original code")
        self.assertNotIn(".local", self.run_git(self.origin, "ls-tree", "-r", "--name-only", "main"))
        paper = json.loads(self.run_git(self.origin, "show", "main:data/papers/2610.00001v1.json"))
        self.assertEqual(paper["published_from"], "local-llm")
        self.assertNotIn("do-not-publish", json.dumps(paper))
        second = publish_local(self.root, tokens=("do-not-publish",))
        self.assertFalse(second["changed"])
        self.assertEqual(len(self.run_git(self.root, "worktree", "list").splitlines()), 1)

    def test_known_token_in_model_output_stops_before_push(self):
        self.local_article["study"]["overview"] = "do-not-publish"
        write_json(self.root / ".local/data/report-2026-10-12.json", {**self.report, "articles": [self.local_article]})
        before = self.run_git(self.origin, "rev-parse", "main")
        with self.assertRaises(PublishError):
            publish_local(self.root, tokens=("do-not-publish",))
        self.assertEqual(self.run_git(self.origin, "rev-parse", "main"), before)

    def test_concurrent_remote_commit_is_merged_on_retry(self):
        pushed_once = [False]
        def interleaved(root, *args, **kwargs):
            if args[0] == "push" and not pushed_once[0]:
                pushed_once[0] = True
                self.report["articles"].append({**self.article, "title": "New cloud paper", "links": [{"url": "https://arxiv.org/abs/2610.00003v1"}]})
                write_json(self.seed / "data/report-2026-10-12.json", self.report)
                self.commit(self.seed)
                self.run_git(self.seed, "push", "origin", "main")
            return git(root, *args, **kwargs)
        with patch("engine.publish_local.git", interleaved):
            result = publish_local(self.root)
        self.assertTrue(result["changed"])
        titles = [article["title"] for article in self.remote_report()["articles"]]
        self.assertIn("New cloud paper", titles)
        self.assertEqual(self.remote_report()["articles"][0]["title_zh"], "大模型标题")

    def test_published_notes_survive_daily_build_and_full_text_survives_prune(self):
        publish_local(self.root)
        self.run_git(self.seed, "pull", "--ff-only")
        item = InfoItem("A paper", "Original abstract", datetime.now(timezone.utc), self.article["links"] and [Link("arxiv", self.article["links"][0]["url"])], source="arxiv")
        dump_json([item], self.seed / "data/report.json")
        latest = json.loads((self.seed / "data/report.json").read_text())
        self.assertEqual(latest["articles"][0]["study"]["overview"], "学习笔记")
        papers = self.seed / "data/papers"
        write_json(papers / "old.json", {"archive_date": "2026-09-01", "status": "complete"})
        prune(papers, keep_days=1, max_bytes=0, today=date(2027, 1, 1))
        self.assertTrue((papers / "2610.00001v1.json").exists())
        self.assertFalse((papers / "old.json").exists())


if __name__ == "__main__":
    unittest.main()

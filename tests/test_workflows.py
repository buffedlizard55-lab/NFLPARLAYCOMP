"""GitHub Actions workflow validation.

Motivation — a real bug this suite exists to prevent
----------------------------------------------------
Both scheduled workflows were rejected outright by GitHub because a single cron
entry used day-of-week ``7`` for Sunday. GitHub's day-of-week field is ``0-6``
(0 = Sunday). POSIX also accepts ``7``, so the file looks correct and standard
cron tools accept it, but GitHub rejects the **entire workflow file**. The only
symptom is a run that is created and then fails in zero seconds with no jobs, no
logs and no check runs — which reads like a permissions problem, not a typo, so
it is easy to misdiagnose.

These tests check the workflow contract statically, so the failure is caught here
instead of in the Actions tab.
"""
import glob
import io
import os
import re
import unittest

sys_path_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, sys_path_root)

WORKFLOWS_DIR = os.path.join(sys_path_root, ".github", "workflows")


def workflow_files():
    return sorted(glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml")) +
                  glob.glob(os.path.join(WORKFLOWS_DIR, "*.yaml")))


def read_text(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def cron_entries(path):
    out = []
    for line in read_text(path).splitlines():
        match = re.search(r'cron:\s*"([^"]+)"', line)
        if match:
            out.append(match.group(1))
            continue
        match = re.search(r"cron:\s*'([^']+)'", line)
        if match:
            out.append(match.group(1))
    return out


class TestWorkflowsPresent(unittest.TestCase):

    def test_workflow_files_exist(self):
        files = workflow_files()
        self.assertTrue(files, "no workflow files found")
        names = {os.path.basename(f) for f in files}
        for expected in ("collect.yml", "simulate.yml", "pages.yml"):
            with self.subTest(workflow=expected):
                self.assertIn(expected, names)

    def test_workflows_parse_as_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml not installed")
        for path in workflow_files():
            with self.subTest(workflow=os.path.basename(path)):
                yaml.safe_load(read_text(path))

    def test_no_byte_order_mark_or_crlf(self):
        """GitHub tolerates neither in workflow files."""
        for path in workflow_files():
            with self.subTest(workflow=os.path.basename(path)):
                with io.open(path, "rb") as handle:
                    raw = handle.read()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "workflow has a UTF-8 BOM")
                self.assertNotIn(b"\r\n", raw, "workflow uses CRLF line endings")


class TestCronSchedule(unittest.TestCase):
    """GitHub's cron dialect is stricter than POSIX. Validate it as GitHub does."""

    def test_every_cron_has_five_fields(self):
        for path in workflow_files():
            for cron in cron_entries(path):
                with self.subTest(workflow=os.path.basename(path), cron=cron):
                    self.assertEqual(len(cron.split()), 5,
                                     "GitHub cron requires exactly 5 fields")

    def test_day_of_week_is_0_to_6(self):
        """The exact bug that silently disabled both scheduled workflows.

        GitHub uses 0-6 with 0 = Sunday. A 7 (valid in POSIX) makes GitHub reject
        the whole file, and the run fails in 0s with no jobs and no logs.
        """
        for path in workflow_files():
            for cron in cron_entries(path):
                dow = cron.split()[4]
                for part in re.split(r"[,\-/]", dow):
                    if part in ("*", ""):
                        continue
                    with self.subTest(workflow=os.path.basename(path), cron=cron, field=dow):
                        value = int(part)
                        self.assertTrue(
                            0 <= value <= 6,
                            f"day-of-week {value} is outside GitHub's 0-6 range in '{cron}'. "
                            "POSIX allows 7 for Sunday but GitHub rejects the entire "
                            "workflow file, failing with no jobs and no logs.")

    def test_minute_and_hour_in_range(self):
        for path in workflow_files():
            for cron in cron_entries(path):
                fields = cron.split()
                for field_name, index, hi in (("minute", 0, 59), ("hour", 1, 23)):
                    for part in re.split(r"[,\-/]", fields[index]):
                        if part in ("*", ""):
                            continue
                        with self.subTest(workflow=os.path.basename(path),
                                          cron=cron, field=field_name):
                            value = int(part)
                            self.assertTrue(0 <= value <= hi,
                                            f"{field_name} {value} out of range in '{cron}'")

    def test_month_and_day_of_month_in_range(self):
        for path in workflow_files():
            for cron in cron_entries(path):
                fields = cron.split()
                for field_name, index, hi in (("day-of-month", 2, 31), ("month", 3, 12)):
                    for part in re.split(r"[,\-/]", fields[index]):
                        if part in ("*", ""):
                            continue
                        with self.subTest(workflow=os.path.basename(path),
                                          cron=cron, field=field_name):
                            value = int(part)
                            self.assertTrue(1 <= value <= hi,
                                            f"{field_name} {value} out of range in '{cron}'")


class TestScheduledJobsAreUsable(unittest.TestCase):
    """A scheduled workflow that cannot run at all is worse than none."""

    def test_scheduled_workflows_are_also_dispatchable(self):
        for path in workflow_files():
            if not cron_entries(path):
                continue
            with self.subTest(workflow=os.path.basename(path)):
                text = read_text(path)
                self.assertIn("workflow_dispatch", text,
                              "scheduled workflow should also support manual dispatch, "
                              "so it can be exercised without waiting for the schedule")

    def test_jobs_are_defined(self):
        for path in workflow_files():
            with self.subTest(workflow=os.path.basename(path)):
                text = read_text(path)
                self.assertRegex(text, r"(?m)^jobs:", "workflow defines no jobs")

    def test_collect_and_simulate_do_not_commit_a_root_bundle(self):
        """`site_data/` at the repo root was removed; a stale `git add` would resurrect it."""
        for name in ("collect.yml", "simulate.yml"):
            path = os.path.join(WORKFLOWS_DIR, name)
            if not os.path.exists(path):
                continue
            text = read_text(path)
            with self.subTest(workflow=name):
                self.assertNotIn("git add data/competition site_data docs", text)
                self.assertNotRegex(text, r"git add[^\n]*\bsite_data\b",
                                    "workflow stages the deprecated root site_data/ path")

    def test_no_real_credentials_or_order_placement(self):
        """This project is read-only paper trading; no workflow may hold a secret."""
        for path in workflow_files():
            text = read_text(path)
            with self.subTest(workflow=os.path.basename(path)):
                self.assertNotIn("secrets.", text,
                                 "workflows must not depend on credentials: the Kalshi "
                                 "client is read-only and unauthenticated by design")




class TestPagesDeployment(unittest.TestCase):
    """The Pages site must actually be reachable, not just "deployed".

    A successful deploy workflow does not guarantee visitors see the site: if the
    repository's Pages setting is the legacy root-path build, GitHub's legacy
    pipeline publishes the repository root and the workflow artifact is ignored.
    These checks pin the pieces that make the site reachable under either setting.
    """

    def test_root_forwarder_exists(self):
        """Under the legacy root-path build, '/' needs an index.html at the root."""
        root_index = os.path.join(sys_path_root, "index.html")
        self.assertTrue(os.path.exists(root_index),
                        "root index.html is the bridge that reaches docs/ while Pages "
                        "uses the legacy root-path build; see docs/OPERATIONS.md")
        html = read_text(root_index)
        self.assertIn("docs/", html, "root forwarder must point at docs/")

    def test_docs_index_exists_and_is_the_real_site(self):
        docs_index = os.path.join(sys_path_root, "docs", "index.html")
        self.assertTrue(os.path.exists(docs_index))
        html = read_text(docs_index)
        self.assertIn("app.js", html)
        self.assertIn("site_data", html + read_text(
            os.path.join(sys_path_root, "docs", "app.js")))

    def test_nojekyll_present(self):
        """Without .nojekyll, Pages' Jekyll pass skips files it should serve."""
        self.assertTrue(os.path.exists(os.path.join(sys_path_root, "docs", ".nojekyll")))

    def test_bundles_resolve_relative_to_docs(self):
        """Relative fetch paths must work whether docs/ is the artifact root or not."""
        js = read_text(os.path.join(sys_path_root, "docs", "app.js"))
        self.assertIn("site_data/", js)
        self.assertNotIn("/site_data/", js,
                         "absolute bundle paths would break when Pages serves from /docs")

    def test_pages_workflow_uploads_docs(self):
        path = os.path.join(WORKFLOWS_DIR, "pages.yml")
        text = read_text(path)
        self.assertIn("upload-pages-artifact", text)
        self.assertIn("'./docs'", text)
        self.assertNotIn('"site_data/**"', text,
                         "pages.yml should trigger on docs/** only; bundles live in docs/")

    def test_operations_documents_the_pages_setting(self):
        """The required Settings change must stay documented, since automation cannot apply it."""
        text = read_text(os.path.join(sys_path_root, "docs", "OPERATIONS.md"))
        self.assertIn("GitHub Actions", text)
        self.assertIn("legacy", text.lower())


if __name__ == "__main__":
    unittest.main()

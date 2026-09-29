# -*- coding: utf-8 -*-
"""Does the documentation describe what actually exists?

    python -m unittest discover tests

Why this file exists on its own
  This repository has had the same incident happen four times. The test
  count was written differently in three documents, and all three were wrong.
  A reference doc was moved to `references/`, but the body still pointed at
  the old path. A tool was built and never invoked from any step. Two design
  baseline numbers were typed in by hand and did not match the measured
  values.

  All of it comes down to one thing: "the docs drifted from the code." This
  is not the kind of thing a human catches by reading — it looks correct
  while you read it. A machine has to cross-check it.
"""
import io
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
DOCS = ["SKILL.md", "README.md", "INSTALL.md"]


def read(p):
    with io.open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


class DocsMatchReality(unittest.TestCase):

    def test_every_script_the_docs_name_exists(self):
        """Does the script the docs name actually exist?"""
        missing = []
        for d in DOCS:
            for m in re.finditer(r"scripts/([a-z_]+\.py)", read(d)):
                if not os.path.isfile(os.path.join(SCRIPTS, m.group(1))):
                    missing.append("%s: %s" % (d, m.group(1)))
        self.assertEqual(missing, [])

    def test_every_script_that_exists_is_named_in_the_skill(self):
        """A tool that is built but never invoked anywhere is as good as not
        existing.

        `prose_audit.py` was exactly that case — it was in the file table but not
        in any step.
        """
        skill = read("SKILL.md")
        unlisted = [f for f in sorted(os.listdir(SCRIPTS))
                    if f.endswith(".py") and not f.startswith("_")
                    and ("scripts/" + f) not in skill]
        self.assertEqual(unlisted, [], "scripts not mentioned in SKILL.md")

    def test_every_markdown_link_resolves(self):
        """If a reference file is moved without updating the path in the body,
        it silently goes unread."""
        bad = []
        for d in DOCS:
            for m in re.finditer(r"\[[^\]]+\]\(([^)#][^)]*)\)", read(d)):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                if not os.path.exists(os.path.join(ROOT, target)):
                    bad.append("%s -> %s" % (d, target))
        self.assertEqual(bad, [])

    def test_every_reference_file_is_pointed_at_from_the_skill(self):
        """A reference file must be linked directly from SKILL.md. Linking it
        through a chain means it goes unread."""
        ref = os.path.join(ROOT, "references")
        if not os.path.isdir(ref):
            self.skipTest("no references/")
        skill = read("SKILL.md")
        orphan = [f for f in sorted(os.listdir(ref))
                  if f.endswith(".md") and ("references/" + f) not in skill]
        self.assertEqual(orphan, [], "reference files SKILL.md does not point at")

    def test_reference_files_open_with_a_contents_list(self):
        """A reference file over 100 lines must open with a table of contents —
        so the scope is visible even if only part of it gets read."""
        ref = os.path.join(ROOT, "references")
        if not os.path.isdir(ref):
            self.skipTest("no references/")
        bad = []
        for f in sorted(os.listdir(ref)):
            if not f.endswith(".md"):
                continue
            with io.open(os.path.join(ref, f), encoding="utf-8") as f_:
                t = f_.read()
            if t.count("\n") > 100 and "## Contents" not in t[:1200]:
                bad.append(f)
        self.assertEqual(bad, [])

    def test_no_absolute_machine_paths(self):
        """It breaks on someone else's machine. A skill is a thing that gets
        distributed."""
        bad = []
        for d in DOCS:
            for m in re.finditer(r"[A-Za-z]:\\\\|/Users/|/home/[a-z]", read(d)):
                bad.append("%s: %s" % (d, m.group(0)))
        self.assertEqual(bad, [])

    def test_no_test_counts_written_into_prose(self):
        """27/30/61 were written into three documents, and all three were wrong.
        Get the number by running it."""
        bad = []
        for d in DOCS:
            for m in re.finditer(r"(\d+)\s+(?:passing\s+)?tests\b", read(d)):
                bad.append("%s: %s" % (d, m.group(0)))
        self.assertEqual(bad, [], "do not write the test count into the docs")

    def test_scripts_are_invoked_through_their_interpreter(self):
        """Invoking it by bare path causes some packagers to strip the executable
        bit, resulting in Permission denied."""
        bad = []
        for d in DOCS:
            for ln in read(d).splitlines():
                s = ln.strip()
                if s.startswith("scripts/") and s.endswith(".py"):
                    bad.append("%s: %s" % (d, s))
        self.assertEqual(bad, [])


class Frontmatter(unittest.TestCase):
    """If even one key falls outside the spec, claude.ai and the Skills API
    refuse the upload."""

    ALLOWED = {"name", "description", "license", "allowed-tools",
               "metadata", "compatibility"}

    def setUp(self):
        import yaml
        t = read("SKILL.md")
        self.assertTrue(t.startswith("---\n"), "no frontmatter")
        self.fm = yaml.safe_load(t.split("---", 2)[1])

    def test_only_spec_keys(self):
        self.assertEqual(set(self.fm) - self.ALLOWED, set())

    def test_required_keys_present(self):
        self.assertIn("name", self.fm)
        self.assertIn("description", self.fm)

    def test_name_is_kebab_case_and_matches_the_install_folder(self):
        """The name must match the folder name that INSTALL.md tells you to
        install into.

        It used to be compared against whatever folder it currently sits in. That
        way, copying it to run under a different name like `skill/` makes the
        test fail even though nothing is wrong with the skill (blind trial 11,
        defect 15).
        """
        self.assertRegex(self.fm["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(self.fm["name"]), 64)
        with open(os.path.join(ROOT, "INSTALL.md"), encoding="utf-8") as f:
            folders = set(re.findall(r"skills/([a-z0-9-]+)/", f.read()))
        self.assertEqual(folders, {self.fm["name"]})

    def test_description_within_limit_and_has_no_angle_brackets(self):
        d = self.fm["description"]
        self.assertLessEqual(len(d), 1024)
        self.assertNotIn("<", d)
        self.assertNotIn(">", d)

    def test_description_says_when_not_to_use_it(self):
        """Without a sentence narrowing the scope, it triggers on unrelated
        requests too."""
        self.assertIn("NOT for", self.fm["description"])

    def test_body_stays_under_the_line_limit(self):
        body = read("SKILL.md").split("---", 2)[2]
        self.assertLess(body.count("\n"), 500)


class Marketplace(unittest.TestCase):
    def test_manifest_is_valid_and_points_at_this_repo(self):
        import json
        p = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
        if not os.path.isfile(p):
            self.skipTest("no marketplace.json")
        with io.open(p, encoding="utf-8") as f_:
            m = json.load(f_)
        self.assertIn("name", m)
        self.assertIn("name", m.get("owner") or {})
        self.assertTrue(m.get("plugins"))
        for pl in m["plugins"]:
            self.assertIn("name", pl)
            src = pl.get("source")
            self.assertTrue(src)
            if isinstance(src, str) and src.startswith("./"):
                self.assertTrue(os.path.isdir(os.path.join(ROOT, src)))


class Evals(unittest.TestCase):
    """The official recommendation is at least three, and to also write
    down cases where it must not trigger."""

    def setUp(self):
        import json
        p = os.path.join(ROOT, "evals", "evals.json")
        if not os.path.isfile(p):
            self.skipTest("no evals.json")
        with io.open(p, encoding="utf-8") as f_:
            self.e = json.load(f_)

    def test_at_least_three_and_some_negatives(self):
        evals = self.e["evals"]
        self.assertGreaterEqual(len(evals), 3)
        neg = [x for x in evals
               if any("Did not use" in s or "NOT" in str(x.get("expected_output", ""))
                      for s in x.get("expectations", []))]
        self.assertGreaterEqual(len(neg), 1, "no case where it must not trigger")

    def test_referenced_files_exist(self):
        for x in self.e["evals"]:
            for f in x.get("files", []):
                self.assertTrue(os.path.exists(os.path.join(ROOT, f)), f)


class ScriptsRun(unittest.TestCase):
    """The docs must not call a script that cannot even answer `--help`."""

    def test_every_script_answers_help(self):
        bad = []
        for f in sorted(os.listdir(SCRIPTS)):
            if not f.endswith(".py") or f.startswith("_"):
                continue
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, f), "--help"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Modules used without arguments (sidecar, timing) do not need to support --help.
            if r.returncode not in (0, 2):
                bad.append("%s -> exit %d" % (f, r.returncode))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Run every check in one command: Python unit tests, the ledger/verification audit,
the manifest audit, and (when node is available) the front-end smoke test.

Exit code is non-zero if any gate fails, so this is what CI runs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _banner(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def run_python_tests() -> bool:
    """Discover and run tests/*.py.

    The tests insert the repository root on sys.path themselves and import
    ``engine.*`` as a top-level package, so discovery starts at the repo root.
    """
    _banner("Python unit tests")
    tests_dir = os.path.join(ROOT, "tests")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for filename in sorted(os.listdir(tests_dir)):
        if not filename.startswith("test_") or not filename.endswith(".py"):
            continue
        module_name = filename[:-3]
        try:
            suite.addTests(loader.loadTestsFromName(f"tests.{module_name}"))
        except Exception as error:  # noqa: BLE001 — surface an unimportable test file
            print(f"could not load tests/{filename}: {error}")
            return False
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return result.wasSuccessful()


def run_script(name: str, args: list[str]) -> bool:
    _banner(f"scripts/{name} {' '.join(args)}".strip())
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", name)] + args,
                          cwd=ROOT)
    return proc.returncode == 0


def run_site_smoke() -> bool:
    node = shutil.which("node")
    if not node:
        print("\nnode not available — skipping front-end smoke test "
              "(CI installs it; the GitHub Pages JS is still syntax-checked in tests)")
        return True
    _banner("Front-end smoke test (docs/app.js against real bundles)")
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "site_smoke.js")], cwd=ROOT)
    return proc.returncode == 0


def main() -> int:
    gates = {
        "python tests": run_python_tests(),
        "ledger + verification": run_script("verify.py", []),
        "fetch manifest": run_script("check_manifest.py", []),
        "site smoke": run_site_smoke(),
    }
    _banner("Summary")
    failed = [name for name, ok in gates.items() if not ok]
    for name, ok in gates.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print(f"\n{len(failed)} gate(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

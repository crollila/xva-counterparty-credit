"""One-command pipeline: tests -> experiment -> figures -> docs -> reconciliation.

    python run_all.py            # full run (~minutes)
    python run_all.py --quick    # small path counts, writes to scratch dirs
    python run_all.py --skip-tests
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def step(title, fn):
    print(f"\n=== {title} ===", flush=True)
    fn()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    a = ap.parse_args()

    from xva import experiment, figures, report

    results = ROOT / ("results_quick" if a.quick else "results")
    figs = ROOT / ("figures_quick" if a.quick else "figures")

    if not a.skip_tests:
        step("tests", lambda: subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=True))
    step("experiment", lambda: experiment.main((["--quick"] if a.quick else []) + ["--out", str(results)]))
    step("figures", lambda: figures.main(["--results", str(results), "--out", str(figs)]))
    if not a.quick:
        step("docs", lambda: report.main(["--write", "--results", str(results / "summary.json"), "--root", str(ROOT)]))
        step("reconcile", lambda: report.main(["--check", "--results", str(results / "summary.json"), "--root", str(ROOT)]))
    print("\nall steps completed")


if __name__ == "__main__":
    main()

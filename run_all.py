
import argparse
import subprocess
import sys
import os

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")


def run_step(script_name: str, description: str):
    print(f"\n{'=' * 60}")
    print(f"  {description}")
    print(f"{'=' * 60}")
    result = subprocess.run(
        [sys.executable, os.path.join(SRC_DIR, script_name)],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    if result.returncode != 0:
        print(f"\n✗ {script_name} failed — stopping pipeline.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run the LedgerLens reconciliation pipeline")
    parser.add_argument("--regenerate", action="store_true",
                         help="Regenerate synthetic data from scratch (same seed, same output)")
    parser.add_argument("--skip-ai", action="store_true",
                         help="Skip the AI resolver step (deterministic-only, no API calls/cost)")
    args = parser.parse_args()

    if args.regenerate:
        run_step("generate_data.py", "STEP 1: Generating synthetic data")

    run_step("normalize.py", "STEP 2: Normalizing data (sanity check)")
    run_step("deterministic_match.py", "STEP 3: Deterministic matching")

    if not args.skip_ai:
        run_step("ai_resolver.py", "STEP 4: AI resolver (calls Gemini API)")
    else:
        print("\nSkipping AI resolver (--skip-ai) — evaluation will run on "
              "deterministic-only results, or reuse any previously cached "
              "AI results if present.")

    run_step("evaluate.py", "STEP 5: Final benchmark evaluation")

    print(f"\n{'=' * 60}")
    print("Pipeline complete. See benchmark results above.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
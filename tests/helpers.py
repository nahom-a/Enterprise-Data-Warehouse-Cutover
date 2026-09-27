"""Helpers for the warehouse cutover verifier test suite."""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

# Paths inside verifier container vs local checkout
CONTAINER_ROOT = Path("/tests")
PROJECT_APP_ROOT = Path("/app/project")

LOCAL_ROOT = Path(__file__).resolve().parent.parent

if CONTAINER_ROOT.exists() and (CONTAINER_ROOT / "project").exists():
    TESTS_DIR = CONTAINER_ROOT
else:
    TESTS_DIR = LOCAL_ROOT / "tests"

if "CUTOVER_PROJECT_DIR" in os.environ:
    APP_PROJECT = Path(os.environ["CUTOVER_PROJECT_DIR"])
elif (LOCAL_ROOT / "solution" / "models").exists():
    APP_PROJECT = LOCAL_ROOT / "solution"
elif PROJECT_APP_ROOT.exists() and (PROJECT_APP_ROOT / "models").exists():
    APP_PROJECT = PROJECT_APP_ROOT
else:
    APP_PROJECT = LOCAL_ROOT / "environment" / "project"

RUNNER_PATH = TESTS_DIR / "project" / "tools" / "run.py"
if not RUNNER_PATH.exists():
    RUNNER_PATH = LOCAL_ROOT / "environment" / "project" / "tools" / "run.py"

COMPARE_PATH = TESTS_DIR / "project" / "tools" / "compare.py"
if not COMPARE_PATH.exists():
    COMPARE_PATH = LOCAL_ROOT / "environment" / "project" / "tools" / "compare.py"

# Add runner/compare directory to sys.path so we can import compare_mart
sys.path.insert(0, str(RUNNER_PATH.parent))
from compare import compare_mart  # noqa: E402

WINDOWS = ["sample", "h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8"]
MARTS = [
    "mart_customer_cohorts",
    "mart_customer_lifetime_value",
    "mart_customer_segment_revenue",
    "mart_daily_revenue",
    "mart_duplicate_customers",
    "mart_first_order_analysis",
    "mart_fx_exposure",
    "mart_guest_conversion",
    "mart_order_status_distribution",
    "mart_product_performance",
    "mart_promo_performance",
    "mart_refund_rate",
    "mart_revenue_by_day_currency",
    "mart_revenue_by_region",
    "mart_shipping_lead_times",
]


def get_data_dir(window: str) -> Path:
    if window == "sample":
        p = TESTS_DIR / "project" / "data" / "sample" / "platform"
        if p.exists():
            return p
        return LOCAL_ROOT / "environment" / "project" / "data" / "sample" / "platform"
    else:
        p = TESTS_DIR / "heldout" / window
        if p.exists():
            return p
        return LOCAL_ROOT / "tests" / "heldout" / window


def get_expected_mart_path(window: str, mart_name: str) -> Path:
    p = TESTS_DIR / "expected" / window / f"{mart_name}.parquet"
    if p.exists():
        return p
    return LOCAL_ROOT / "tests" / "expected" / window / f"{mart_name}.parquet"


def run_window(window: str, project_dir: Path = None) -> Path:
    """Runs the pristine runner for the given window as nobody (or fallback)."""
    if project_dir is None:
        project_dir = APP_PROJECT

    data_dir = get_data_dir(window)
    if not data_dir.exists():
        raise RuntimeError(f"Platform data directory not found for {window}: {data_dir}")

    out_dir = Path(tempfile.mkdtemp(prefix=f"marts_{window}_"))
    try:
        os.chmod(out_dir, 0o777)
    except Exception:
        pass

    stdout_path = Path(tempfile.mktemp(prefix=f"run_{window}_out_"))
    stderr_path = Path(tempfile.mktemp(prefix=f"run_{window}_err_"))

    python_bin = sys.executable
    if Path("/opt/venv/bin/python").exists():
        python_bin = "/opt/venv/bin/python"

    cmd = [
        python_bin,
        str(RUNNER_PATH),
        "--sources", "platform",
        "--data", str(data_dir),
        "--out", str(out_dir),
        "--project-dir", str(project_dir),
    ]

    use_setpriv = (os.name != "nt" and shutil.which("setpriv") is not None and hasattr(os, "getuid") and os.getuid() == 0)
    if use_setpriv:
        cmd = [
            "setpriv",
            "--reuid", "nobody",
            "--regid", "nogroup",
            "--clear-groups",
            "--no-new-privs",
        ] + cmd

    with open(stdout_path, "wb") as out_f, open(stderr_path, "wb") as err_f:
        proc = subprocess.Popen(
            cmd,
            stdout=out_f,
            stderr=err_f,
            start_new_session=(os.name != "nt"),
        )
        try:
            returncode = proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            proc.kill()
            proc.wait()
            raise RuntimeError(f"Runner timed out after 600 seconds on window {window}")

    stdout_text = stdout_path.read_text(errors="replace") if stdout_path.exists() else ""
    stderr_text = stderr_path.read_text(errors="replace") if stderr_path.exists() else ""

    try:
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)
    except Exception:
        pass

    if returncode != 0:
        raise RuntimeError(
            f"Runner exited with code {returncode} on window {window}.\n"
            f"STDOUT:\n{stdout_text}\nSTDERR:\n{stderr_text}"
        )

    return out_dir


def compare_mart_files(mart_name: str, actual_path: Path, expected_path: Path) -> list:
    return compare_mart(mart_name, actual_path, expected_path)

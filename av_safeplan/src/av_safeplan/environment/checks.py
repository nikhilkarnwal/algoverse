"""Composable environment checks with no eager heavy-framework imports."""

from dataclasses import asdict, dataclass
import importlib
from importlib import metadata
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional

from av_safeplan.settings import StackSettings


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _module_version(module: Any) -> Optional[str]:
    return getattr(module, "__version__", None)


def check_python(expected: str) -> CheckResult:
    actual = ".".join(str(part) for part in sys.version_info[:3])
    return CheckResult(
        "python",
        "pass" if actual == expected else "fail",
        "expected {}, found {}".format(expected, actual),
    )


def check_module(
    name: str,
    expected: Optional[str],
    required: bool = True,
    distribution: Optional[str] = None,
) -> CheckResult:
    try:
        module = importlib.import_module(name)
    except Exception as error:
        return CheckResult(name, "fail" if required else "warn", str(error), required)

    actual = _module_version(module)
    if actual is None and distribution:
        try:
            actual = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            actual = None
    if expected is None:
        return CheckResult(name, "pass", "imported successfully", required)
    return CheckResult(
        name,
        "pass" if actual == expected else "fail",
        "expected {}, found {}".format(expected, actual or "unknown"),
        required,
    )


def check_path(name: str, path: Optional[Path], required: bool = True) -> CheckResult:
    if path is None:
        return CheckResult(name, "fail" if required else "warn", "path is not configured", required)
    if not path.exists():
        return CheckResult(
            name, "fail" if required else "warn", "{} does not exist".format(path), required
        )
    return CheckResult(name, "pass", str(path), required)


def check_checkpoint(path: Optional[Path], minimum_size: int) -> CheckResult:
    basic = check_path("simlingo_checkpoint", path)
    if basic.status != "pass" or path is None:
        return basic
    size = path.stat().st_size
    return CheckResult(
        "simlingo_checkpoint",
        "pass" if size >= minimum_size else "fail",
        "{} bytes at {} (minimum {})".format(size, path, minimum_size),
    )


def check_git_revision(root: Optional[Path], expected: str) -> CheckResult:
    if root is None or not root.exists():
        return CheckResult("simlingo_revision", "fail", "SIMLINGO_ROOT is unavailable")
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        actual = completed.stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        return CheckResult("simlingo_revision", "fail", str(error))
    return CheckResult(
        "simlingo_revision",
        "pass" if actual == expected else "fail",
        "expected {}, found {}".format(expected, actual),
    )


def check_carla_agents() -> CheckResult:
    try:
        importlib.import_module("agents.navigation.behavior_agent")
    except Exception as error:
        return CheckResult("carla_behavior_agent", "fail", str(error))
    return CheckResult("carla_behavior_agent", "pass", "imported successfully")


def check_cuda(required: bool) -> CheckResult:
    try:
        torch = importlib.import_module("torch")
        available = bool(torch.cuda.is_available())
        device = torch.cuda.get_device_name(0) if available else "none"
    except Exception as error:
        return CheckResult("cuda", "fail" if required else "warn", str(error), required)
    return CheckResult(
        "cuda",
        "pass" if available else ("fail" if required else "warn"),
        "available={}, device={}".format(available, device),
        required,
    )


def apply_python_paths(settings: StackSettings) -> None:
    """Expose external CARLA and SimLingo modules to the current process."""
    candidates = []
    if settings.carla_root:
        candidates.append(settings.carla_root / "PythonAPI" / "carla")
    if settings.simlingo.root:
        candidates.extend([
            settings.simlingo.root,
            settings.simlingo.root / "scenario_runner",
            settings.simlingo.root / "leaderboard",
        ])
    for candidate in reversed(candidates):
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    os.environ["PYTHONPATH"] = os.pathsep.join(sys.path)


def run_offline_checks(settings: StackSettings) -> List[CheckResult]:
    apply_python_paths(settings)
    return [
        check_python(settings.runtime.python),
        check_module("yaml", "6.0.1", distribution="PyYAML"),
        check_module("torch", settings.runtime.torch, distribution="torch"),
        check_module("torchvision", settings.runtime.torchvision, distribution="torchvision"),
        check_module("transformers", settings.runtime.transformers, distribution="transformers"),
        check_module("flash_attn", settings.runtime.flash_attn, distribution="flash-attn"),
        check_module("carla", settings.carla.version, distribution="carla"),
        check_carla_agents(),
        check_cuda(settings.runtime.cuda_required),
        check_path("carla_root", settings.carla_root),
        check_path("simlingo_root", settings.simlingo.root),
        check_git_revision(settings.simlingo.root, settings.simlingo.revision),
        check_checkpoint(
            settings.simlingo.checkpoint,
            settings.simlingo.checkpoint_spec.minimum_size_bytes,
        ),
        check_path("huggingface_cache", settings.model_cache, required=False),
    ]

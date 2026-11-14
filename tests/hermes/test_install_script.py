"""The Hermes installer must target the environment Hermes actually runs.

Two regressions are pinned here, both of which shipped in 0.3.4 and made
``hermes/install.sh`` fail on every git-checkout Hermes:

1. The capability probe imported ``agent.memory_provider`` from a bare
   interpreter. A git checkout only exposes ``agent`` because the ``hermes``
   launcher inserts it, so the probe died with ``ModuleNotFoundError``.
2. The bridge was installed with a plain ``pip install``. Hermes launches with
   ``-I`` and activates a managed environment, so a package in the base
   interpreter or the user site is invisible to the host and the provider never
   loaded even when the install "succeeded".

The probes live in ``hermes/probes`` so they can be exercised directly instead of
being re-parsed out of a shell heredoc.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PY = REPO_ROOT / "hermes" / "probes" / "runtime_python.py"
PROBE_PY = REPO_ROOT / "hermes" / "probes" / "capability_probe.py"
INSTALL_SH = REPO_ROOT / "hermes" / "install.sh"

CONTRACT_STUB = '''
class MemoryProvider:
    name = "stub"
    is_available = True

    def initialize(self, *args, **kwargs):
        return None

    def get_tool_schemas(self):
        return []
'''


def _run(
    script: Path,
    *,
    env: dict[str, str],
    flags: tuple[str, ...] = ("-I",),
    args: tuple[str, ...] = (),
):
    return subprocess.run(
        [sys.executable, *flags, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def _base_env(**overrides: str) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "HERMES_BIN": "/nonexistent/hermes",
    }
    env.update(overrides)
    return env


def _make_checkout(root: Path, *, with_agent: bool = True) -> Path:
    """Build a git-checkout-shaped Hermes tree under ``root``."""
    checkout = root / "hermes-agent"
    checkout.mkdir(parents=True)
    (checkout / "hermes_bootstrap.py").write_text("", encoding="utf-8")
    if with_agent:
        agent = checkout / "agent"
        agent.mkdir()
        (agent / "__init__.py").write_text("", encoding="utf-8")
        (agent / "memory_provider.py").write_text(CONTRACT_STUB, encoding="utf-8")
    return checkout


def _venv_site_packages(venv: Path) -> Path:
    """The site-packages path this interpreter version would use inside ``venv``."""
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return venv / "lib" / version / "site-packages"


def _make_venv(root: Path) -> Path:
    """Build a venv-shaped directory whose python is this interpreter."""
    venv = root / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (venv / "bin" / "python").symlink_to(sys.executable)
    _venv_site_packages(venv).mkdir(parents=True, exist_ok=True)
    return venv


def _bootstrap_adding(checkout: Path, site_packages: Path) -> None:
    """Point the checkout's bootstrap at a specific site-packages directory."""
    (checkout / "hermes_bootstrap.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(site_packages)!r})\n",
        encoding="utf-8",
    )


def test_runtime_python_resolves_the_activated_environment(tmp_path):
    """A managed environment is found through the checkout's bootstrap."""
    checkout = _make_checkout(tmp_path)
    venv = _make_venv(tmp_path)
    site_packages = _venv_site_packages(venv)
    _bootstrap_adding(checkout, site_packages)

    result = _run(RUNTIME_PY, env=_base_env(HERMES_HOME=str(tmp_path)))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(venv / "bin" / "python")


def test_runtime_python_skips_a_site_packages_without_a_venv(tmp_path):
    """A bare site-packages is not an environment; only a pyvenv.cfg root counts."""
    checkout = _make_checkout(tmp_path)
    plain = tmp_path / "plain" / "site-packages"
    plain.mkdir(parents=True)
    _bootstrap_adding(checkout, plain)

    result = _run(RUNTIME_PY, env=_base_env(HERMES_HOME=str(tmp_path)))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_runtime_python_skips_its_own_environment(tmp_path):
    """The interpreter running the probe is never the answer, even inside a venv."""
    checkout = _make_checkout(tmp_path)
    own_site = Path(sys.prefix).resolve() / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if not own_site.is_dir():
        pytest.skip("this interpreter has no venv site-packages to shadow")
    _bootstrap_adding(checkout, own_site)

    result = _run(RUNTIME_PY, env=_base_env(HERMES_HOME=str(tmp_path)))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_runtime_python_prints_nothing_without_a_hermes_install(tmp_path):
    """No checkout means no answer, and the installer falls back to its own interpreter."""
    result = _run(RUNTIME_PY, env=_base_env(HERMES_HOME=str(tmp_path)))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_capability_probe_finds_agent_in_a_git_checkout(tmp_path):
    """The probe must import ``agent`` from the checkout, not from site-packages."""
    _make_checkout(tmp_path)

    result = _run(PROBE_PY, env=_base_env(HERMES_HOME=str(tmp_path)))

    assert result.returncode == 0, result.stderr


def test_capability_probe_reports_an_unimportable_agent(tmp_path):
    """A checkout without ``agent`` fails with an actionable message, not a traceback."""
    _make_checkout(tmp_path, with_agent=False)

    result = _run(PROBE_PY, env=_base_env(HERMES_HOME=str(tmp_path)))

    assert result.returncode == 1
    assert "agent package is not importable" in result.stderr
    assert "Traceback" not in result.stderr


def test_capability_probe_reports_an_incomplete_contract(tmp_path):
    """A host that exposes ``MemoryProvider`` without the required hooks is rejected."""
    checkout = _make_checkout(tmp_path)
    (checkout / "agent" / "memory_provider.py").write_text(
        "class MemoryProvider:\n    name = 'stub'\n", encoding="utf-8"
    )

    result = _run(PROBE_PY, env=_base_env(HERMES_HOME=str(tmp_path)))

    assert result.returncode == 1
    assert "MemoryProvider contract is missing" in result.stderr


def test_capability_probe_rejects_a_user_site_only_install(tmp_path):
    """Under -I the user site is invisible, so a --user install must not pass."""
    _make_checkout(tmp_path)

    result = _run(PROBE_PY, env=_base_env(HERMES_HOME=str(tmp_path)), flags=("-I", "-S"))

    assert result.returncode == 1
    assert "entry point is not visible" in result.stderr


def test_runtime_python_reports_the_site_packages(tmp_path):
    """The installer needs the directory for its last-resort install path."""
    checkout = _make_checkout(tmp_path)
    venv = _make_venv(tmp_path)
    site_packages = _venv_site_packages(venv)
    _bootstrap_adding(checkout, site_packages)

    result = _run(
        RUNTIME_PY, env=_base_env(HERMES_HOME=str(tmp_path)), args=("--site-packages",)
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(site_packages)


def test_capability_probe_accepts_a_pip_installed_hermes(tmp_path):
    """A pip-installed Hermes has ``agent`` in site-packages, with no checkout to find."""
    venv = _make_venv(tmp_path)
    site_packages = _venv_site_packages(venv)
    agent = site_packages / "agent"
    agent.mkdir(parents=True)
    (agent / "__init__.py").write_text("", encoding="utf-8")
    (agent / "memory_provider.py").write_text(CONTRACT_STUB, encoding="utf-8")

    # Make the luminary entry point visible the way a real install would.
    source_site = Path(sys.prefix).resolve() / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    dist_info = next(source_site.glob("luminary_memory-*.dist-info"), None)
    if dist_info is None:
        pytest.skip("the test environment has no luminary dist-info to mirror")
    (site_packages / dist_info.name).symlink_to(dist_info)
    (site_packages / "_luminary_src.pth").write_text(
        str(REPO_ROOT / "src") + "\n", encoding="utf-8"
    )

    result = subprocess.run(
        [str(venv / "bin" / "python"), "-I", str(PROBE_PY)],
        check=False,
        capture_output=True,
        text=True,
        env=_base_env(HERMES_HOME=str(tmp_path)),
        timeout=120,
    )

    assert result.returncode == 0, result.stderr


def test_install_script_uses_the_extracted_probes():
    """The installer must call the probes instead of inlining a bare import."""
    script = INSTALL_SH.read_text(encoding="utf-8")

    assert "hermes/probes/runtime_python.py" in script
    assert "hermes/probes/capability_probe.py" in script
    # The original defect: importing the contract from an unqualified interpreter.
    assert "from agent.memory_provider import" not in script
    # The install must target the resolved environment, never the bare one.
    assert 'pip --python "$HERMES_RUNTIME_PYTHON"' in script


def test_install_script_has_install_fallbacks():
    """A host whose pip predates ``--python`` must still get a working install."""
    script = INSTALL_SH.read_text(encoding="utf-8")

    assert '--target "$HERMES_RUNTIME_SITE"' in script
    assert '"$HERMES_RUNTIME_PYTHON" -m pip install' in script


def test_install_script_backs_up_the_config_before_activation():
    """Activation rewrites an operator-owned file, so it must be recoverable."""
    script = INSTALL_SH.read_text(encoding="utf-8")

    assert "CONFIG_BACKUP=" in script
    assert 'cp "$CONFIG" "$CONFIG_BACKUP"' in script
    # The backup has to happen before the activation call, not after it.
    assert script.index("CONFIG_BACKUP=") < script.index("-m luminary_memory.hermes.activation")


def test_install_script_refuses_activation_without_the_module():
    """A bridge too old to activate must fail before the config is touched."""
    script = INSTALL_SH.read_text(encoding="utf-8")

    assert "import luminary_memory.hermes.activation" in script


def test_install_script_fails_cleanly_without_a_hermes_install(tmp_path):
    """No Hermes means one actionable line, not a traceback and not a half-config."""
    config = tmp_path / "config.yaml"
    original = "memory:\n  memory_enabled: true\n  user_profile_enabled: true\n  provider: ''\n"
    config.write_text(original, encoding="utf-8")

    env = _base_env(HERMES_HOME=str(tmp_path), HERMES_PYTHON=sys.executable)
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--no-hook", "--no-skill"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )

    assert result.returncode == 1
    assert "ERROR:" in result.stderr
    assert "Traceback" not in result.stderr
    # A failed install must leave the operator's config exactly as it was.
    assert config.read_text(encoding="utf-8") == original


def test_install_script_is_syntactically_valid():
    """A shell syntax error would only surface on a user's machine."""
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)], check=False, capture_output=True, text=True, timeout=60
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", [RUNTIME_PY, PROBE_PY])
def test_probes_are_importable_modules(script):
    """Both probes must stay importable so the tests can call them directly."""
    result = subprocess.run(
        [sys.executable, "-c", f"import runpy; runpy.run_path({str(script)!r}, run_name='probe')"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr

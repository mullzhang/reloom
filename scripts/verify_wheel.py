"""Build an sdist and wheels; test installed artifacts outside the checkout."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd, env):
    result = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode:
        print(result.stdout, file=sys.stderr)
        result.check_returncode()
    return result.stdout


def payload(wheel):
    with zipfile.ZipFile(wheel) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def python_path(venv):
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--relindex-source", type=Path, help="Read the pinned commit from this local Git repository"
    )
    args = parser.parse_args()
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    versions = {p["name"]: p["version"] for p in lock["package"]}
    dependency = config["tool"]["uv"]["sources"]["relindex"]
    env = {
        key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME")
    }
    artifacts = ROOT / "dist"
    artifacts.mkdir(exist_ok=True)
    run("uv", "build", "--out-dir", artifacts, ROOT, cwd=ROOT, env=env)
    package_version = config["project"]["version"]
    wheel = artifacts / f"reloom-{package_version}-py3-none-any.whl"
    sdist = artifacts / f"reloom-{package_version}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="reloom-wheel-") as folder:
        work = Path(folder).resolve()
        rebuilt = work / "rebuilt"
        run("uv", "build", sdist, "--wheel", "--out-dir", rebuilt, cwd=work, env=env)
        assert payload(wheel) == payload(rebuilt / wheel.name), "sdist and source wheels differ"
        files = payload(wheel)
        assert "reloom/py.typed" in files
        assert not any(
            n.startswith(("tests/", "examples/", "relindex_ports_prototype/")) for n in files
        )
        print("Source wheel and sdist-rebuilt wheel match", flush=True)

        source = args.relindex_source.resolve() if args.relindex_source else work / "relindex-git"
        if args.relindex_source is None:
            run("git", "clone", "--no-checkout", dependency["git"], source, cwd=work, env=env)
        archive = work / "relindex.tar"
        # Archive the pinned commit, never build in or modify the user's dependency checkout.
        run(
            "git",
            "-C",
            source,
            "archive",
            "--format=tar",
            f"--output={archive}",
            dependency["rev"],
            cwd=work,
            env=env,
        )
        unpacked = work / "relindex-source"
        unpacked.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(unpacked, filter="data")
        dep_dist = artifacts / "dependencies"
        run("uv", "build", unpacked, "--wheel", "--out-dir", dep_dist, cwd=work, env=env)
        dependency_version = tomllib.loads((unpacked / "pyproject.toml").read_text())["project"][
            "version"
        ]
        relindex_wheel = dep_dist / f"relindex-{dependency_version}-py3-none-any.whl"

        test_dir = work / "checks"
        shutil.copytree(
            ROOT / "tests", test_dir / "tests", ignore=shutil.ignore_patterns("__pycache__")
        )
        shutil.copytree(
            ROOT / "examples", test_dir / "examples", ignore=shutil.ignore_patterns("__pycache__")
        )
        shutil.copy2(ROOT / "pyproject.toml", test_dir / "pyproject.toml")
        pytest_requirement = f"pytest=={versions['pytest']}"
        core = work / "core"
        run("uv", "venv", "--python", args.python, core, cwd=work, env=env)
        core_python = python_path(core)
        run(
            "uv",
            "pip",
            "install",
            "--python",
            core_python,
            wheel,
            relindex_wheel,
            pytest_requirement,
            cwd=work,
            env=env,
        )
        core_check = f"""
import importlib.util
import pathlib
import reloom
assert not pathlib.Path(reloom.__file__).resolve().is_relative_to({str(ROOT)!r})
for name in ('pyomo', 'pulp', 'highspy', 'numpy'):
    assert importlib.util.find_spec(name) is None, name
"""
        run(core_python, "-I", "-c", core_check, cwd=work, env=env)
        print(
            run(
                core_python,
                "-m",
                "pytest",
                "-q",
                "--import-mode=importlib",
                "tests/test_contracts.py",
                "tests/test_assembly.py",
                cwd=test_dir,
                env=env,
            ),
            flush=True,
        )

        backend = work / "backend"
        run("uv", "venv", "--python", args.python, backend, cwd=work, env=env)
        backend_python = python_path(backend)
        run(
            "uv",
            "pip",
            "install",
            "--python",
            backend_python,
            f"{wheel}[pyomo]",
            relindex_wheel,
            pytest_requirement,
            *config["dependency-groups"]["solver"],
            cwd=work,
            env=env,
        )
        run(
            backend_python,
            "-I",
            "-c",
            (
                f"import pathlib,reloom; assert not pathlib.Path(reloom.__file__).resolve()"
                f".is_relative_to({str(ROOT)!r})"
            ),
            cwd=work,
            env=env,
        )
        print(
            run(
                backend_python,
                "-m",
                "pytest",
                "-q",
                "--import-mode=importlib",
                "tests",
                cwd=test_dir,
                env=env,
            ),
            flush=True,
        )
        for scenario, expected in (("normal", 26), ("unreachable", None), ("stock", 14)):
            output = run(
                backend_python,
                "-I",
                test_dir / "examples/supply_chain.py",
                "--scenario",
                scenario,
                cwd=work,
                env=env,
            )
            result = json.loads(output)
            assert result["termination"] == ("infeasible" if expected is None else "optimal")
            assert result.get("objective") == expected
        result = json.loads(
            run(backend_python, "-I", test_dir / "examples/network.py", cwd=work, env=env)
        )
        assert result["objective"] == 9 and result["constant_true"] == 1
        runtime = run(backend_python, "--version", cwd=work, env=env).strip()
        print(f"{runtime}: isolated core, full test suite, and four standalone examples passed")
        print(f"Verified wheel: {wheel}")


if __name__ == "__main__":
    main()

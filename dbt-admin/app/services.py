from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Job, JobStatus, JobType, Project
from .db import DATA_DIR, get_session

ENVS_DIR = DATA_DIR / "envs"
ENVS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_LOGS_DIR = DATA_DIR / "job_logs"
JOBS_LOGS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def get_project_env_dir(project_id: int) -> Path:
    return ENVS_DIR / f"project_{project_id}"


def get_env_python_bin(env_dir: Path) -> Path:
    # Linux path
    python_bin = env_dir / "bin" / "python"
    return python_bin


def get_env_pip_bin(env_dir: Path) -> Path:
    pip_bin = env_dir / "bin" / "pip"
    return pip_bin


def _create_env_with_virtualenv(env_dir: Path) -> bool:
    try:
        proc = subprocess.run(["python3", "-m", "virtualenv", str(env_dir)], capture_output=True, text=True)
        return proc.returncode == 0
    except Exception:
        return False


def _create_env_with_venv(env_dir: Path) -> bool:
    try:
        proc = subprocess.run(["python3", "-m", "venv", str(env_dir)], capture_output=True, text=True)
        return proc.returncode == 0
    except Exception:
        return False


def ensure_env(project: Project) -> Tuple[Path, Path, Path]:
    env_dir = get_project_env_dir(project.id)  # type: ignore[arg-type]
    env_dir.mkdir(parents=True, exist_ok=True)

    python_bin = get_env_python_bin(env_dir)
    pip_bin = get_env_pip_bin(env_dir)

    if not python_bin.exists():
        created = _create_env_with_virtualenv(env_dir)
        if not created:
            created = _create_env_with_venv(env_dir)
        if not created:
            raise RuntimeError("Failed to create a virtual environment. Ensure 'virtualenv' or 'venv' is available.")

    # Ensure pip is up to date (best-effort)
    subprocess.run([str(pip_bin), "install", "--upgrade", "pip", "setuptools", "wheel"], check=False)

    return env_dir, python_bin, pip_bin


def install_dbt_for_project(project: Project) -> CommandResult:
    env_dir, _python_bin, pip_bin = ensure_env(project)

    packages: List[str] = [f"dbt-core=={project.dbt_version}"]
    if project.extra_packages:
        packages.extend([pkg.strip() for pkg in project.extra_packages.split(",") if pkg.strip()])

    proc = subprocess.run([str(pip_bin), "install", *packages], capture_output=True, text=True)
    return CommandResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def run_dbt_parse(project: Project) -> CommandResult:
    env_dir = get_project_env_dir(project.id)  # type: ignore[arg-type]
    dbt_bin = env_dir / "bin" / "dbt"
    # Fallback: Some envs may only have module entrypoint
    if not dbt_bin.exists():
        cmd = [str(get_env_python_bin(env_dir)), "-m", "dbt", "parse", "--project-dir", project.root_path]
    else:
        cmd = [str(dbt_bin), "parse", "--project-dir", project.root_path]

    if project.profiles_dir:
        cmd += ["--profiles-dir", project.profiles_dir]

    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=project.root_path)
    return CommandResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def compute_stats_from_manifest(project: Project) -> Dict[str, int]:
    manifest_path = Path(project.root_path) / "target" / "manifest.json"
    if not manifest_path.exists():
        return {}

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    nodes = manifest.get("nodes", {})
    exposures = manifest.get("exposures", {})
    metrics = manifest.get("metrics", {}) or {}

    stats = {
        "models": 0,
        "tests": 0,
        "snapshots": 0,
        "analyses": 0,
        "seeds": 0,
        "sources": 0,
        "macros": len(manifest.get("macros", {})),
        "exposures": len(exposures),
        "metrics": len(metrics),
        "packages": len(manifest.get("metadata", {}).get("dependencies", [])),
    }

    for node in nodes.values():
        resource_type = node.get("resource_type")
        if resource_type == "model":
            stats["models"] += 1
        elif resource_type == "test":
            stats["tests"] += 1
        elif resource_type == "snapshot":
            stats["snapshots"] += 1
        elif resource_type == "analysis":
            stats["analyses"] += 1
        elif resource_type == "seed":
            stats["seeds"] += 1
        elif resource_type == "source":
            stats["sources"] += 1

    return stats


def create_job(project: Project, job_type: JobType) -> Job:
    log_file = JOBS_LOGS_DIR / f"job_{project.id}_{job_type.value}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.log"
    job = Job(project_id=project.id, job_type=job_type, status=JobStatus.PENDING, log_path=str(log_file))
    with get_session() as session:
        session.add(job)
        session.flush()
        session.refresh(job)
    return job


def run_job(job: Job, project: Project) -> None:
    with get_session() as session:
        job.started_at = datetime.utcnow()
        job.status = JobStatus.RUNNING
        session.add(job)

    def write_log(text: str) -> None:
        if job.log_path:
            with open(job.log_path, "a", encoding="utf-8") as lf:
                lf.write(text)

    try:
        if job.job_type == JobType.INSTALL:
            write_log(f"Installing packages for project {project.name}...\n")
            res = install_dbt_for_project(project)
            write_log(res.stdout)
            if res.stderr:
                write_log("\n[stderr]\n" + res.stderr)
            success = res.returncode == 0
        elif job.job_type == JobType.EVALUATE:
            write_log(f"Running dbt parse for project {project.name}...\n")
            res = run_dbt_parse(project)
            write_log(res.stdout)
            if res.stderr:
                write_log("\n[stderr]\n" + res.stderr)
            success = res.returncode == 0
        else:
            write_log("Unknown job type\n")
            success = False

        with get_session() as session2:
            job.status = JobStatus.SUCCESS if success else JobStatus.FAILED
            job.finished_at = datetime.utcnow()
            if not success:
                job.error_message = "Job failed. See logs."
            session2.add(job)
    except Exception as exc:  # noqa: BLE001
        write_log(f"Exception: {exc}\n")
        with get_session() as session3:
            job.status = JobStatus.FAILED
            job.finished_at = datetime.utcnow()
            job.error_message = str(exc)
            session3.add(job)
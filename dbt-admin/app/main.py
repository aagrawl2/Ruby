from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from types import SimpleNamespace

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import init_db, get_session
from .models import Job, JobStatus, JobType, Project
from .services import compute_stats_from_manifest, create_job, run_job

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="DBT Admin UI")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):  # type: ignore[no-untyped-def]
    with get_session() as session:
        projects = session.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse("home.html", {"request": request, "projects": projects})


@app.get("/projects/new", response_class=HTMLResponse)
def new_project(request: Request):  # type: ignore[no-untyped-def]
    return templates.TemplateResponse("new_project.html", {"request": request})


@app.post("/projects")
def create_project(  # type: ignore[no-untyped-def]
    name: str = Form(...),
    root_path: str = Form(...),
    dbt_version: str = Form(...),
    profiles_dir: Optional[str] = Form(None),
    extra_packages: Optional[str] = Form(None),
):
    project = Project(
        name=name,
        root_path=root_path,
        dbt_version=dbt_version,
        profiles_dir=profiles_dir,
        extra_packages=extra_packages,
        updated_at=datetime.utcnow(),
    )
    with get_session() as session:
        session.add(project)
        session.flush()
        session.refresh(project)
    return RedirectResponse(url=f"/projects/{project.id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def show_project(request: Request, project_id: int):  # type: ignore[no-untyped-def]
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        jobs = session.query(Job).filter(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(20).all()
    stats = compute_stats_from_manifest(project)
    return templates.TemplateResponse("project_detail.html", {"request": request, "project": project, "jobs": jobs, "stats": stats})


@app.post("/projects/{project_id}/update")
def update_project(  # type: ignore[no-untyped-def]
    project_id: int,
    name: str = Form(...),
    root_path: str = Form(...),
    dbt_version: str = Form(...),
    profiles_dir: Optional[str] = Form(None),
    extra_packages: Optional[str] = Form(None),
):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project.name = name
        project.root_path = root_path
        project.dbt_version = dbt_version
        project.profiles_dir = profiles_dir
        project.extra_packages = extra_packages
        project.updated_at = datetime.utcnow()
        session.add(project)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/delete")
def delete_project(project_id: int):  # type: ignore[no-untyped-def]
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        session.delete(project)
    return RedirectResponse(url="/", status_code=303)


@app.post("/projects/{project_id}/install")
def install_project_env(project_id: int):  # type: ignore[no-untyped-def]
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
    job = create_job(project, JobType.INSTALL)
    thread = threading.Thread(target=run_job, args=(job, project), daemon=True)
    thread.start()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/evaluate")
def evaluate_project(project_id: int):  # type: ignore[no-untyped-def]
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
    job = create_job(project, JobType.EVALUATE)
    thread = threading.Thread(target=run_job, args=(job, project), daemon=True)
    thread.start()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.get("/jobs/{job_id}/logs")
def get_job_logs(job_id: int):  # type: ignore[no-untyped-def]
    with get_session() as session:
        job = session.get(Job, job_id)
        if not job or not job.log_path:
            raise HTTPException(status_code=404, detail="Logs not found")
        log_path = Path(job.log_path)
        if not log_path.exists():
            raise HTTPException(status_code=404, detail="Logs not found")
    return FileResponse(path=str(log_path), media_type="text/plain")


# Preview routes with mock data
@app.get("/preview", response_class=HTMLResponse)
def preview_home(request: Request):  # type: ignore[no-untyped-def]
    projects = [
        SimpleNamespace(id=1, name="Marketing Warehouse", dbt_version="1.8.6", root_path="/srv/dbt/marketing"),
        SimpleNamespace(id=2, name="Finance Lakehouse", dbt_version="1.7.13", root_path="/srv/dbt/finance"),
    ]
    return templates.TemplateResponse("home.html", {"request": request, "projects": projects})


@app.get("/preview/projects/{project_id}", response_class=HTMLResponse)
def preview_project(request: Request, project_id: int):  # type: ignore[no-untyped-def]
    project = SimpleNamespace(
        id=project_id,
        name="Marketing Warehouse" if project_id == 1 else "Finance Lakehouse",
        root_path="/srv/dbt/marketing" if project_id == 1 else "/srv/dbt/finance",
        dbt_version="1.8.6" if project_id == 1 else "1.7.13",
        profiles_dir="/home/app/.dbt",
        extra_packages="dbt-postgres==1.8.6, dbt-redshift==1.8.6",
    )
    now = datetime.utcnow()
    jobs = [
        SimpleNamespace(id=301, project_id=project_id, job_type="install", status="success", started_at=now - timedelta(hours=6), finished_at=now - timedelta(hours=6, minutes=2), log_path=None),
        SimpleNamespace(id=302, project_id=project_id, job_type="evaluate", status="success", started_at=now - timedelta(hours=5), finished_at=now - timedelta(hours=5, minutes=1), log_path=None),
        SimpleNamespace(id=303, project_id=project_id, job_type="evaluate", status="failed", started_at=now - timedelta(hours=3), finished_at=now - timedelta(hours=3, minutes=1), log_path=None),
        SimpleNamespace(id=304, project_id=project_id, job_type="evaluate", status="running", started_at=now - timedelta(minutes=10), finished_at=None, log_path=None),
    ]
    stats = {
        "models": 128,
        "tests": 420,
        "snapshots": 6,
        "analyses": 4,
        "seeds": 12,
        "sources": 23,
        "macros": 37,
        "exposures": 5,
        "metrics": 9,
        "packages": 3,
    }
    return templates.TemplateResponse("project_detail.html", {"request": request, "project": project, "jobs": jobs, "stats": stats})
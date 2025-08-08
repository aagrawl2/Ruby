# DBT Admin UI

A lightweight FastAPI app to manage multiple dbt Core projects in a mesh environment.

## Features
- Per-project dbt-core version via isolated venvs
- Project registry with root path, profiles dir, and extra adapter packages
- Install/Update dbt for a project
- Evaluate project (dbt parse) and read `manifest.json` for stats
- Simple job history with logs

## Quickstart

```bash
cd /workspace/dbt-admin
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 and create your first project.

Notes:
- Use absolute paths for `root_path` and `profiles_dir`.
- Add adapter packages (e.g., `dbt-postgres==1.8.1`) in Extra Packages.
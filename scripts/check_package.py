"""Check runtime resources in the installed package (also works after wheel installation)."""
from importlib.resources import files
from pathlib import Path

root = files('se_team')
for resource in ('crew/agents.yaml','crew/tasks.yaml','office/static/index.html',
                 'office/static/app.js','office/static/style.css','office/static/mark.svg'):
    if not root.joinpath(resource).is_file():
        raise SystemExit(f'Missing package resource: {resource}')
print('Installed package contains all runtime YAML and Office assets')

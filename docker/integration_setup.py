"""Initialize a new isolated CLI workdir, never an existing project."""
from pathlib import Path
import re
import shutil
import sys

project = sys.argv[1]
if not re.fullmatch(r"agrifos-it-[a-f0-9]{8}", project):
    raise SystemExit("Invalid test project name")
target = Path("/output") / "supabase"
target.mkdir(exist_ok=False)
config = Path("/source/supabase/config.toml").read_text(encoding="utf-8")
config = config.replace('project_id = "agrifos"', f'project_id = "{project}"')
for old, new in ((54321, 54331), (54322, 54332), (54323, 54333), (54324, 54334), (54320, 54330)):
    config = config.replace(str(old), str(new))
(target / "config.toml").write_text(config, encoding="utf-8", newline="\n")
shutil.copytree("/source/supabase/templates", target / "templates")
Path("/output/evidence").mkdir()

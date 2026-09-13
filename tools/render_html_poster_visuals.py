#!/usr/bin/env python3
"""Render the generated HTML poster infographics with Windows Chrome."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dist" / "poster_html_visuals_2026-08-28"
WINDOWS_ROOT = Path("/mnt/c/Users/Jio/Downloads/auto_titration")
WINDOWS_OUT = WINDOWS_ROOT / "dist" / "poster_html_visuals_2026-08-28"
PS_SCRIPT = Path("/mnt/c/Users/Jio/AppData/Local/Temp/render_poster_html_visuals.ps1")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    html_files = sorted(SOURCE.glob("*.html"))
    if not html_files:
        raise SystemExit("no HTML visuals found; run build_html_poster_visuals.py first")
    WINDOWS_OUT.mkdir(parents=True, exist_ok=True)

    jobs: list[dict[str, str]] = []
    for index, html in enumerate(html_files, start=1):
        alias = f"poster-{index:02d}"
        windows_html = WINDOWS_OUT / f"{alias}.html"
        shutil.copy2(html, windows_html)
        jobs.append(
            {
                "source_name": html.stem,
                "alias": alias,
                "windows_html": str(windows_html).replace("/mnt/c", "C:").replace("/", "\\"),
                "windows_png": str((WINDOWS_OUT / f"{alias}.png")).replace("/mnt/c", "C:").replace("/", "\\"),
            }
        )

    jobs_json = json.dumps(jobs, ensure_ascii=False).replace("'", "''")
    script = f"""$ErrorActionPreference='Stop'
$chrome='C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
$jobs=ConvertFrom-Json @'
{jobs_json}
'@
foreach($job in $jobs){{
  if(Test-Path $job.windows_png){{Remove-Item $job.windows_png -Force}}
  $profile="C:\\Users\\Jio\\AppData\\Local\\Temp\\chrome-poster-"+$job.alias
  $uri='file:///'+($job.windows_html -replace '\\\\','/')
  $args=@('--headless=new','--disable-gpu','--hide-scrollbars','--allow-file-access-from-files','--force-device-scale-factor=2','--window-size=1600,760',"--user-data-dir=$profile","--screenshot=$($job.windows_png)",$uri)
  $p=Start-Process -FilePath $chrome -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
  if(-not(Test-Path $job.windows_png)){{throw "Screenshot missing: $($job.source_name), exit=$($p.ExitCode)"}}
}}
"""
    PS_SCRIPT.write_text(script, encoding="utf-8-sig")
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\Users\\Jio\\AppData\\Local\\Temp\\render_poster_html_visuals.ps1"],
        check=True,
    )

    manifest = []
    for job in jobs:
        source_name = job["source_name"]
        source_png = WINDOWS_OUT / f"{job['alias']}.png"
        local_png = SOURCE / f"{source_name}.png"
        shutil.copy2(source_png, local_png)
        image = Image.open(local_png)
        if image.size != (3200, 1520):
            raise RuntimeError(f"unexpected screenshot size for {source_name}: {image.size}")
        image.save(local_png, dpi=(300, 300), optimize=True)
        shutil.copy2(local_png, WINDOWS_OUT / f"{source_name}.png")
        shutil.copy2(SOURCE / f"{source_name}.html", WINDOWS_OUT / f"{source_name}.html")
        manifest.append(
            {
                "name": source_name,
                "html": f"{source_name}.html",
                "png": f"{source_name}.png",
                "width": 3200,
                "height": 1520,
                "dpi": 300,
                "sha256": sha256(local_png),
            }
        )

    (SOURCE / "manifest.json").write_text(
        json.dumps({"visual_count": len(manifest), "visuals": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(SOURCE / "manifest.json", WINDOWS_OUT / "manifest.json")
    print(json.dumps({"rendered": len(manifest), "output": str(SOURCE)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

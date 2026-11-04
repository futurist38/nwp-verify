"""Copy platform assets without replacing the separately released energy editor."""
from pathlib import Path
import shutil

# tools/release_energy_editor.py publishes this bundle after browser validation.
# An hourly/daily runner may have checked out main before that release completed.
ENERGY_EDITOR_FILES = frozenset({
    'energy-radar-map.json', 'energy-weather.html', 'energy-weather.js',
    'energy-editor.css', 'inline-edit.js', 'energy-shared.js',
    'energy-shared-ui.js',
})


def copy_static_assets(source_dir, site_dir):
    source, target = Path(source_dir), Path(site_dir)
    target.mkdir(parents=True, exist_ok=True)
    for asset in source.iterdir():
        destination = target / asset.name
        if asset.name in ENERGY_EDITOR_FILES and destination.is_file():
            continue
        shutil.copy2(asset, destination)

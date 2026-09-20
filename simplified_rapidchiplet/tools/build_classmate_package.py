"""Build a small source+launcher ZIP; runtime downloads are never redistributed."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parent


def package_files():
    files = [REPO/'Start Chiplet Lab.cmd', REPO/'QUICK_START_zh-TW.md', REPO/'README.md', REPO/'.gitignore']
    names = ['gui.py','run.py','preference_dse.py','Start GUI.cmd','README.md','README_zh-TW.md',
             'GUI_GUIDE_zh-TW.md','PORTABLE_PACKAGE_zh-TW.md','PREFERENCE_BLOCK_DSE.md','.gitignore']
    files += [PROJECT/name for name in names]
    for directory, pattern in [('simple_rapidchiplet','*.py'),('gui','*'),('configs','*.json'),
                               ('tests','*.py'),('packaging','*'),('validation','*.json')]:
        files.extend(p for p in (PROJECT/directory).glob(pattern) if p.is_file())
    files.extend(PROJECT/'scripts'/name for name in ('bootstrap_windows.ps1','run_gui.ps1'))
    files.extend(PROJECT/'tools'/name for name in ('portable_smoke.py','build_classmate_package.py',
        'calibrate_models.py','calibrate_resnet50.py','record_gui_validation.py','validate_0917.py'))
    files.extend(PROJECT/name for name in ('0917_IMPLEMENTATION_REVIEW_zh-TW.md',
        'VALIDATION_0917_zh-TW.md','ASSUMPTIONS_AUDIT_20260920_zh-TW.md'))
    return sorted(set(files))


def main():
    target = REPO/'0920.zip'
    target.parent.mkdir(exist_ok=True)
    manifest = {}
    with ZipFile(target,'w',ZIP_DEFLATED,compresslevel=9) as archive:
        for file in package_files():
            relative = file.relative_to(REPO).as_posix()
            content = file.read_bytes()
            if file.suffix in ('.cmd','.ps1'):
                content=content.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            archive.writestr('0920/'+relative, content)
            manifest[relative]=hashlib.sha256(content).hexdigest()
        archive.writestr('0920/PACKAGE_MANIFEST.json',json.dumps(manifest,indent=2))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    print(target)
    print(f'{len(manifest)} files; {target.stat().st_size:,} bytes; SHA256 {digest}')


if __name__=='__main__':main()

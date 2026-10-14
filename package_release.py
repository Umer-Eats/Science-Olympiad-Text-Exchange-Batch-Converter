"""Create portable and source ZIPs without local PDFs, reviews or secrets."""
import shutil
import zipfile
from pathlib import Path
root=Path(__file__).resolve().parent
dist=root/'dist'/'Test Exchange Converter'
for name in ['README.md','requirements.txt','events.json','app.py','Start Converter.cmd','start-converter.sh','.gitignore']:
    shutil.copy2(root/name,dist/name)
for directory in ['converter','web']:
    shutil.copytree(root/directory,dist/directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(root/'inbox-example',dist/'inbox-example',dirs_exist_ok=True)
release=root/'releases';release.mkdir(exist_ok=True)
shutil.make_archive(str(release/'Test-Exchange-Converter-Windows-x64'),'zip',root/'dist','Test Exchange Converter')
with zipfile.ZipFile(release/'Test-Exchange-Converter-Source.zip','w',zipfile.ZIP_DEFLATED) as z:
    for name in ['app.py','build.py','package_release.py','import_akoizo.py','README.md','requirements.txt','events.json','Start Converter.cmd','start-converter.sh','.gitignore']:
        z.write(root/name,'Test Exchange Converter/'+name)
    for directory in ['converter','web','tests','inbox-example']:
        for p in (root/directory).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:z.write(p,'Test Exchange Converter/'+p.relative_to(root).as_posix())
print('Created releases: Windows portable and cross-platform source ZIPs.')

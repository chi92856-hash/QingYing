from pathlib import Path
import hashlib,json,zipfile,os
root=Path(__file__).resolve().parents[1]
app=root/'清影'
output=root/'release'/'清影新版便携包.zip'
exe_source=Path(os.environ.get('QINGYING_PACKAGE_EXE',str(app/'清影.exe'))) 
files=[exe_source,app/'使用说明.txt',app/'第三方组件.md']
for folder in ('_internal','第三方许可证'):
 files.extend(p for p in (app/folder).rglob('*') if p.is_file())
manifest=[]
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in sorted(files):
  name='清影新版/'+('清影.exe' if p==exe_source else p.relative_to(app).as_posix())
  z.write(p,name)
  manifest.append({'path':name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 z.writestr('清影新版/文件校验清单.json',json.dumps(manifest,ensure_ascii=False,indent=2))
with zipfile.ZipFile(output) as z:
 assert z.testzip() is None
 for m in manifest:
  assert hashlib.sha256(z.read(m['path'])).hexdigest()==m['sha256'],m['path']
 assert all(not any(x in m['path'].split('/') for x in ['collector_data','facebook_data','instagram_data','x_data','settings.json','pending_downloads.json']) for m in manifest)
(root/'release'/'清影新版便携包.zip.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n','utf-8')
print('PASS: package CRC and every file SHA256 verified; personal data excluded')
print('Files:',len(files),'ZIP MB:',round(output.stat().st_size/1024**2,1))


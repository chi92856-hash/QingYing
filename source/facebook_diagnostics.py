"""Explicit packaged-runtime acceptance check; reports no cookies or headers."""
import json
import threading
from pathlib import Path
from facebook_profile import FacebookArchive


def check(config_path):
    config=json.loads(config_path.read_text('utf-8'))
    service=FacebookArchive(Path(config['data_dir']),lambda *_:None,lambda *_:None)
    report={'saved':[],'skipped':0};cancel=threading.Event()
    folder=Path(config['folder']);folder.mkdir(parents=True,exist_ok=True)
    try:
        if config.get('scan_categories'):
            profile,found,warnings=service.scan(config['profile_url'],folder,cancel,categories=config['scan_categories'])
            report['identified_profile']=profile
            report['scan_categories']=config['scan_categories']
            report['discovered']=len(found)
            report['warnings']=warnings
            report['pending_kinds']=sorted({item['kind'] for item in service.history.pending(profile,folder,config['scan_categories'])})
            return
        if config.get('profile_url'):
            state=service.navigate(config['profile_url'],cancel)
            actual=service.identify(state,cancel)
            if actual!=config['profile']:raise ValueError('主页编号与验收目标不一致')
            report['identified_profile']=actual
        for item in config['items']:
            if service.history.completed(config['profile'],folder,item['id']):
                report['skipped']+=1;continue
            service.history.discover(config['profile'],folder,item)
            files=service.save_item(item,config['profile'],folder,cancel)
            service.history.mark(config['profile'],folder,item['id'],files)
            report['saved'].extend({'path':str(p),'bytes':p.stat().st_size} for p in files)
        report['remaining']=len(service.history.pending(config['profile'],folder))
    except Exception as e:
        report['error_type']=type(e).__name__;report['error']=str(e)[:1000]
    finally:
        service.browser.shutdown()
        config_path.with_suffix('.result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

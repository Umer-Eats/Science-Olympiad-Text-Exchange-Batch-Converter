"""One-time, read-only import from an existing Akoizo checkout. No credentials copied."""
import argparse
import collections
import json
from pathlib import Path
from converter.store import Store

def run(project,home):
    project=Path(project).resolve();store=Store(home)
    queue=json.loads((project/'output/practice-research/bulk/queue.json').read_text(encoding='utf-8'))
    index={p.stem:p for p in (project/'output/practice-research').rglob('*.pdf') if len(p.stem)==64}
    counts=collections.Counter()
    for item in queue:
        source={k:item.get(k) for k in ['id','sourceId','sourceUrl','division','eventId','competition','year','level','levelText']}
        source['assets']=[]
        for f in item.get('files',[]):
            role={'test':'test','answer_key':'key','images':'supplement','image':'supplement','answer_sheet':'supplement','stations':'supplement','notes':'supplement','other':'supplement'}.get(f.get('type'))
            if role is None:continue
            sha=f.get('sha256','');path=index.get(sha)
            if not path:
                candidate=item.get({'test':'paperPath','key':'keyPath','supplement':'contextPath'}[role])
                if candidate:
                    p=(project/candidate).resolve()
                    if p.is_relative_to(project) and p.is_file():path=p
            try:
                if not path:raise ValueError('Not downloaded')
                asset=store.add_asset(path,role,f['name'],expected=sha or None);counts['copied_assets']+=1
            except (ValueError,OSError):
                asset=dict(role=role,name=f['name'],sha256=sha,path=None);counts['missing_assets']+=1
            source['assets'].append(asset)
        store.enqueue(source);counts['jobs']+=1
    print(json.dumps(dict(counts),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('project',type=Path);parser.add_argument('--home',type=Path,default=Path(__file__).parent/'data');args=parser.parse_args();run(args.project,args.home)

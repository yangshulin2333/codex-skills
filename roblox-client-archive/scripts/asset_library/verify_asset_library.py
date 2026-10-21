"""Independently check catalog paths, preserved bytes, raw identity and category coverage."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import re

def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def controlled_source_input(archive,relative,expected_sha,expected_bytes):
    value=Path(relative)
    if value.is_absolute() or '..' in value.parts: raise ValueError('Unsafe source metadata path')
    candidate=archive/value
    if not candidate.is_file(): candidate=archive/'validation'/value
    path=candidate.resolve(strict=True)
    if not path.is_relative_to(archive) or candidate.is_symlink() or not path.is_file(): raise ValueError('Source metadata escaped archive root')
    if path.stat().st_size!=expected_bytes or sha(path)!=expected_sha: raise ValueError('Controlled source metadata hash/size differs: '+relative)
    return path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args();root=args.library.resolve(strict=True)
    catalog=read(root/'index.json');checks=read(root/'file-checksums.json')['files'];download=read(root/'download-index.json')
    assert catalog['mode']=='organize_assets' and catalog['sourceRecoveryPerformed'] is False and catalog['originalScriptsExecuted'] is False
    records={c['relativePath']:c for c in checks}
    for relative,item in records.items():
        path=(root/relative).resolve(strict=True)
        assert path.is_relative_to(root) and path.stat().st_size==item['bytes'] and sha(path)==item['sha256'],relative
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name not in {'file-checksums.json','library-verification.json'}}
    assert actual==set(records),'Unindexed or removed library files'
    hashes=set()
    for item in download['files']:
        record=records[item['relativePath']]
        assert record['sha256']==item['sha256'] and record['bytes']==item['bytes']
        assert item['sha256'] not in hashes,'Duplicated original content instead of alias indexing'
        hashes.add(item['sha256'])
    category_counts=Counter()
    for item in catalog['records']:
        assert item['relativePath'] in records,item['relativePath']
        if item.get('sha256'): assert item['sha256']==records[item['relativePath']]['sha256']
        category_counts[item['category']]+=1
    assert dict(category_counts)==catalog['summary']['catalogByCategory']
    if args.archive:
        archive=args.archive.resolve(strict=True)
        for item in catalog['sourceInputs']:
            controlled_source_input(archive,item['relativePath'],item['sha256'],item['bytes'])
    page=(root/'index.html').read_text(encoding='utf-8')
    raw=re.search(r'<script id="catalog" type="application/json">(.*?)</script>',page,re.S).group(1)
    data=json.loads(raw)
    assert len(data['records'])==len(catalog['records']) and data['summary']==catalog['summary']
    assert not re.search(r'<(?:script|link)[^>]+(?:src|href)=["\']https?://',page,re.I),'External browser dependency'
    for key in ['models/assembled/index.json','rigs/index.json','animations/scene/index.json']:
        source=read(root/key).get('source',{})
        assert 'path' not in source or not Path(source['path']).is_absolute(),'Machine source path leaked into portable scene index'
    print(json.dumps({'passed':True,'checkedFiles':len(records),'downloadedUniqueFiles':len(hashes),
        'catalogRecords':len(catalog['records']),'categoryCounts':dict(category_counts),'rawInputsUnchanged':bool(args.archive),
        'offlineCatalogDataPassed':True,'sourceRecoveryPerformed':False},ensure_ascii=False))

if __name__=='__main__': main()

"""Build an offline catalog from verified, original-format asset-library stages."""
from pathlib import Path
from collections import Counter
import argparse
import csv
import hashlib
import html
import json
import re
import zipfile
from urllib.parse import parse_qs, urlsplit

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def safe_path(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe library path: ' + str(relative))
    return path

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def first(record, *keys, default=None):
    return next((record[k] for k in keys if record.get(k) is not None), default)

def as_list(value):
    return value if isinstance(value, list) else [] if value is None else [value]

def tree_text(value):
    if isinstance(value,list) and all(isinstance(v,dict) and 'name' in v for v in value):
        return '.'.join(str(v['name']) for v in value)
    return str(value)

def compact_record(row):
    result={}
    for key,value in row.items():
        if key in {'models','rigNodes','dependencyReferences','sourceProofs','usageEvidence','references','poseNames','externalRefsCleared'} and isinstance(value,list):
            result[key+'Count']=len(value)
            result[key+'Sample']=value[:5]
        elif key=='dependencyUris' and isinstance(value,list):
            result['dependencyUrisCount']=len(value);result['dependencyUrisSample']=value[:15]
        elif key not in {'referencePaths','sourceTreePath','relativePath','containerPath','containerFile','file','path','sha256','bytes','sourcePath','assetIDs','requestKeys','filename','tags','category','subtype'}: result[key]=value
    return result

def portable(value):
    if isinstance(value,dict):
        return {k:portable(v) for k,v in value.items() if k!='outputRoot' and not (k=='path' and isinstance(v,str) and Path(v).is_absolute())}
    if isinstance(value,list): return [portable(v) for v in value]
    return value

def file_record(row, category=None):
    relative = first(row, 'catalogFile', 'file', 'path', 'containerFile', 'outputRelativePath', 'outputPath', 'bundlePath')
    if relative is None:
        relative = row.get('relativePath') if isinstance(row.get('relativePath'),str) else row.get('containerPath')
    if not isinstance(relative,str): raise ValueError('Expected a relative file path in scene/download record')
    label = first(row, 'name', 'filename', 'label', 'sourcePathText', 'sourceTreePath', 'sourcePath', 'originalPath', default=Path(relative or '').stem)
    if isinstance(label,list): label=tree_text(label)
    references=first(row, 'referencePaths', 'sourcePaths', 'sourcePath', 'sourceTreePath', 'originalPath')
    if isinstance(references,list) and references and isinstance(references[0],dict): references=[tree_text(references)]
    return {'name': label, 'category': category or row.get('category', 'other'),
            'subtype': row.get('subtype', category or 'original'), 'relativePath': relative,
            'sha256': first(row,'sha256','containerSha256'), 'bytes': row.get('bytes'),
            'assetIDs': as_list(first(row, 'assetIDs', 'assetIds')), 'tags': as_list(row.get('tags')),
            'referencePaths': as_list(references),
            'instancePath':row.get('relativePath') if isinstance(row.get('relativePath'),list) else None,
            'sourceRecord': compact_record(row)|({'instanceRelativePath':row['relativePath']} if isinstance(row.get('relativePath'),list) else {})}

HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>素材库索引</title><style>
:root{color-scheme:dark;font-family:system-ui,"Microsoft YaHei",sans-serif;background:#10151b;color:#e7edf6}*{box-sizing:border-box}body{margin:0}header{padding:30px 5vw 22px;background:#17212e;border-bottom:1px solid #2b3c4c}h1{font-size:27px;margin:0 0 10px}.muted{color:#a5b6c7;font-size:14px;line-height:1.7}.stats{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.stat{background:#213142;padding:10px 15px;border-radius:9px}.controls{display:flex;gap:12px;flex-wrap:wrap;padding:22px 5vw 10px;position:sticky;top:0;background:#10151bef;backdrop-filter:blur(10px);z-index:2}input,select,button{background:#1b2836;border:1px solid #3d5265;color:#edf4fc;padding:11px;border-radius:8px;font:inherit}input{flex:1;min-width:220px}button{cursor:pointer}.status{margin:10px 5vw 20px;color:#adc2d4}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin:0 5vw 24px}.card{background:#18232f;border:1px solid #2e4053;border-radius:12px;padding:16px;min-width:0}.card h2{font-size:15px;line-height:1.6;overflow-wrap:anywhere;margin:12px 0 7px}.preview{height:130px;display:flex;align-items:center;justify-content:center;background:repeating-conic-gradient(#14202a 0% 25%,#1d2a35 0% 50%) 50%/20px 20px;border-radius:8px}.preview img{max-width:100%;max-height:100%;object-fit:contain}.icon{font-size:32px;color:#7bbbd0}.tag{display:inline-block;padding:3px 7px;font-size:11px;border-radius:4px;background:#2b3f52;margin:2px;color:#c9e6f6}a{color:#81d7e0;text-decoration:none}a:hover{text-decoration:underline}audio{width:100%;margin:8px 0}.path{font-size:12px;line-height:1.5;color:#92a9bf;overflow-wrap:anywhere}.pager{display:flex;align-items:center;justify-content:center;gap:20px;margin:24px}.empty{padding:30px;color:#acc3d4}footer{padding:20px 5vw;color:#92a9bf;font-size:12px;border-top:1px solid #2b3c4c}
</style><header><h1>分类素材库</h1><div class="muted">原始格式 · 模型 / 贴图 / 骨架与动画 / 音频<br>完整模型文件供 Roblox 编辑器导入；网格、贴图和动作依赖的取得情况见索引。原始归档保留，未转换 Luau。</div><div class="stats" id="stats"></div></header>
<div class="controls"><input id="query" placeholder="搜索名称、原路径、资产 ID、用途…" aria-label="搜索素材"><select id="category" aria-label="分类"><option value="">全部分类</option><option value="models">模型</option><option value="textures">贴图</option><option value="animations">骨架与动画</option><option value="audio">音频</option><option value="other">其他原始文件</option></select><select id="kind" aria-label="来源形式"><option value="">全部形式</option></select></div><div class="status" id="status"></div><main class="grid" id="grid"></main><div class="pager"><button id="prev">上一页</button><span id="page"></span><button id="next">下一页</button></div><footer>离线检索，无外部服务。详细信息：<a href="index.json">总索引 JSON</a> · <a href="index.csv">表格索引 CSV</a> · <a href="missing-assets.json">未取得资源</a> · <a href="README.txt">使用说明</a></footer>
<script id="catalog" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('catalog').textContent);const records=data.records;
const names={models:'模型',textures:'贴图',animations:'骨架与动画',audio:'音频',other:'其他'};
const kinds={assembled_bundle:'组装模型容器',assembled_model:'容器内模型',roblox_mesh:'原始网格',rig:'骨架容器',nested_rig_model:'骨架模型',scene_keyframes:'场景动作',downloaded_keyframe_or_curve_container:'已下载动作',font:'字体',json_metadata:'元数据'};
let page=0,filtered=[];const pageSize=48;const q=document.getElementById('query'),cat=document.getElementById('category'),kind=document.getElementById('kind');
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
const localURL=p=>p.split('/').map(encodeURIComponent).join('/');
const s=data.summary,dc=s.downloadSummary.categoryCounts,sc=s.sceneSummary;
for(const [label,n] of [['贴图',dc.textures],['原始网格',dc.models],['组装容器',sc.modelBundleFiles],['骨架模型',sc.nestedRigModelObjects],['动作容器',dc.animations+sc.uniqueAnimationFiles],['音频',dc.audio]]){document.getElementById('stats').append(node('div',label+' '+n,'stat'))}
for(const v of [...new Set(records.map(r=>r.subtype))].sort()){const o=node('option',kinds[v]||v);o.value=v;kind.append(o)}
function filter(){page=0;const term=q.value.trim().toLocaleLowerCase();filtered=records.filter(r=>(!cat.value||r.category===cat.value)&&(!kind.value||r.subtype===kind.value)&&(!term||r.search.includes(term)));render()}
function render(){const grid=document.getElementById('grid');grid.replaceChildren();const pages=Math.max(1,Math.ceil(filtered.length/pageSize));page=Math.max(0,Math.min(page,pages-1));document.getElementById('status').textContent=`匹配 ${filtered.length.toLocaleString()} 条索引 · 容器内模型和骨架可指向同一文件`;document.getElementById('page').textContent=`${page+1} / ${pages}`;document.getElementById('prev').disabled=page===0;document.getElementById('next').disabled=page>=pages-1;
for(const r of filtered.slice(page*pageSize,(page+1)*pageSize)){const card=node('article',undefined,'card'),preview=node('div',undefined,'preview');const p=r.relativePath||'',ext=p.split('.').pop().toLowerCase();if(['png','jpg','jpeg'].includes(ext)){const im=node('img');im.src=localURL(p);im.alt=r.name;im.loading='lazy';preview.append(im)}else preview.append(node('span',r.category==='audio'?'♫':r.subtype==='rig'?'骨架':ext.toUpperCase()||'素材','icon'));card.append(preview,node('h2',r.name));card.append(node('span',names[r.category]||r.category,'tag'),node('span',r.subtype,'tag'));for(const t of (r.tags||[]).slice(0,4))card.append(node('span',t,'tag'));if(r.category==='audio'&&['ogg','mp3'].includes(ext)){const a=node('audio');a.controls=true;a.preload='none';a.src=localURL(p);card.append(a)}if(p){const a=node('a','打开原格式文件');a.href=localURL(p);card.append(node('p'),a,node('div',p,'path'))}if(r.assetIDs.length)card.append(node('div','ID: '+r.assetIDs.slice(0,4).join(', '),'path'));if(r.referencePaths.length)card.append(node('div',r.referencePaths[0],'path'));const details=node('details'),sum=node('summary','来源与依赖');details.append(sum);const pre=node('pre',JSON.stringify(r.detail,null,2),'path');details.append(pre);card.append(details);grid.append(card)}if(!filtered.length)grid.append(node('div','没有匹配素材','empty'))}
q.addEventListener('input',filter);cat.addEventListener('change',filter);kind.addEventListener('change',filter);document.getElementById('prev').onclick=()=>{page--;render()};document.getElementById('next').onclick=()=>{page++;render()};filter();
</script></html>'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--scene-index',type=Path,required=True)
    parser.add_argument('--download-index',type=Path)
    parser.add_argument('--output-zip',type=Path)
    args=parser.parse_args()
    root=args.library.resolve(strict=True);archive=args.archive.resolve(strict=True)
    downloads=load(args.download_index or root/'download-index.json');scene=load(args.scene_index)
    if (root/'index.json').exists(): raise ValueError('Catalog already exists; preserve prior result')
    portable_scene=portable({k:v for k,v in scene.items() if k not in {'outputRoot','indexes'}})
    portable_scene['source']={k:v for k,v in scene.get('source',{}).items() if k!='path'}|{'relativePath':'snapshot/scene.rbxlx'}
    portable_scene['indexes']={'models':'models/assembled/index.json','rigs':'rigs/index.json','animations':'animations/scene/index.json'}
    write_json(root/'scene-index.json',portable_scene)
    rows=[file_record(row) for row in downloads['files']]
    models=load(root/'models/assembled/index.json')
    asset_ids={str(asset_id):file for file in downloads['files'] for asset_id in file.get('assetIDs',[])}
    request_files={key:file for file in downloads['files'] for key in file.get('requestKeys',[])}
    requests={r.get('key',r.get('requestKey')):r for r in downloads.get('requests',[])}
    dependency_bundles=[]
    for bundle in models.get('bundles',[]):
        bundle_row=bundle|{'catalogFile':bundle['path'],'subtype':'assembled_bundle'}
        dependencies=[]
        for uri in bundle.get('dependencyUris',[]):
            parsed=urlsplit(uri);asset_id=parsed.netloc if parsed.scheme=='rbxassetid' else parse_qs(parsed.query).get('id',[None])[0]
            key='id:'+str(asset_id) if asset_id else ('builtin:'+uri[len('rbxasset://'):].strip().replace('\\','/') if uri.startswith('rbxasset://') else uri)
            available=asset_ids.get(str(asset_id)) if asset_id else request_files.get(key)
            failure=requests.get(key,{})
            dependencies.append({'uri':uri,'assetID':asset_id,'available':bool(available),
                'libraryFile':available.get('relativePath') if available else None,'sha256':available.get('sha256') if available else None,
                'status':'success' if available else failure.get('status','not_in_verified_downloads')})
        bundle_row['dependencyAvailability']={'references':len(dependencies),'available':sum(d['available'] for d in dependencies),'unavailable':sum(not d['available'] for d in dependencies)}
        dependency_bundles.append({'modelFile':bundle['path'],'dependencies':dependencies})
        rows.append(file_record(bundle_row,'models'))
        for model in bundle.get('models',[]):
            new=file_record(model|{'catalogFile':bundle['path'],'sha256':bundle['sha256'],'bytes':bundle['bytes']},'models');new['subtype']='assembled_model';rows.append(new)
    rigs=load(root/'rigs/index.json')
    for row in rigs.get('rigs',[]):
        new=file_record(row,'animations');new['subtype']='rig';rows.append(new)
    for row in rigs.get('rigModels',[]):
        new=file_record(row,'animations');new['subtype']='nested_rig_model';rows.append(new)
    animations=load(root/'animations/scene/index.json')
    for row in animations.get('animations',[]):
        new=file_record(row,'animations');new['subtype']='scene_keyframes';rows.append(new)
    identities=set();unique=[]
    for row in rows:
        if not row['relativePath']: raise ValueError('Catalog record missing relative file: '+str(row)[:300])
        path=safe_path(root,row['relativePath'])
        if not path.is_file(): raise ValueError('Catalog file missing: '+str(path))
        key=(row['category'],row['subtype'],row['relativePath'],str(row['name']),json.dumps(row['instancePath'],ensure_ascii=False,sort_keys=True))
        if key in identities: continue
        identities.add(key)
        row['id']=hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:20]
        unique.append(row)
    rows=unique
    missing=[]
    for req in downloads.get('requests',[]):
        if req.get('status')!='success':
            item={k:v for k,v in req.items() if k not in {'references','history'}}
            item['referenceCount']=len(req.get('references',[]));item['referenceSample']=req.get('references',[])[:5]
            item['fullRecordIndex']='download-index.json#requests'
            missing.append(item)
    summary={'catalogRecords':len(rows),'catalogByCategory':dict(Counter(row['category'] for row in rows)),
        'catalogBySubtype':dict(Counter(row['subtype'] for row in rows)),
        'downloadedUniqueFiles':len(downloads['files']), 'missingRequests':len(missing),
        'sceneSummary':compact_record(portable(scene.get('summary',{}))), 'downloadSummary':downloads.get('summary',{})}
    source_inputs=[]
    canonical_relative='download-validation.json' if (archive/'download-validation.json').is_file() else 'validation/download-validation.json'
    for relative in ['snapshot/scene.rbxlx','inventory.json',canonical_relative]:
        source=archive/relative
        source_inputs.append({'relativePath':relative,'bytes':source.stat().st_size,'sha256':digest(source)})
    catalog={'schemaVersion':1,'mode':'organize_assets','pathsRelativeTo':'libraryRoot','originalScriptsExecuted':False,
        'sourceRecoveryPerformed':False,'summary':summary,'sourceInputs':source_inputs,'records':rows}
    write_json(root/'index.json',catalog);write_json(root/'missing-assets.json',{'requests':missing,'count':len(missing)})
    write_json(root/'model-dependencies.json',{'schemaVersion':1,'bundles':dependency_bundles,'note':'A local file association does not rewrite online model URIs or certify renderability.'})
    with (root/'index.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['名称','分类','形式','文件相对路径','资产ID','用途标签','原引用路径','SHA256'])
        for row in rows:
            values=[row['name'],row['category'],row['subtype'],row['relativePath'],','.join(map(str,row['assetIDs'])),','.join(map(str,row['tags'])),' | '.join(map(str,row['referencePaths'])),row['sha256'] or '']
            writer.writerow(["'"+str(v) if str(v).startswith(('=','+','-','@')) else str(v) for v in values])
    browser_rows=[]
    for row in rows:
        detail=row['sourceRecord'];search=' '.join(str(row[k]) for k in ['name','assetIDs','tags','referencePaths','relativePath']).lower()
        browser_rows.append({k:row[k] for k in ['name','category','subtype','relativePath','assetIDs','tags','referencePaths']}|{'search':search,'detail':detail})
    data=json.dumps({'records':browser_rows,'summary':summary},ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    (root/'index.html').write_text(HTML.replace('__DATA__',data),encoding='utf-8')
    (root/'README.txt').write_text('分类素材库\n\n双击 index.html 可离线搜索、查看贴图和试听音频。index.csv 可用表格工具筛选；index.json 保存完整来源和依赖。\n\nmodels/meshes 是原始网格；models/assembled 是从原场景提取的原生模型容器。嵌套模型和骨架索引可能指向同一个容器，请结合相对实例路径定位。\nanimations/downloaded 是解析确认的动作数据；animations/scene 为场景内关键帧；rigs 保存骨架索引。骨架与动作是否匹配需要进一步核对，未自动认证蒙皮或玩法。\n\n原始下载文件按 SHA256 去重；纹理用途来自实际引用，候选标签不代表作者原名。缺失依赖见 missing-assets.json 与模型记录。其他字体和 JSON 原始文件保存在 other。\n\n模型提取剔除脚本，保留内部引用，外部引用置空并列出。原始归档和字节码没有改写，未反编译 Luau、未运行原游戏脚本、未下载新增资源。原模型仍可能有在线引用；分类素材库不保证完全离线可运行。\n\n模型 XML 使用标准 XML 声明；部分 Lune 解码器需要先在内存移除声明再解析，保留文件原字节。普通 XML 结构验证和原生解析器抽样不等于 Studio 导入、渲染、蒙皮或动画匹配验证。\n',encoding='utf-8')
    checks=[]
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name not in {'file-checksums.json','library-verification.json'}:
            checks.append({'relativePath':path.relative_to(root).as_posix(),'bytes':path.stat().st_size,'sha256':digest(path)})
    write_json(root/'file-checksums.json',{'schemaVersion':1,'files':checks})
    for item in checks:
        path=safe_path(root,item['relativePath']);assert path.stat().st_size==item['bytes'] and digest(path)==item['sha256']
    report={'fileChecksumsPassed':True,'catalogPathsPassed':True,'sourceInputsStable':True,'sourceRecoveryPerformed':False,'summary':summary,'verifiedFiles':len(checks)}
    for item in source_inputs: assert digest(archive/item['relativePath'])==item['sha256']
    if args.output_zip:
        output=args.output_zip.resolve()
        if output.exists(): raise ValueError('ZIP exists; refusing overwrite')
        temporary=output.with_suffix(output.suffix+'.partial')
        if temporary.exists(): raise ValueError('Pending ZIP exists')
        paths=sorted(p for p in root.rglob('*') if p.is_file() and p.name!='library-verification.json')
        expected={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':digest(p)} for p in paths}
        print('ZIP_STARTED',len(paths),flush=True)
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as bundle:
            for p in paths: bundle.write(p,p.relative_to(root).as_posix())
        with zipfile.ZipFile(temporary) as bundle:
            assert bundle.testzip() is None and set(bundle.namelist())==set(expected)
            for name,item in expected.items():
                assert bundle.getinfo(name).file_size==item['bytes']
                with bundle.open(name) as stream: assert hashlib.file_digest(stream,'sha256').hexdigest()==item['sha256']
        temporary.replace(output)
        report['zip']={'name':output.name,'bytes':output.stat().st_size,'sha256':digest(output),'entries':len(expected),'crcPassed':True,'entrySizeAndSha256Passed':True}
    write_json(root/'library-verification.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__': main()

"""Organize a verified raw archive locally; never execute archived game scripts."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent

def read_json(path): return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def source_file(root,relative,expected_sha=None,expected_bytes=None):
    value=Path(relative)
    if value.is_absolute() or '..' in value.parts: raise ValueError('Expected controlled archive-relative metadata path')
    candidate=root/value
    # The official package relocates root metadata beneath validation/. No
    # basename search or arbitrary alternate root is allowed.
    if not candidate.is_file(): candidate=root/'validation'/value
    path=candidate.resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or candidate.is_symlink(): raise ValueError('Source metadata escaped archive root')
    if expected_sha is not None and sha(path)!=expected_sha: raise ValueError('Relocated source metadata SHA256 differs')
    if expected_bytes is not None and path.stat().st_size!=expected_bytes: raise ValueError('Relocated source metadata size differs')
    return path

def normalized_source_proofs(root,proofs):
    result=[];seen=set()
    for proof in proofs:
        row=dict(proof)
        row['path']=source_file(root,proof['path'],proof['sha256']).relative_to(root).as_posix()
        if row['path'] in seen: raise ValueError('Duplicate resolved source-proof path')
        seen.add(row['path'])
        if proof.get('inventoryPath'):
            row['inventoryPath']=source_file(root,proof['inventoryPath'],proof['inventorySha256']).relative_to(root).as_posix()
        result.append(row)
    return sorted(result,key=lambda row:row['path'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--lune-executable',type=Path)
    parser.add_argument('--evidence-dir',type=Path)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--no-zip',action='store_true')
    args=parser.parse_args()
    archive=args.archive.resolve(strict=True);output=args.output.resolve()
    if output.is_relative_to(archive) or archive.is_relative_to(output): raise ValueError('Library and raw archive must be separate')
    evidence=(args.evidence_dir or output.with_name(output.name+'.evidence')).resolve()
    if evidence.is_relative_to(archive) or evidence.is_relative_to(output): raise ValueError('Execution evidence must stay outside source and library')
    scene=archive/'snapshot/scene.rbxlx';canonical=archive/'download-validation.json'
    if not canonical.exists(): canonical=archive/'validation/download-validation.json'
    for p in [scene,canonical,archive/'inventory.json']:
        if not p.is_file(): raise FileNotFoundError('Required raw input missing: '+str(p))
    source_identity={'sceneSha256':sha(scene),'canonicalSha256':sha(canonical),'inventorySha256':sha(archive/'inventory.json')}
    evidence.mkdir(parents=True,exist_ok=True)
    checkpoint=evidence/'checkpoint.json'
    if checkpoint.exists():
        if not args.resume: raise ValueError('Evidence checkpoint exists; use --resume after verification')
        state=read_json(checkpoint)
        if state['sourceIdentity']!=source_identity: raise ValueError('Raw inputs changed since checkpoint')
    else:
        if output.exists() and any(output.iterdir()) and not args.resume: raise ValueError('Nonempty output exists; choose a new library or explicitly resume verified stages')
        state={'schemaVersion':1,'mode':'organize_assets','sourceIdentity':source_identity,'steps':[],
               'rawReadOnly':True,'convertToLuau':False,'executeGameScripts':False}
    if state.get('complete'):
        state['lastCompletedUnix']=state.get('finishedUnix')
    state.update(complete=False,currentRunStartedUnix=time.time())
    def save(): checkpoint.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    def execute(label,command,always=False):
        completed=[s for s in state['steps'] if s['label']==label and s.get('exitCode')==0]
        if completed and not always: return completed[-1]
        attempt=sum(s['label']==label for s in state['steps'])+1
        item={'label':label,'attempt':attempt,'command':command,'startedUnix':time.time()}
        state['steps'].append(item);save();print('COMMAND_EXECUTION',label,json.dumps(command),flush=True)
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
        stdout_path=evidence/(label+'.'+str(attempt)+'.stdout.txt');stderr_path=evidence/(label+'.'+str(attempt)+'.stderr.txt')
        item.update(stdoutPath=str(stdout_path),stderrPath=str(stderr_path));save()
        with stdout_path.open('xb') as out, stderr_path.open('xb') as err:
            run=subprocess.run(command,stdout=out,stderr=err,env=env)
        item.update(exitCode=run.returncode,finishedUnix=time.time());save()
        print('EXIT',label,run.returncode,flush=True)
        if run.returncode: raise SystemExit(run.returncode)
        return item
    # Source validation is a new execution on every invocation, including resume.
    source_attempt=sum(s['label']=='check_source_inputs' for s in state['steps'])+1
    source_evidence=evidence/('source-input-check.'+str(source_attempt))
    execute('check_source_inputs',[sys.executable,str(HERE/'classify_downloaded_assets.py'),'--archive',str(archive),
            '--check-inputs-only','--evidence-dir',str(source_evidence)],always=True)
    preflight=read_json(source_evidence/'input-preflight-verification.json')
    canonical_record=read_json(canonical)
    capture_identity={'placeId':canonical_record['placeId'],'universeId':canonical_record['universeId'],
                      'canonicalSha256':source_identity['canonicalSha256']}
    if not preflight.get('passed') or preflight.get('canonicalSha256')!=source_identity['canonicalSha256']:
        raise ValueError('New source preflight did not bind this canonical SHA256')
    download_index=output/'download-index.json'
    if not download_index.exists():
        command=[sys.executable,str(HERE/'classify_downloaded_assets.py'),'--archive',str(archive),'--output',str(output),'--evidence-dir',str(evidence/'download-stage')]
        if args.lune_executable: command+=['--lune-executable',str(args.lune_executable.resolve(strict=True))]
        execute('classify_downloads',command,always=True)
    else:
        existing_download=read_json(download_index)
        recorded_source=existing_download.get('source',{})
        if recorded_source.get('canonicalSha256')!=source_identity['canonicalSha256'] or recorded_source.get('captureIdentity')!=capture_identity:
            raise ValueError('Existing download index belongs to a different canonical capture')
        if existing_download.get('game')!={'placeId':capture_identity['placeId'],'universeId':capture_identity['universeId']}:
            raise ValueError('Existing download index game identity differs from source')
        canonical_from_index=source_file(archive,recorded_source.get('canonicalPath',''),source_identity['canonicalSha256'])
        if canonical_from_index!=canonical.resolve(strict=True):
            raise ValueError('Existing download index canonical path has no controlled layout equivalence')
        indexed_proofs=normalized_source_proofs(archive,recorded_source.get('verifiedSourceMetadata',[]))
        fresh_proofs=normalized_source_proofs(archive,preflight.get('verifiedSourceMetadata',[]))
        if indexed_proofs!=fresh_proofs:
            raise ValueError('Existing download index source proof set differs from fresh preflight')
        for item in existing_download['files']:
            p=output/item['relativePath']
            if Path(item['relativePath']).is_absolute() or p.is_symlink() or not p.resolve().is_relative_to(output) or sha(p)!=item['sha256'] or p.stat().st_size!=item['bytes']: raise ValueError('Existing copied file differs')
    scene_report=evidence/'scene-extraction.json'
    if not scene_report.exists():
        if (output/'models/assembled/index.json').exists(): raise ValueError('Scene output exists without its checkpoint; supply original evidence directory')
        execute('extract_scene',[sys.executable,str(HERE/'extract_scene_models.py'),'--source',str(scene),'--output-root',str(output),'--work-root',str(evidence)],always=True)
    if read_json(scene_report)['source']['sha256']!=source_identity['sceneSha256']: raise ValueError('Existing scene extraction source mismatch')
    scene_verification=evidence/'scene-extraction-verification.json'
    if not scene_verification.exists():
        execute('verify_scene',[sys.executable,str(HERE/'verify_scene_models.py'),'--source',str(scene),'--output-root',str(output),'--report',str(scene_verification)],always=True)
    else:
        verification=read_json(scene_verification)
        if verification.get('status')!='passed' or verification['source']['sha256']!=source_identity['sceneSha256']: raise ValueError('Scene verification checkpoint mismatch')
    if not (output/'index.json').exists():
        command=[sys.executable,str(HERE/'finalize_asset_library.py'),'--archive',str(archive),'--library',str(output),'--scene-index',str(scene_report)]
        execute('finalize',command,always=True)
    # Verification must observe the current library even when an old run passed.
    execute('verify_library',[sys.executable,str(HERE/'verify_asset_library.py'),'--library',str(output),'--archive',str(archive)],always=True)
    if not args.no_zip:
        zip_path=output.with_name(output.name+'.zip')
        package_attempt=sum(s['label']=='package_library' for s in state['steps'])+1
        command=[sys.executable,str(HERE/'package_asset_library.py'),'--library',str(output),'--output',str(zip_path),
                 '--evidence-dir',str(evidence/('package.'+str(package_attempt)))]
        if zip_path.exists(): command+=['--verify-existing']
        execute('package_library',command,always=True)
    if source_identity!={'sceneSha256':sha(scene),'canonicalSha256':sha(canonical),'inventorySha256':sha(archive/'inventory.json')}: raise ValueError('Raw input changed')
    state.update(complete=True,zipRequested=not args.no_zip,finishedUnix=time.time());save()
    print(json.dumps({'complete':True,'rawInputsUnchanged':True,'sourceRecoveryPerformed':False,'library':str(output),
                     'zipRequested':not args.no_zip,'zip':str(output.with_name(output.name+'.zip')) if not args.no_zip else None},ensure_ascii=False),flush=True)

if __name__=='__main__': main()

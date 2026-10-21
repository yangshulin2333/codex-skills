"""Create a new library ZIP, or explicitly verify an existing ZIP without replacing it."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import uuid
import zipfile

def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def library_files(root):
    files=sorted(p for p in root.rglob('*') if p.is_file())
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root): raise ValueError('Linked or out-of-root library file: '+str(path))
        if path.suffix.lower() in {'.partial','.tmp','.lock'}: raise ValueError('Incomplete library file present: '+str(path))
    return files

def write_json(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--output',type=Path,help='Default: sibling library-directory-name.zip')
    parser.add_argument('--evidence-dir',type=Path,help='Default: sibling ZIP-name.evidence directory')
    parser.add_argument('--verify-existing',action='store_true',help='Require an existing ZIP and verify every entry; never overwrite')
    args=parser.parse_args();root=args.library.resolve(strict=True)
    output=(args.output or root.with_name(root.name+'.zip')).resolve()
    evidence=(args.evidence_dir or output.with_name(output.name+'.evidence')).resolve()
    if output.is_relative_to(root) or evidence.is_relative_to(root): raise ValueError('ZIP and external evidence must be outside library')
    if args.verify_existing:
        if not output.is_file(): raise ValueError('--verify-existing requires an existing ZIP')
    elif output.exists(): raise ValueError('ZIP exists; preserve it or explicitly use --verify-existing')
    temporary=output.with_name(output.name+'.partial')
    if not args.verify_existing and temporary.exists(): raise ValueError('Partial ZIP exists; inspect prior state without deleting it')
    files=library_files(root)
    expected={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':digest(p)} for p in files}
    if not expected: raise ValueError('Refusing empty library')
    if args.verify_existing:
        zip_input=output;prior_zip={'bytes':output.stat().st_size,'sha256':digest(output)}
        print('EXISTING_LIBRARY_ZIP_VERIFICATION_STARTED',len(files),flush=True)
    else:
        output.parent.mkdir(parents=True,exist_ok=True)
        print('LIBRARY_ZIP_STARTED',len(files),flush=True)
        with zipfile.ZipFile(temporary,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as bundle:
            for path in files: bundle.write(path,path.relative_to(root).as_posix())
        zip_input=temporary;prior_zip=None
    entry_records=[]
    with zipfile.ZipFile(zip_input) as bundle:
        if bundle.testzip() is not None: raise ValueError('ZIP CRC failed')
        names=bundle.namelist()
        if len(names)!=len(set(names)) or len(names)!=len(expected) or set(names)!=set(expected): raise ValueError('ZIP file set has missing, duplicate, or unexpected entries')
        for name,item in expected.items():
            actual_size=bundle.getinfo(name).file_size
            with bundle.open(name) as stream: actual_sha=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual_size!=item['bytes'] or actual_sha!=item['sha256']: raise ValueError('ZIP entry differs: '+name)
            entry_records.append({'relativePath':name,'expectedBytes':item['bytes'],'actualBytes':actual_size,'expectedSha256':item['sha256'],'actualSha256':actual_sha,'passed':True})
    if {p.relative_to(root).as_posix() for p in library_files(root)}!=set(expected): raise ValueError('Library file set changed during ZIP operation')
    for relative,item in expected.items():
        path=root/relative
        if path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']: raise ValueError('Library bytes changed during ZIP operation: '+relative)
    if args.verify_existing:
        if output.stat().st_size!=prior_zip['bytes'] or digest(output)!=prior_zip['sha256']: raise ValueError('Existing ZIP changed during verification')
    else:
        if output.exists(): raise ValueError('ZIP appeared during creation; preserve existing and partial outputs')
        temporary.rename(output)
    evidence.mkdir(parents=True,exist_ok=True)
    suffix=''
    if (evidence/'zip-entry-verification.json').exists() or (evidence/'package-verification.json').exists():
        suffix='.run-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    entry_report=evidence/('zip-entry-verification'+suffix+'.json');package_report=evidence/('package-verification'+suffix+'.json')
    report={'passed':True,'mode':'verify_existing' if args.verify_existing else 'create_new','zipName':output.name,'zipPath':str(output),
        'zipBytes':output.stat().st_size,'zipSha256':digest(output),'entries':len(files),'crcPassed':True,'fileSetPassed':True,
        'everyEntrySizeAndSha256Passed':True,'sourceLibraryUnchanged':True,'existingZipUnchanged':True if args.verify_existing else None,
        'entryVerificationReport':str(entry_report),'packageVerificationReport':str(package_report)}
    write_json(entry_report,entry_records);write_json(package_report,report)
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__': main()

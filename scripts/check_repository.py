#!/usr/bin/env python3
"""Offline repository checks; no deployment, device access, or external dependencies."""
import argparse
import ast
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit
import zipfile


SKIP_DIRS = {'.git', '__pycache__', '.venv', 'venv', 'private', 'runtime', 'backups', 'outputs', 'work'}
RESERVED_DIRS = SKIP_DIRS | {'scripts', 'archives', 'docs', 'tests', '.github', 'assets'}


def visible_files(root):
    for item in sorted(root.iterdir()):
        if item.is_symlink():
            continue
        if item.is_dir() and item.name not in SKIP_DIRS:
            yield from visible_files(item)
        elif item.is_file():
            yield item


def inspect_repository(root):
    """Return errors and a compact summary. This function does not execute tests."""
    root = root.resolve()
    errors = []
    skills = []
    readme = root / 'README.md'
    homepage = readme.read_text(encoding='utf-8-sig') if readme.is_file() else ''
    if not homepage:
        errors.append('README.md: missing or empty homepage')

    for directory in sorted(root.iterdir()):
        if directory.is_symlink():
            errors.append(directory.name + ': symbolic-link roots are not inspected')
            continue
        if not directory.is_dir() or directory.name in RESERVED_DIRS or directory.name.startswith('.'):
            continue
        entry = directory / 'SKILL.md'
        if not entry.is_file():
            errors.append(directory.name + ': missing SKILL.md')
            continue
        skills.append(directory)
        text = entry.read_text(encoding='utf-8-sig')
        header = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
        fields = header.group(1) if header else ''
        name = re.search(r'^name:[ \t]*([^\r\n]+)$', fields, re.M)
        description = re.search(r'^description:[ \t]*([^\r\n]*)$', fields, re.M)
        if not name or name.group(1).strip().strip('\"\'') != directory.name:
            errors.append(directory.name + ': frontmatter name must match directory')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', directory.name) or len(directory.name) > 64:
            errors.append(directory.name + ': use a short lower-case hyphenated skill name')
        description_value = description.group(1).strip().strip('\"\'') if description else ''
        if description_value in {'>', '|', '>-', '|-', '>+', '|+'}:
            continuation = fields[description.end():].splitlines()
            paragraphs = []
            for line in continuation:
                if line.strip() and not line.startswith((' ', '\t')):
                    break
                paragraphs.append(line.strip())
            description_value = ' '.join(paragraphs).strip()
        if not description_value:
            errors.append(directory.name + ': non-empty frontmatter description required')
        if '(' + directory.name + '/SKILL.md)' not in homepage:
            errors.append(directory.name + ': missing homepage entry link')
    if not skills:
        errors.append('No skill entrypoints found')

    links = 0
    python_files = 0
    for file in visible_files(root):
        relative = file.relative_to(root).as_posix()
        if file.suffix == '.md':
            text = file.read_text(encoding='utf-8-sig')
            for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)', text):
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith(('#', '//')):
                    continue
                destination = (file.parent / unquote(parsed.path)).resolve()
                if not destination.is_relative_to(root):
                    errors.append(relative + ': relative link escapes repository')
                elif not destination.exists():
                    errors.append(relative + ': broken relative link ' + target)
                links += 1
        if file.suffix == '.py':
            python_files += 1
            try:
                ast.parse(file.read_text(encoding='utf-8-sig'), filename=relative)
            except (SyntaxError, UnicodeError):
                errors.append(relative + ': Python syntax/encoding error')

    archive_count = 0
    archive_dir = root / 'archives'
    if archive_dir.is_dir():
        archive_readme = archive_dir / 'README.md'
        notes = archive_readme.read_text(encoding='utf-8-sig') if archive_readme.is_file() else ''
        checksums = dict((name, digest.lower()) for digest, name in re.findall(
            r'^([0-9a-fA-F]{64})  ([^/\\\r\n]+\.zip)\s*$', notes, re.M))
        for archive in sorted(archive_dir.glob('*.zip')):
            archive_count += 1
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if checksums.get(archive.name) != digest:
                errors.append('archives/' + archive.name + ': missing or mismatched documented SHA-256')
            try:
                with zipfile.ZipFile(archive) as handle:
                    if handle.testzip() is not None:
                        errors.append('archives/' + archive.name + ': corrupt ZIP entry')
            except (OSError, zipfile.BadZipFile):
                errors.append('archives/' + archive.name + ': invalid ZIP')

    return errors, {'skills': [p.name for p in skills], 'local_links': links,
                    'python_files': python_files, 'archives': archive_count}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--structure-only', action='store_true', help='skip all unit-test execution')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        errors, summary = inspect_repository(root)
    except (OSError, UnicodeError, ValueError):
        print('REPOSITORY_CHECK_FAILED: cannot read repository inputs', file=sys.stderr)
        return 1
    for error in errors:
        print('ERROR: ' + error)
    if errors:
        print('REPOSITORY_CHECK_FAILED')
        return 1
    print('STRUCTURE_OK: skills={skills}; links={local_links}; python={python_files}; archives={archives}'.format(
        skills=len(summary['skills']), **{k: v for k, v in summary.items() if k != 'skills'}), flush=True)
    if not args.structure_only:
        for name in summary['skills']:
            tests = root / name / 'tests'
            if not tests.is_dir() or not any(tests.glob('test*.py')):
                continue
            print('UNIT_TESTS: ' + name, flush=True)
            try:
                result = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                                        cwd=root / name, timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired):
                print('REPOSITORY_CHECK_FAILED: unit-test process unavailable or timed out')
                return 1
            if result.returncode != 0:
                return 1
    print('REPOSITORY_CHECK_OK' + (' (structure only; tests not run)' if args.structure_only else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())

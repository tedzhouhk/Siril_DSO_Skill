"""Validate the distributable skill without third-party dependencies."""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'siril-deep-sky'
errors = []
manifest = (SKILL / 'SKILL.md').read_text(encoding='utf-8')
if not manifest.startswith('---\n'):
    errors.append('Missing frontmatter')
else:
    front = manifest.split('---', 2)[1]
    if not re.search(r'^name: siril-deep-sky$', front, re.M):
        errors.append('Unexpected skill name')
    if not re.search(r'^description: .+', front, re.M):
        errors.append('Missing description')

files = [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts]
for path in files:
    if path.suffix in {'.fit', '.fits', '.fitseq', '.tif', '.tiff', '.onnx', '.pth', '.pt', '.docx'}:
        errors.append(f'Unexpected data/model artifact: {path.relative_to(ROOT)}')
    if path.suffix not in {'.md', '.py', '.yml', '.yaml'}:
        continue
    text = path.read_text(encoding='utf-8')
    if path.name != Path(__file__).name:
        if re.search(r'(?:[A-Za-z]:[/\\]Users[/\\]|codex-clipboard-)', text):
            errors.append(f'Personal machine/session content: {path.relative_to(ROOT)}')
    if path.suffix == '.py':
        ast.parse(text, filename=str(path))
    if path.suffix == '.md':
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
            if target.startswith(('https://', 'http://', '#', 'mailto:')):
                continue
            resolved = (path.parent / target.split('#', 1)[0]).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                errors.append(f'Broken/outside link in {path.relative_to(ROOT)}: {target}')

for expected in ['README.md', 'LICENSE', 'siril-deep-sky/references/calibration-library.md', 'siril-deep-sky/references/intake.md']:
    if not (ROOT / expected).exists():
        errors.append(f'Missing file: {expected}')
if errors:
    raise SystemExit('\n'.join(errors))
print(f'PASS: {len(files)} package files; manifest, Python syntax, local links, and private-data/artifact scan')

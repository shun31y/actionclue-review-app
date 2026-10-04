import argparse
from pathlib import Path
from app.dataset import load_dataset
p=argparse.ArgumentParser()
p.add_argument('directory',type=Path)
p.add_argument('--version',required=True)
a=p.parse_args()
rows=load_dataset((a.directory/'manifest.jsonl').read_bytes(),(a.directory/'meta.jsonl').read_bytes(),a.version)
print(f'{len(rows)} records validated; {sum(bool(r["warnings"]) for r in rows)} timing warnings')

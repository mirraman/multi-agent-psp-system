import json, sys
with open(r"c:\programing\multi-agent-psp-system\backend\data\outputs\Q99720.json") as f:
    d = json.load(f)
print('POCKETS:', json.dumps(d.get('pockets', {}).get('pockets', [])[:5], indent=2))
print('SYNTHESIS:', json.dumps(d.get('synthesis'), indent=2))
print('ANALYSIS:', json.dumps(d.get('analysis'), indent=2))
print('METRICS keys:', list(d.get('metrics', {}).keys()))
print('PDB text first 200 chars:')
psp = d.get('esmfold') or {}
for k in ['alphafold_db', 'esmfold', 'colabfold_modal']:
    pdb = psp.get(k, {}).get('pdb', '')
    if pdb:
        print(f'MODEL={k}, PDB_LEN={len(pdb)}')
        break

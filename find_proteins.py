import urllib.parse
import requests

query = "reviewed:true AND ft_transmem:[1 TO *] AND (cc_disease:*) NOT (database:pdb)"
# If "NOT (database:pdb)" fails we try without it and filter locally
url = f"https://rest.uniprot.org/uniprotkb/search?query={urllib.parse.quote(query)}&format=json&size=50"

r = requests.get(url)
if 'results' not in r.json():
    print("Failed with NOT database:pdb. Trying to fetch and filter locally.")
    query = "reviewed:true AND keyword:KW-0812 AND keyword:KW-0225 AND length:[1 TO 400]"
    url = f"https://rest.uniprot.org/uniprotkb/search?query={urllib.parse.quote(query)}&format=json&size=500"
    r = requests.get(url)

results = r.json().get('results', [])
print(f"Total results fetched: {len(results)}")
count = 0
with open('found_proteins.txt', 'w') as f:
    for x in results:
        has_pdb = False
        for db in x.get('uniProtKBCrossReferences', []):
            if db.get('database') == 'PDB':
                has_pdb = True
                break
        if not has_pdb:
            acc = x['primaryAccession']
            name = x.get('proteinDescription', {}).get('recommendedName', {}).get('fullName', {}).get('value', 'NoName')
            f.write(f"{acc} - {name}\n")
            count += 1
            if count >= 3:
                break

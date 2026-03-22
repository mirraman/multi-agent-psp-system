import json, urllib.request

results = []
for jid in range(25, 45):
    try:
        r = urllib.request.urlopen(f'http://localhost:8000/jobs/{jid}', timeout=5)
        d = json.loads(r.read())
        val = d.get('input_value', '')[:15]
        results.append(f"job {jid}: {d.get('status'):12} | {val}")
    except Exception as e:
        pass

for l in results:
    print(l)

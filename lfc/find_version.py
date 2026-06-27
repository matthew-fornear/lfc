from pathlib import Path
s = Path("SeatingPlan.min.js").read_text(encoding="utf-8")
for term in ["i-'+", 'i-"+', "displayStyles", "status", '.o"', "chair_"]:
    idx = 0
    while True:
        i = s.find(term, idx)
        if i < 0:
            break
        print(s[max(0,i-60):i+100])
        print("---")
        idx = i + len(term)
        if idx > i + 5000:
            break

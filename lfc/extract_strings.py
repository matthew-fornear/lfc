from pathlib import Path

s = Path("SelectTickets.min.js").read_text(encoding="utf-8")
i = s.find("function pi(")
print(s[i : i + 800])
print("\n--- wi ---")
j = s.find("function wi(")
print(s[j : j + 600])

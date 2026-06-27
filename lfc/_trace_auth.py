"""Trace idmSso restore — dev only."""
import base64
import re
import urllib.parse

from curl_cffi import requests

from lfc.session import DEFAULT_HEADERS, cookies_from_requests_txt

jar = cookies_from_requests_txt("requests.txt")
s = requests.Session(impersonate="chrome146")

next_rel = "en-GB/categories/home-tickets"
auth_url = f"https://ticketing.liverpoolfc.com/idmSso/auth?act=restore&next={urllib.parse.quote(next_rel, safe='')}"
print("GET", auth_url)

r = s.get(auth_url, headers=DEFAULT_HEADERS, cookies=jar, allow_redirects=False, timeout=30)
jar.update(dict(r.cookies))
print(0, r.status_code, (r.headers.get("location") or "")[:180])

loc = r.headers.get("location") or ""
for i in range(20):
    if not loc:
        if r.status_code == 200:
            if 'name="code"' in r.text:
                m = re.search(r'name="code"\s+value="([^"]+)"', r.text)
                print("form code", m.group(1)[:50] if m else "?")
            if "productId" in r.text:
                print("got event page")
        break
    if loc.startswith("/"):
        loc = "https://ticketing.liverpoolfc.com" + loc
    r = s.get(loc, headers=DEFAULT_HEADERS, cookies=jar, allow_redirects=False, timeout=30)
    jar.update(dict(r.cookies))
    print(i + 1, r.status_code, r.url[:100])
    nloc = r.headers.get("location") or ""
    print("  ->", nloc[:150])
    if r.status_code == 200 and "idmSso" in r.url and 'name="code"' in r.text:
        break
    loc = nloc

# If we landed on idmSso callback page with form, POST it
if r.status_code == 200 and "idmSso" in r.url.lower():
    m_code = re.search(r'name="code"\s+value="([^"]+)"', r.text)
    m_state = re.search(r'name="state"\s+value="([^"]+)"', r.text)
    m_scope = re.search(r'name="scope"\s+value="([^"]+)"', r.text)
    m_iss = re.search(r'name="iss"\s+value="([^"]+)"', r.text)
    if m_code:
        data = {
            "code": m_code.group(1),
            "scope": m_scope.group(1) if m_scope else "openid ticketing fullProfile",
            "state": m_state.group(1) if m_state else "",
            "iss": m_iss.group(1) if m_iss else "https://profile.liverpoolfc.com",
        }
        print("POST idmSso", {k: v[:40] + "..." if len(v) > 40 else v for k, v in data.items()})
        r2 = s.post(
            "https://ticketing.liverpoolfc.com/idmSso",
            headers={**DEFAULT_HEADERS, "content-type": "application/x-www-form-urlencoded"},
            cookies=jar,
            data=data,
            allow_redirects=True,
            timeout=30,
        )
        jar.update(dict(r2.cookies))
        print("post result", r2.status_code, r2.url[:100], "swapi", len(jar.get("swapi_auth", "")))

from lfc.session import session_diagnostics

print(session_diagnostics(jar))

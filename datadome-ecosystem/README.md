# DataDome RE Ecosystem (glizzykingdreko)

Local copy of the open-source stack for reversing DataDome without a full browser.

## Repos (cloned)

| Directory | Purpose |
|-----------|---------|
| `new-datadome-deobfuscator/` | Deobfuscate interstitial + captcha JS; extract WASM + dynamic challenge |
| `datadome-wasm/` | Run `boring_challenge` WASM in Node |
| `datadome-encryption/` | Node signal encrypt/decrypt |
| `datadome-encryption-python/` | Python signal encrypt/decrypt (`pip install -e`) |
| `Datadome-GeeTest-Captcha-Solver/` | Slide captcha image position (Python/OpenCV) |

## Setup

```powershell
cd c:\projects\tickets\datadome-ecosystem
.\setup.ps1
```

Or manually:

```powershell
cd new-datadome-deobfuscator; npm install
cd ..\datadome-encryption; npm install
pip install -e datadome-encryption-python
pip install -r requirements.txt
```

Verify everything:

```powershell
python scripts\pipeline.py verify
```

## LFC workflow

### 1. Capture block page

```powershell
python scripts\fetch_block.py
# or fresh session:
python scripts\fetch_block.py --no-cookies
```

Saves `captures/block_<timestamp>.html`.

### 2. Parse challenge metadata

```powershell
python scripts\parse_dd.py captures\block_<timestamp>.html
```

Check `t`:
- `fe` — can attempt solve
- `bv` — IP/session burned; get new session on home IP in real browser first

### 3. Fetch challenge JS (manual or script)

From `parse_dd` output, GET `script_url` (e.g. `interstitial.captcha-delivery.com/i.js`) with curl_cffi + same cookies/UA. Save as `captures/i.js`.

### 4. Deobfuscate

```powershell
.\scripts\deobfuscate.ps1 -InputJs captures\i.js -BundleType interstitial
```

Output: `captures/deobfuscated/interstitial/report.json` with `dynamic_challenge` + `wasm`.

### 5. Run WASM PoW

```powershell
node scripts\run_wasm.js captures\deobfuscated\interstitial\report.json
```

### 6. Encrypt signals (when you have signal key/value pairs)

```python
from datadome_encryption import DataDomeEncryptor
enc = DataDomeEncryptor(hash_str, cid, ctype="interstitial")
enc.add("key", "value")
payload = enc.encrypt()
```

### 7. Slider captcha (if rt=c)

```powershell
cd Datadome-GeeTest-Captcha-Solver
python -c "from solver import GeeTestIdentifier; GeeTestIdentifier.test()"
```

## Pipeline helper

```powershell
python scripts\pipeline.py fetch
python scripts\pipeline.py parse captures\block_....html
python scripts\pipeline.py wasm --input datadome-wasm\wasm.txt
python scripts\pipeline.py encrypt-demo
python scripts\pipeline.py verify
```

## What this does NOT do yet

A full `datadome` cookie generator requires:

1. Running the deobfuscated **VM** (`vm-obj.js`) with consistent browser env
2. Building the **jsData** signal list matching that env
3. **POST** to `https://api-js.datadome.co/js/` with encrypted payload

That is ongoing RE — DataDome updates bundles frequently. The deobfuscator is maintained for that; expect to re-fetch `i.js`/`c.js` when LFC updates.

## Links

- [new-datadome-deobfuscator](https://github.com/glizzykingdreko/new-datadome-deobfuscator)
- [Breaking Down Datadome WAF (Medium)](https://glizzykingdreko.com/breaking-down-datadome-captcha-waf-d7b68cef3e21)
- [Analyzing latest VM changes (Medium)](https://medium.com/@glizzykingdreko/analyzing-datadome-latest-changes-424f385bcdd4)

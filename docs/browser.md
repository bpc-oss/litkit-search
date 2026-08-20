# Browser-assisted downloads

The PDF download chain includes a browser-assisted path for publishers that
block plain HTTP clients (ScienceDirect, Wiley, Nature, MDPI, …). It uses:

- **Node.js** (runtime) + **puppeteer-core / puppeteer-extra / stealth** (from
  the repo's `package.json`)
- **Playwright** (Python package) for page automation
- **Google Chrome** (any recent install)

This is an **optional** feature. Without it, open-access and institutional
download paths still work.

## Install

```bash
# 1. Python extra
pip install 'litkit-search[browser]'

# 2. Node.js (>= 18)
#    Windows: https://nodejs.org    macOS: brew install node    Linux: apt install nodejs
node --version

# 3. (from a source checkout) install the node sidecar
cd litkit-search
npm install            # installs puppeteer-core + stealth

# 4. Playwright browser binaries (first run downloads ~120 MB)
python -m playwright install chromium
```

## Verify

```bash
litkit-dsh doctor    # "browser chain" should show: node found; playwright installed
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `node not found` | Install Node.js and reopen your terminal |
| Playwright browser missing | `python -m playwright install chromium` |
| Downloads still failing for a publisher | The site may have changed; open an issue with the DOI and publisher |

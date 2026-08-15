# Troubleshooting

## Installation

| Symptom | Fix |
|---|---|
| `python` not found / wrong version | Install Python 3.11+; on Windows avoid the Store alias; verify `python --version` in a **new** terminal |
| `pip` installs to the wrong Python | Use `python -m pip install ...` so the interpreter matches |
| PowerShell: `pip install dist/*.whl` fails | PowerShell does not expand globs — iterate: `Get-ChildItem dist\*.whl \| ForEach-Object { pip install $_.FullName }` |
| `litkit` command not found after install | Scripts dir not on PATH — use `python -m litkit` or add `%LOCALAPPDATA%\Programs\Python\Python311\Scripts` to PATH |

## Runtime

| Symptom | Fix |
|---|---|
| `litkit doctor` shows core-dependency FAIL | Reinstall: `pip install --force-reinstall litkit-search` |
| Search returns nothing for a source | That source may be rate-limited or temporarily down — `litkit sources` shows status; retry later or narrow `-s` |
| `UnicodeEncodeError` on Windows | Already handled internally (errors="replace"); if you still see it, run `chcp 65001` |
| Verify reports an error about anystyle/GROBID | Install the tool: `gem install anystyle` or `docker run -p 8070:8070 lfoppiano/grobid` |
| Publisher PDF downloads fail | Try `litkit download` with browser chain installed (see [browser.md](browser.md)) |
| zh-search blocked | Institutional cookie expired — re-export `INSTITUTIONAL_COOKIE_FILE` after logging in |

## Network / DNS

- Some shadow-library domains are DNS-poisoned in certain regions; the
  download chain includes a DoH-based resolver as a fallback (lazy-loaded in a
  future release).
- Corporate proxies: set `HTTP_PROXY` / `HTTPS_PROXY` environment variables
  before running litkit.

## Still stuck?

Open an issue at https://github.com/bpshil/litkit-search/issues with:

1. `litkit doctor` output
2. OS + Python version
3. The exact command and full error text

# Debate Table — Enterprise Production Copy

This package contains the current Debate Table v1.2 Phase 1 text application from
Git commit `d7be33579c0f986db74c0b221b5bdf06a9d280df` on `master`. That commit has no
exact tag. Packaging did not modify the application engine, prompts, configuration,
models, thresholds, or frontend.

## Requirements

- Windows 10 or 11 (Windows 11 was used for release verification)
- Python 3.14.6 (the tested interpreter; the project declares Python 3.10+)
- Ollama running locally at `http://127.0.0.1:11434`
- `phi4:14b` and `qwen2.5:14b-instruct` installed in Ollama
- A modern browser
- Sufficient RAM or VRAM for the selected 14B models

Model weights are not included. Install the required models yourself if needed:

```powershell
ollama pull phi4:14b
ollama pull qwen2.5:14b-instruct
```

`config.json` also names `dolphin-llama3:8b` as the extractor model, but it is not
required while the default `insight_panel` setting remains `false`.

## Installation

Open PowerShell in this extracted folder and run the verified bootstrap:

```powershell
.\scripts\bootstrap.ps1
```

The bootstrap creates `.venv`, installs the pinned Windows dependency closure from
`requirements.lock.txt`, installs pytest for the offline self-check, checks Ollama,
and reports missing required models. It does not download models or edit
`config.json`.

For a runtime-only manual installation:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

## Startup

```powershell
.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:8700`. The application deliberately binds only to localhost.
Stop it with `Ctrl+C` in the PowerShell window.

Press `C` while the Debate Table browser page has focus to open the operator drawer.

## Voice status

Local Voice / TTS is not included in this production copy.
This package represents the completed v1.2 Phase 1 text application before Voice
Phase 2.

## Package scope

Included are the current runtime, frontend, configuration, dependency declarations,
bootstrap and environment-capture scripts, snapshot provenance, restore runbook, and
the complete offline test suite. Deliberately omitted are Git metadata, virtual
environments, Python and pytest caches, historical archives, audit and soak logs,
research spikes and embedding caches, superseded directives, editor state, scratch
directories, temporary logs, and local Ollama model storage. These omissions do not
change the packaged application engine.

## Verification

First verify the ZIP with the adjacent `.zip.sha256` file. In PowerShell:

```powershell
Get-FileHash .\Debate_Table_v1.2_Phase1_Production_*.zip -Algorithm SHA256
Get-Content .\Debate_Table_v1.2_Phase1_Production_*.zip.sha256
```

After extraction, verify every packaged file against `MANIFEST-SHA256.json`:

```powershell
python -c "import hashlib,json,pathlib,sys; r=pathlib.Path('.'); m=json.loads((r/'MANIFEST-SHA256.json').read_text(encoding='utf-8')); bad=[e['path'] for e in m['files'] if not (r/e['path']).is_file() or (r/e['path']).stat().st_size != e['size'] or hashlib.sha256((r/e['path']).read_bytes()).hexdigest() != e['sha256']]; print(f'{len(m[\"files\"])} files checked; {len(bad)} mismatches'); print(*bad, sep='\n'); sys.exit(bool(bad))"
```

The manifest intentionally does not hash itself. It covers every other file in the
application folder. Paths use forward slashes and are sorted deterministically.

Check the environment and run the offline test suite:

```powershell
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -m pytest tests -q -W error
```

The release baseline is `84 passed`, `0 failed`, `0 warnings`. The tests use a local
mock Ollama service and do not invoke the installed models. See
`SNAPSHOT-RESTORE.md` for the historical baseline restore record and additional
operational detail.

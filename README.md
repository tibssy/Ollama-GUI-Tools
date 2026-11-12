# Ollama GUI Tools

Registry of downloadable tools for [Ollama GUI](https://github.com/tibssy/Ollama-GUI-rs).

Each tool is a small, self-contained folder with a JSON manifest and an executable
`run` script. The app downloads the files from this repository, verifies their
SHA-256 hashes, installs them under `~/.local/share/ollama-gui/tools/`, and runs
them inside a bubblewrap sandbox using only the permissions declared in the
manifest.

## First tools

| Tool | Category | Description |
|---|---|---|
| `current_time` | core | Local date, time, timezone, and UTC offset. |
| `calculator` | core | Safe arithmetic with functions and constants. |
| `unit_convert` | core | Length, mass, temperature, volume, speed, data, time, angle. |
| `web_search` | web | DuckDuckGo search with titles, URLs, and snippets. |
| `weather` | web | Current weather and a short forecast from Open-Meteo. |
| `clipboard` | desktop | Read or write the clipboard through Noctalia, `wl-clipboard`, or `xclip`. |
| `noctalia` | desktop | Volume, brightness, network, DND, media, panels, wallpapers, workspaces, notifications, and session actions. |
| `kdeconnect` | desktop | List, ping, ring, share files or text, send SMS, lock/unlock, and list notifications on paired devices. |

All tools use only the Python standard library. Web tools need network access;
desktop tools need the system commands listed in their manifests.

## Layout

```
index.json
schema/tool.schema.json
scripts/build_index.py
scripts/selftest.py
tools/
  current_time/
    tool.json
    run
```

## Manifest

```json
{
  "name": "calculator",
  "description": "Evaluate one arithmetic expression...",
  "version": 1,
  "category": "core",
  "runtime": "python3",
  "requires": {
    "commands": ["python3"]
  },
  "sandbox": {},
  "timeout_secs": 5,
  "max_output_bytes": 4096,
  "parameters": {
    "type": "object",
    "properties": {
      "expression": {
        "type": "string",
        "description": "The expression to evaluate."
      }
    },
    "required": ["expression"]
  },
  "default_permission": "allow",
  "default_cloud_permission": "allow"
}
```

The `parameters` object is passed to Ollama as the function schema.

### Sandbox

The app runs tools with `bwrap`. Nothing is available unless declared:

| Field | Effect |
|---|---|
| `network` | Shares the network namespace. |
| `wayland` | Binds the Wayland socket. |
| `dbus` | Binds the session D-Bus socket. |
| `runtime_dir` | Binds `$XDG_RUNTIME_DIR` for compositor or shell IPC. |
| `read_paths` | Read-only bind mounts, absolute or starting with `~/`. |
| `write_paths` | Read-write bind mounts. |

The tool directory itself is read-only. `$HOME` is a scratch directory, and
`/usr`, `/lib`, `/etc`, and `/bin` are read-only. A tool that needs to share a
file declares it in `file_params`; the app binds that specific file read-only
instead of exposing the home directory.

Tools that must hand a path to a daemon outside the sandbox, such as KDE
Connect's share action, set `"preserve_file_paths": true`. The app then binds
the file at its real path and leaves the argument unchanged instead of staging
it under `/sandbox/incoming`.

### Permissions

`default_permission` applies to local models. `default_cloud_permission`
(defaults to `deny`) applies to cloud models. Both accept `allow`, `ask`, or
`deny`, and the user can change them per tool in Preferences → Tools.

`dangerous_actions` lists action values that always require confirmation, even
when the tool is set to `allow`.

## Protocol

The app writes a JSON object with the tool arguments to **stdin**. The script
must print exactly one JSON object to stdout:

```json
{"success": true, "result": "the text returned to the model"}
```

```json
{"success": false, "error": "a short explanation"}
```

Errors go to stderr only for diagnostics; the model sees the `error` field.

## Adding a tool

1. Create `tools/<id>/tool.json` and `tools/<id>/run`.
2. Make `run` executable: `chmod +x tools/<id>/run`.
3. Add the tool id and sample arguments to `scripts/selftest.py`.
4. Regenerate the index:

   ```sh
   python3 scripts/build_index.py
   ```

5. Run the checks:

   ```sh
   python3 scripts/build_index.py --check
   python3 scripts/selftest.py
   ```

6. Open a pull request. CI runs both checks.

## Requirements

The scripts target Python 3.10 or newer. Any additional command must be listed
in `requires.commands`; the app warns when something is missing and never installs
packages automatically.

## License

MIT

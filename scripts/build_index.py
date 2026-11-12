#!/usr/bin/env python3
"""Validate tool manifests and generate index.json using only the standard library."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
INDEX_PATH = ROOT / "index.json"

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
PERMISSIONS = {"allow", "ask", "deny"}
RUNTIMES = {"python3", "binary"}
SANDBOX_KEYS = {"network", "wayland", "dbus", "runtime_dir", "read_paths", "write_paths"}
MANIFEST_KEYS = {
    "name",
    "description",
    "version",
    "category",
    "runtime",
    "requires",
    "sandbox",
    "timeout_secs",
    "max_output_bytes",
    "file_params",
    "preserve_file_paths",
    "dangerous_actions",
    "parameters",
    "default_permission",
    "default_cloud_permission",
    "homepage",
    "author",
    "license",
}
CATEGORY_ORDER = {"core": 0, "web": 1, "desktop": 2, "files": 3, "system": 4, "other": 5}
MAX_MANIFEST_BYTES = 64 * 1024
MAX_SCRIPT_BYTES = 256 * 1024


class ValidationError(Exception):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def is_string_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_path_list(value, field):
    require(is_string_list(value), f"{field} must be a list of strings")
    for entry in value:
        require(entry.strip(), f"{field} entries cannot be empty")
        require("\x00" not in entry, f"{field} entries cannot contain NUL bytes")
        require(
            entry.startswith("/") or entry.startswith("~/"),
            f"{field} entry '{entry}' must be absolute or start with ~/",
        )
        parts = Path(entry.replace("~", str(Path.home()), 1)).parts
        require(
            ".." not in parts,
            f"{field} entry '{entry}' must not contain '..' components",
        )


def validate_manifest(tool_id, manifest):
    require(ID_RE.match(tool_id), f"tool directory '{tool_id}' must match {ID_RE.pattern}")
    require(isinstance(manifest, dict), "tool.json must contain a JSON object")

    unknown = set(manifest) - MANIFEST_KEYS
    require(not unknown, f"unknown manifest fields: {sorted(unknown)}")

    for field in ("name", "description", "version", "runtime", "parameters", "default_permission"):
        require(field in manifest, f"missing required field '{field}'")

    require(manifest["name"] == tool_id, f"'name' must be '{tool_id}'")

    description = manifest["description"]
    require(isinstance(description, str), "'description' must be a string")
    require(description.strip(), "'description' cannot be empty")
    require(len(description) <= 2000, "'description' is too long")

    version = manifest["version"]
    require(isinstance(version, int) and not isinstance(version, bool), "'version' must be an integer")
    require(version >= 1, "'version' must be at least 1")

    category = manifest.get("category", "other")
    require(isinstance(category, str) and category.strip(), "'category' must be a non-empty string")
    require(category in CATEGORY_ORDER, f"'category' must be one of {sorted(CATEGORY_ORDER)}")

    runtime = manifest["runtime"]
    require(runtime in RUNTIMES, f"'runtime' must be one of {sorted(RUNTIMES)}")

    parameters = manifest["parameters"]
    require(isinstance(parameters, dict), "'parameters' must be an object")
    require(parameters.get("type") == "object", "'parameters.type' must be 'object'")
    properties = parameters.get("properties", {})
    require(isinstance(properties, dict), "'parameters.properties' must be an object")
    for name, schema in properties.items():
        require(isinstance(name, str) and name, "parameter names must be non-empty strings")
        require(isinstance(schema, dict), f"parameter '{name}' schema must be an object")
        require("type" in schema, f"parameter '{name}' is missing a type")
    required = parameters.get("required", [])
    require(is_string_list(required), "'parameters.required' must be a list of strings")
    for name in required:
        require(name in properties, f"required parameter '{name}' is not declared in properties")

    default_permission = manifest["default_permission"]
    require(default_permission in PERMISSIONS, f"'default_permission' must be one of {sorted(PERMISSIONS)}")
    cloud_permission = manifest.get("default_cloud_permission", "deny")
    require(cloud_permission in PERMISSIONS, f"'default_cloud_permission' must be one of {sorted(PERMISSIONS)}")

    timeout = manifest.get("timeout_secs", 30)
    require(isinstance(timeout, int) and not isinstance(timeout, bool), "'timeout_secs' must be an integer")
    require(1 <= timeout <= 300, "'timeout_secs' must be between 1 and 300")

    max_output = manifest.get("max_output_bytes", 65536)
    require(
        isinstance(max_output, int) and not isinstance(max_output, bool),
        "'max_output_bytes' must be an integer",
    )
    require(
        1024 <= max_output <= 1024 * 1024,
        "'max_output_bytes' must be between 1024 and 1048576",
    )

    requires = manifest.get("requires", {})
    require(isinstance(requires, dict), "'requires' must be an object")
    for key in ("commands", "python", "arch"):
        if key in requires:
            require(is_string_list(requires[key]), f"'requires.{key}' must be a list of strings")
            for entry in requires[key]:
                require(entry.strip(), f"'requires.{key}' entries cannot be empty")

    sandbox = manifest.get("sandbox", {})
    require(isinstance(sandbox, dict), "'sandbox' must be an object")
    unknown = set(sandbox) - SANDBOX_KEYS
    require(not unknown, f"unknown sandbox keys: {sorted(unknown)}")
    for key in ("network", "wayland", "dbus", "runtime_dir"):
        if key in sandbox:
            require(isinstance(sandbox[key], bool), f"'sandbox.{key}' must be a boolean")
    for key in ("read_paths", "write_paths"):
        if key in sandbox:
            validate_path_list(sandbox[key], f"sandbox.{key}")

    preserve_file_paths = manifest.get("preserve_file_paths", False)
    require(
        isinstance(preserve_file_paths, bool),
        "'preserve_file_paths' must be a boolean",
    )

    file_params = manifest.get("file_params", [])
    require(is_string_list(file_params), "'file_params' must be a list of strings")
    for name in file_params:
        require(name in properties, f"file parameter '{name}' is not declared in properties")

    dangerous = manifest.get("dangerous_actions", [])
    require(is_string_list(dangerous), "'dangerous_actions' must be a list of strings")
    action_schema = properties.get("action")
    if dangerous and isinstance(action_schema, dict):
        allowed = action_schema.get("enum")
        if isinstance(allowed, list):
            for action in dangerous:
                require(
                    action in allowed,
                    f"dangerous action '{action}' is not in the action enum",
                )


def load_manifest(path):
    require(path.stat().st_size <= MAX_MANIFEST_BYTES, f"{path.name} is unreasonably large")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON in {path}: {exc}") from exc


def build_entry(tool_dir):
    tool_id = tool_dir.name
    manifest_path = tool_dir / "tool.json"
    run_path = tool_dir / "run"

    require(manifest_path.is_file(), f"{tool_id}: missing tool.json")
    require(run_path.is_file(), f"{tool_id}: missing run")

    manifest = load_manifest(manifest_path)
    validate_manifest(tool_id, manifest)

    require(run_path.stat().st_size > 0, f"{tool_id}: run is empty")
    require(
        run_path.stat().st_size <= MAX_SCRIPT_BYTES,
        f"{tool_id}: run is larger than {MAX_SCRIPT_BYTES} bytes",
    )
    with run_path.open("rb") as handle:
        first_line = handle.readline(128)
    if manifest["runtime"] == "python3":
        require(first_line.startswith(b"#!"), f"{tool_id}: run must start with a shebang")
    else:
        require(first_line.startswith(b"\x7fELF"), f"{tool_id}: run must be an ELF binary")
    if not (run_path.stat().st_mode & 0o111):
        print(f"warning: {tool_id}: run is not executable; the app installs it as 0755", file=sys.stderr)

    requires = manifest.get("requires", {})
    entry = {
        "id": tool_id,
        "name": manifest["name"],
        "description": manifest["description"],
        "version": manifest["version"],
        "category": manifest.get("category", "other"),
        "runtime": manifest["runtime"],
        "requires": {
            "commands": requires.get("commands", []),
            "python": requires.get("python", []),
            "arch": requires.get("arch", []),
        },
        "file_params": manifest.get("file_params", []),
        "dangerous_actions": manifest.get("dangerous_actions", []),
        "default_permission": manifest["default_permission"],
        "default_cloud_permission": manifest.get("default_cloud_permission", "deny"),
        "timeout_secs": manifest.get("timeout_secs", 30),
        "max_output_bytes": manifest.get("max_output_bytes", 65536),
        "files": {
            "tool.json": {
                "sha256": sha256(manifest_path),
                "size": manifest_path.stat().st_size,
            },
            "run": {
                "sha256": sha256(run_path),
                "size": run_path.stat().st_size,
            },
        },
    }
    return entry


def build_index():
    require(TOOLS_DIR.is_dir(), f"missing tools directory at {TOOLS_DIR}")
    entries = []
    for tool_dir in sorted(TOOLS_DIR.iterdir()):
        if not tool_dir.is_dir() or tool_dir.name.startswith("."):
            continue
        entries.append(build_entry(tool_dir))

    require(entries, "no tools found")
    entries.sort(key=lambda entry: (CATEGORY_ORDER.get(entry["category"], 99), entry["id"]))

    index = {
        "schema": 1,
        "tools": entries,
    }
    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if index.json is missing or out of date instead of writing it",
    )
    args = parser.parse_args()

    try:
        generated = build_index()
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if not INDEX_PATH.is_file():
            print("error: index.json is missing; run scripts/build_index.py", file=sys.stderr)
            return 1
        current = INDEX_PATH.read_text(encoding="utf-8")
        if current != generated:
            print(
                "error: index.json is out of date; run scripts/build_index.py",
                file=sys.stderr,
            )
            return 1
        print(f"index.json is up to date ({len(json.loads(generated)['tools'])} tools)")
        return 0

    INDEX_PATH.write_text(generated, encoding="utf-8")
    print(f"wrote {INDEX_PATH} ({len(json.loads(generated)['tools'])} tools)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

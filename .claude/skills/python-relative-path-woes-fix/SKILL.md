---
name: python-relative-path-woes-fix
description: |
  Fix Python "cannot find file" or "empty database" errors caused by relative path resolution
  depending on working directory. Use when: (1) database or config files not found when running
  from different directories, (2) relative paths work from one location but fail from another,
  (3) same code finds different files depending on where it's invoked, (4) monorepo or
  multiple-checkout setup where code runs from different directories. Root cause: relative
  paths resolve from current working directory, not the script/module location. Solution:
  anchor paths to source file using Path(__file__).resolve().
author: Claude Code
version: 1.0.0
date: 2026-02-21
---

# Python Relative Path Resolution Issues

## Problem

Relative paths in Python resolve from the **current working directory**, not from the script or module location. This causes files to be created or accessed in different locations depending on where the code is invoked from.

### Symptom Pattern

- Code works when running from one directory but fails from another
- "FileNotFoundError" or "No such file or directory" errors
- Database files created in unexpected locations
- Same codebase operating on different data depending on execution context
- Monorepos where services are invoked from different directories

## Context / Trigger Conditions

Use this skill when:

1. **Path-dependent failures**: Error messages like:
   - `FileNotFoundError: [Errno 2] No such file or directory: 'config.db'`
   - `IOError: [Errno 2] No such file or directory`
   - Files mysteriously not found despite existing in the codebase

2. **Working directory dependency**:
   - Running `python script.py` from `/repo/` works
   - Running from `/repo/subdir/` fails
   - Running from `/` fails with file not found

3. **Multi-location execution**:
   - Monorepo where service can be called from root or subdirectory
   - Bot/daemon invoked from systemd, cron, or different entry points
   - Code imported as library from different locations
   - CI/CD running from workspace root instead of subdirectory

4. **Database/config not persisting**:
   - Data written to `myapp.db` in one location
   - Same code reads from different `myapp.db` elsewhere
   - In-memory or empty database despite recent writes

## Solution

**Replace relative paths with paths anchored to the source file:**

### Before (Problematic):
```python
from pathlib import Path

DB_PATH = Path("polybot.db")  # ❌ Resolves from current working directory
CONFIG_PATH = Path("config.yaml")  # ❌ Different location per invocation
```

### After (Fixed):
```python
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "polybot.db"
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
```

### For Files in Parent/Sibling Directories:
```python
# If DB should be in the project root (3 levels up from src/core/script.py)
DB_PATH = Path(__file__).resolve().parent.parent.parent / "polybot.db"

# If CONFIG should be in the same directory as the module
CONFIG_DIR = Path(__file__).resolve().parent

# If DATA should be in a sibling directory
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "dataset.csv"
```

### Key Components Explained:

- `__file__`: The absolute or relative path to the current module
- `.resolve()`: Converts to absolute path (expands symlinks, removes `.` and `..`)
- `.parent`: Gets the directory containing the file
- `.parent.parent`: Goes up multiple levels as needed
- `/`: pathlib's overloaded division operator for path joining (cleaner than `os.path.join`)

## Verification

Test that paths resolve correctly from any working directory:

```bash
# Test from project root
cd /Users/abreckler/conductor/workspaces/prediction-market-analysis/papeete-v1
python polybot/main.py run

# Test from subdirectory
cd /Users/abreckler/conductor/workspaces/prediction-market-analysis/papeete-v1/polybot
python main.py run

# Test from completely different location
cd /tmp
python /Users/abreckler/conductor/workspaces/prediction-market-analysis/papeete-v1/polybot/main.py run
```

All should access the same database at `papeete-v1/polybot/polybot.db`.

## Example

**Real Case**: Trading bot database not logging trades

```python
# ❌ BROKEN: Database created at CWD, not the code directory
from pathlib import Path

class PositionStore:
    def __init__(self):
        self.db_path = Path("polybot.db")  # If started from ~/Sites, creates ~/Sites/polybot.db
        self._init_db()

# Run from ~/conductor/workspaces/...: creates DB in current dir
# Run from ~/Sites: creates DB in ~/Sites instead
# Same code, two different databases!
```

```python
# ✅ FIXED: Database always at src location
from pathlib import Path

class PositionStore:
    def __init__(self):
        # Resolves to: ~/conductor/workspaces/.../polybot/polybot.db
        # Regardless of where the code is invoked from
        self.db_path = Path(__file__).resolve().parent.parent.parent / "polybot.db"
        self._init_db()
```

## Notes

1. **Why `.resolve()`?** Some environments set `__file__` as a relative path. `.resolve()` converts to absolute and expands symlinks.

2. **IDE debugging**: When running in IDE debuggers, `__file__` sometimes behaves differently. Test with actual command-line execution.

3. **Frozen applications**: If packaging with PyInstaller or similar, `__file__` may not exist. Use alternatives:
   ```python
   import sys
   script_dir = Path(sys.argv[0]).resolve().parent
   ```

4. **Windows compatibility**: pathlib handles Windows path separators automatically (no need for `os.path.join`).

5. **Package resources**: For installed packages, use `importlib.resources` instead of `__file__`:
   ```python
   from importlib.resources import files
   data_path = files('mypackage').joinpath('data.json')
   ```

## Anti-Pattern: Don't Do This

```python
# ❌ Using absolute hardcoded paths
DB_PATH = Path("/Users/abreckler/polybot.db")  # Only works on your machine

# ❌ Using os.getcwd() to find resources
DB_PATH = Path(os.getcwd()) / "polybot.db"  # Same problem as relative paths

# ❌ Assuming execution from project root
DB_PATH = Path("polybot/polybot.db")  # Breaks when called from subdirectory
```

## References

- [Python pathlib — Object-oriented filesystem paths](https://docs.python.org/3/library/pathlib.html)
- [How to Use pathlib for File Paths in Python](https://oneuptime.com/blog/post/2026-01-27-use-pathlib-for-file-paths-python/view)
- [How to Reference Files Relatively in Python Packages](https://www.w3reference.com/blog/relative-file-paths-in-python-packages/)
- [Python pathlib: The Complete Guide for 2026](https://devtoolbox.dedyn.io/blog/python-pathlib-complete-guide)
- [importlib.resources for package resources](https://docs.python.org/3/library/importlib.resources.html)

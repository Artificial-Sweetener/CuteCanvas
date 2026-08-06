# Maintenance Tools

This directory contains repository-wide enforcement for code quality,
architectural boundaries, documentation consistency, and test selection.
Product-specific runtime and performance harnesses live with the tests that
own them under each package's `tests` directory.

## Test selection

`test.py` validates the test inventory before executing public logical targets.
It selects tests through package-owned `TEST_POLICY.toml` facts, including
consumer contract subscriptions, instead of requiring private pytest node IDs.

```powershell
.venv\Scripts\python tools\test.py list
.venv\Scripts\python tools\test.py explain packages\qpane\src\qpane\cache.py
.venv\Scripts\python tools\test.py run qpane cache integration
.venv\Scripts\python tools\test.py changed
.venv\Scripts\python tools\test.py staged --commit
```

`verify_python_wheels.py` builds QPane and CuteCanvas, proves QPane imports
without CuteCanvas installed, then installs CuteCanvas against that exact QPane
wheel with only declared dependencies. `verify_ferrastra_wheel.py` performs the
equivalent direct-wheel and source-derived-wheel proof for Ferrastra.

## Architecture governance

`check_architecture.py` validates product dependency direction, protected
Python and Rust boundaries, repository-wide structural limits, package-local
debt and waiver snapshots, and exact current fingerprints. Commit gates use the
Git index so an unstaged registry edit cannot reconcile staged source.

```powershell
.venv\Scripts\python tools\check_architecture.py
.venv\Scripts\python tools\check_architecture.py --staged
.venv\Scripts\python tools\check_architecture.py --fingerprint packages\qpane\src\qpane\viewer.py
```

Each package owns its `ARCHITECTURE_DEBT.toml` and
`ARCHITECTURE_WAIVERS.toml`. Update a debt record by replacing stale current
facts; delete resolved records. Git owns history.

## 1. `check_consistency.py` (The "Trinity" Check)

This is the primary validation tool for all three published packages. It treats
the Ferrastra, QPane, and CuteCanvas root stubs plus QPane's typed integration
SDK as the authoritative public contracts, then verifies implementation,
documentation, examples, configuration defaults, and package boundaries
against them.

**Usage:**
```powershell
.venv\Scripts\python tools\check_consistency.py
```

**Checks Performed:**
- **Implementation Reality:** Verifies every exported root-facade and QPane SDK
  symbol against its typed contract, including public class members.
- **Demo Compliance:** Ensures each package's tutorial imports only its
  supported public facade and that both product demos are present.
- **Documentation Completeness:** Requires same-block API explanations and
  meaningful narrative guide coverage for every public symbol in each package.
- **Config Accuracy:** Compares each package's documented configuration mapping
  with the exact runtime defaults.
- **Package Boundaries:** Enforces `CuteCanvas -> QPane`, rejects the reverse
  dependency, and permits CuteCanvas to consume QPane only through `qpane` or
  the explicit `qpane.sdk` namespaces.

**Output:**
- `SUCCESS`: All checks passed.
- `FAILED`: Lists specific violations (e.g., "Demo uses hidden method", "Missing doc for symbol X").

## 2. `check_api_order.py`

Enforces the physical layout of the main `qpane.py` file to match the project's architectural guidelines.

**Usage:**
```bash
python tools/check_api_order.py
```

**Checks Performed:**
- **Public API Visibility:** Ensures all methods defined in `qpane.pyi` are physically located *above* the `# Internal Implementation` banner in `qpane.py`.
- **Internal Encapsulation:** Ensures all methods *not* in `qpane.pyi` are located *below* the banner.

**Output:**
- `SUCCESS`: File layout is correct.
- `[FAIL] API Organization Violation`: Lists methods that are in the wrong section (Hidden Public API or Leaking Internal API).

## 3. `check_docstrings.py`

A linter that enforces the project's documentation standards.

**Usage:**
```bash
python tools/check_docstrings.py
```

**Checks Performed:**
- Scans every package's source and public-example directories.
- Ensures every module, class, and function has a docstring.
- Skips property setters (assuming the getter is documented) and empty `__init__.py` files.

**Output:**
- `SUCCESS`: No missing docstrings found.
- `FAILED`: Lists files and line numbers where docstrings are missing, along with a summary of the guidelines.

## 4. `add_license_headers.py`

Automates copyright compliance for the project.

**Usage:**
```bash
python tools/add_license_headers.py
```

**Actions:**
- Scans all git-tracked `.py` and `.pyi` files.
- Adds the standard GPLv3-or-later license header if it is missing.
- Updates the header if an older version is detected.

**Output:**
- Prints the path of any file that was updated or added.

## 5. `fix_encoding.py`

Ensures cross-platform compatibility by enforcing UTF-8 encoding.

**Usage:**
```bash
python tools/fix_encoding.py
```

**Actions:**
- Attempts to read every tracked Python file as UTF-8.
- If reading fails, it tries fallback encodings (like `cp1252` or `latin1`).
- If a fallback succeeds, it re-saves the file as valid UTF-8.

**Output:**
- Reports files that were converted or files that could not be recovered.

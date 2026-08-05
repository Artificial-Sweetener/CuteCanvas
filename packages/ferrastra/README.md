# Ferrastra

Ferrastra is the CPU-first, typed, spatial, revision-aware native graphics product
engine shared by QPane and CuteCanvas.

The Stage 0 package establishes an independently buildable, typed Python/native
boundary and the architecture gates required before graphics behavior is
implemented. Its public surface is package version identity.

Install a local development build from the repository root with:

```powershell
.venv\Scripts\python -m pip install -e packages\ferrastra
```

The wheel uses the CPython 3.10 stable ABI and supports Python 3.10 through
3.14 from one wheel per supported native platform. The minimum platform set is
Windows x64, Linux x64, and Apple Silicon macOS. Ferrastra does not install or
import Qt, QPane, or CuteCanvas.

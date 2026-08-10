<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/main/assets/logos/ferrastra-logo-on-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/main/assets/logos/ferrastra-logo-on-light.svg">
    <img alt="Ferrastra — oxidized image processing" src="https://raw.githubusercontent.com/Artificial-Sweetener/CuteCanvas/main/assets/logos/ferrastra-logo.svg" width="720">
  </picture>
</h1>

<p align="center">
  <a href="https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/FERRASTRA_DESIGN.md"><img src="https://img.shields.io/badge/stage-0-d97706" alt="Stage 0"></a>
  <a href="https://github.com/Artificial-Sweetener/CuteCanvas/actions/workflows/verify.yml"><img src="https://img.shields.io/github/actions/workflow/status/Artificial-Sweetener/CuteCanvas/verify.yml?branch=main&amp;label=Tests" alt="Test status"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+"></a>
  <a href="https://www.rust-lang.org/"><img src="https://img.shields.io/badge/rust-1.93.1-000000?logo=rust&amp;logoColor=white" alt="Rust 1.93.1"></a>
  <a href="https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later license"></a>
</p>

Ferrastra is the independently buildable Python/native foundation for a
CPU-first, typed, spatial graphics product engine. The current Stage 0 package
establishes its package boundary, native build, stable-ABI Python binding, and
architecture gates. Its public surface is package version identity; it does not
yet provide graphics behavior to QPane or CuteCanvas.

Install a local development build from the repository root with:

```powershell
.venv\Scripts\python -m pip install -e packages\ferrastra
```

The wheel uses the CPython 3.10 stable ABI and supports Python 3.10 through
3.14 from one wheel per supported native platform. The minimum platform set is
Windows x64, Linux x64, and Apple Silicon macOS. Ferrastra does not install or
import Qt, QPane, or CuteCanvas.

See the [Ferrastra design charter](https://github.com/Artificial-Sweetener/CuteCanvas/blob/main/FERRASTRA_DESIGN.md)
and [package source](https://github.com/Artificial-Sweetener/CuteCanvas/tree/main/packages/ferrastra)
for its planned product boundary and current Stage 0 implementation.

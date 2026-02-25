# MIXINv2

[![PyPI](https://img.shields.io/pypi/v/overlay.language)](https://pypi.org/project/overlay.language/)
[![CI](https://github.com/Atry/overlay/actions/workflows/ci.yml/badge.svg)](https://github.com/Atry/overlay/actions/workflows/ci.yml)
[![Documentation Status](https://readthedocs.org/projects/overlaylanguage/badge/?version=latest)](https://overlaylanguage.readthedocs.io/en/latest/?badge=latest)

A dependency injection framework with pytest-fixture syntax, plus a
configuration language for declarative programming.

The configuration language is designed for modularity — independent modules
compose freely without glue code, dissolving the
[Expression Problem](https://en.wikipedia.org/wiki/Expression_problem).
If you prefer declarative programming, you can even move all your business logic
from Python into MIXINv2 — it is based on
[inheritance-calculus](https://arxiv.org/abs/2602.16291), which is provably more
expressive than λ-calculus. As a bonus, your Python code
reduces to thin I/O adapters, trivially mockable, and the same MIXINv2
code runs unchanged on both sync and async runtimes
(a.k.a. [function-color](https://journal.stuffwithstuff.com/2015/02/01/what-color-is-your-function/)-blind).

```
pip install overlay.language
```

Full documentation is available at [overlaylanguage.readthedocs.io](https://overlaylanguage.readthedocs.io/).

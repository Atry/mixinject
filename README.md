# MIXINv2

[![PyPI](https://img.shields.io/pypi/v/mixinv2)](https://pypi.org/project/mixinv2/)
[![CI](https://github.com/Atry/MIXINv2/actions/workflows/ci.yml/badge.svg)](https://github.com/Atry/MIXINv2/actions/workflows/ci.yml)
[![Documentation Status](https://readthedocs.org/projects/mixinv2/badge/?version=latest)](https://mixinv2.readthedocs.io/en/latest/?badge=latest)

A dependency injection framework with pytest-fixture syntax, plus a
configuration language for declarative programming.

The configuration language is designed for modularity — independent modules
compose freely without glue code, immune to the
[Expression Problem](https://en.wikipedia.org/wiki/Expression_problem).
If you prefer declarative programming, you can even move all your business logic
from Python into MIXINv2 — it is based on
[inheritance-calculus](https://arxiv.org/abs/2602.16291), which is provably more
expressive than λ-calculus. As a bonus, your Python code
reduces to thin I/O adapters, trivially mockable, and the same MIXINv2
code runs unchanged on both sync and async runtimes
(a.k.a. [function-color](https://journal.stuffwithstuff.com/2015/02/01/what-color-is-your-function/)-blind).

```
pip install mixinv2
```

Full documentation is available at [mixinv2.readthedocs.io](https://mixinv2.readthedocs.io/).

## History

MIXINv2 is the successor to [MIXIN](https://github.com/Atry/MIXIN).

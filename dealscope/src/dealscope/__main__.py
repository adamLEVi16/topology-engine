"""Allow ``python -m dealscope`` as well as the ``dealscope`` console script.

The console script lands in Python's ``Scripts``/``bin`` directory, which is
frequently missing from PATH on Windows. Running the module directly always
works, so it is the invocation the docs lead with.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

"""Packages under ``src/`` (``model``, ``web``).

Marks ``src`` as a package so the documented ``python -m src.model.run`` /
``python -m src.web.app`` invocations work from the repository root.  The
``model`` and ``web`` packages are also importable directly (editable install
or ``PYTHONPATH=src``).
"""

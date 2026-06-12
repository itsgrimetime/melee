"""Allow `python -m src.hooks.validate_commit` for the pre-commit hook."""

from src.hooks.validate_commit import main

raise SystemExit(main())

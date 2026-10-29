# Contributing

Thanks for helping. Keep it simple:

- **No new dependencies.** Python standard library and vanilla JS only (no pip, npm or CDN in the app).
- **Two languages.** Every text a person reads goes through `tr("English", "Español")` in Python or `L("English", "Español")` in JS.
- **Few buttons.** New settings go in `data/config.json` and in [AGENTS.md](AGENTS.md), not in new screens.
- **Run the tests** before a pull request: `python3 tests.py`.
- **Never commit `data/`** or anyone's transcripts.

Questions and ideas: open an issue. Small, focused pull requests are easiest to review.

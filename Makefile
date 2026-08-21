# Local checks. This is the layer that runs BEFORE the AI review — it's free,
# instant, and deterministic. Getting it green first is what makes the AI review
# worth reading, because otherwise the passes spend their attention on lint.
#
#   make check     everything below, ~30s
#   make report    re-aggregate findings after /review-all
#
# The AI review itself runs inside Antigravity: /review-all
#
# Python config comes from .flake8 and .isort.cfg — both at 120 columns.
# EDIT THE PATH VARS BELOW to match your layout.

PY_DIRS  ?= backend tracker
WEB_DIRS ?= frontend/src

.PHONY: check fix lint imports types test sec deps migrations report blockers clean install-hooks

# ---------- deterministic layer ----------

check: imports lint types sec
	@echo "✓ static checks passed"

# isort in check mode. Reads .isort.cfg: line_length 120, multi_line_output 5,
# known_first_party = app. Fails without changing anything.
imports:
	isort --check-only --diff $(PY_DIRS)

# flake8 reads .flake8: max-line-length 120, max-doc-length 120, max-complexity 18.
# E501 is enforced (code lines) and W505 is enforced (docstring and comment lines),
# so nothing else in this repo needs to think about line width.
lint:
	flake8 $(PY_DIRS)
	npx eslint $(WEB_DIRS) --max-warnings=0

# Highest-ROI check in this file. Catches the class of bug that reads fine.
types:
	mypy $(PY_DIRS) --ignore-missing-imports --show-error-codes
	npx tsc --noEmit

test:
	pytest -q
	npm test -- --run

# Pattern-matchable vulnerabilities and secrets. Not the AI's job.
sec:
	@command -v semgrep >/dev/null || { echo "pip install semgrep"; exit 1; }
	semgrep --config p/default --config p/python --config p/react \
	        --config p/secrets --config p/owasp-top-ten \
	        --config .semgrep/ --error --quiet
	@command -v gitleaks >/dev/null && gitleaks detect --no-banner --redact || \
	  echo "(gitleaks not installed, skipping — brew install gitleaks)"

deps:
	pip-audit --strict --desc
	npm audit --audit-level=high

# Migration safety is deterministic. Don't ask an LLM whether a migration locks.
migrations:
	@if [ -f manage.py ]; then \
	  python manage.py makemigrations --check --dry-run; \
	  python manage.py lintmigrations --warnings-as-errors; \
	fi
	@if ls alembic/versions/*.py >/dev/null 2>&1; then \
	  alembic upgrade head --sql > /tmp/upgrade.sql && squawk /tmp/upgrade.sql; \
	fi

# isort rewrites imports in place; flake8 only reports, it never fixes.
# Removing E501 from ignore means flake8 now flags every code line over 120 —
# expect a one-time cleanup, and land it in its own commit.
fix:
	isort $(PY_DIRS)
	npx eslint $(WEB_DIRS) --fix
	@echo "isort and eslint applied. flake8 findings must be fixed by hand:"
	@flake8 $(PY_DIRS) || true

# ---------- AI layer ----------
#
# There is no shell target here. In Antigravity the review runs inside the agent:
#
#   /review-all              six subagents in parallel, one ranked list
#   /review-docstrings       just the docstring pass
#   /review-frontend-live    load the real pages in a browser and verify them
#
# Re-aggregate existing findings without re-reviewing:

report:
	python3 ~/.gemini/config/skills/review-all/scripts/render_review.py

blockers:
	python3 ~/.gemini/config/skills/review-all/scripts/render_review.py --important

# ---------- setup ----------

install-hooks:
	pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push

pyinstaller:
	@echo "Building Python tracker with PyInstaller..."
	cd tracker && \
	../tracker/.venv/bin/pyinstaller --noconfirm --onefile --name logline_tracker \
		--add-data "sync/agent.py:sync" \
		--hidden-import "tracker.sync.agent" \
		entry.py
	@echo "✓ PyInstaller build complete"

package: pyinstaller
	cd tracker-app && RELEASE=1 ./build.sh
	@echo "Packaging DMG..."
	mkdir -p dist
	rm -f dist/LoglineSync.dmg
	hdiutil create -volname "LoglineSync" -srcfolder tracker-app/LoglineSync.app -ov -format UDZO dist/LoglineSync.dmg
	@echo "✓ DMG created: dist/LoglineSync.dmg"

clean:
	rm -rf .review

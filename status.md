# Project Status - RouteFinder2

## 🎯 Current Objectives
- None (All current objectives met).

## 🚀 Completed Features
- Fixed database engine resolution in `RouteFinder/settings.py` so PostgreSQL is properly recognized from either `DATABASE_URL`/`POSTGRES_URL` or individual Postgres environment variables (`POSTGRES_DB`/`DATABASE_NAME`, `POSTGRES_USER`/`DATABASE_USER`, `POSTGRES_PASSWORD`/`DATABASE_PASSWORD`, `DATABASE_HOST`/`POSTGRES_HOST`/`DB_HOST`, `DATABASE_PORT`/`POSTGRES_PORT`/`DB_PORT`).
- Prevented unexpanded Kubernetes dependent environment variable templates (e.g. `postgres://$(POSTGRES_USER)...`) from breaking database initialization or causing unexpected fallback to SQLite.
- Fixed Kubernetes `web-deployment.yaml` manifest by explicitly defining dependent environment variables using `valueFrom` prior to `DATABASE_URL`.
- Enhanced database connection pre-flight logging in `RouteFinderWeb/apps.py` and `doctor.py` to clearly report the active database engine, host, and database name during startup diagnostics.
- Added comprehensive unit tests in `RouteFinderWeb/tests.py` covering all database resolution scenarios (PostgreSQL URLs, SQLite URLs, individual Postgres variables, unexpanded K8s variables, zero-config local fallback).
- Fixed issue where the AI settings page did not display the new service provider, API URL, and model fields due to the Service Worker caching the profile page.
- Incremented PWA cache version to `routefinder-v4` to force a cache purge and update across client browsers.
- Added comprehensive unit tests (`ProfileViewTests`) to verify the rendering of the AI settings fields on the profile page.
- Baseline project setup and environment diagnostics.
- Fixed syntax error in `views.py` and updated `tests.py` to match current signatures.
- Implemented AI Settings in User Profile with a tabbed UI (Address, Defaults, AI Settings).
- Added switch toggles for AI Enablement, AI Deep Thinking, and a range slider for Thinking Effort (1-100).
- Integrated user profile settings into `AIService` to bypass queries when disabled and apply thinking configurations (think parameter, custom instruction budget, temperature adjustment).
- Fixed a `TemplateSyntaxError` on the Discover page caused by an unclosed `{% if perform_search %}` tag and malformed `div`/`script` elements.
- Added support for custom Ollama URLs, custom models, and standard OpenAI-compatible API URLs by introducing `ai_provider`, `ai_api_url`, `ai_model`, and `ai_api_key` fields to `UserProfile`.
- Updated the profile settings page dynamically to show/hide provider-specific settings (e.g. hiding API key for Ollama, updating Base URL label).
- Updated `UserProfile` and related database models to declare index properties explicitly using `db_index=True` on ForeignKey and OneToOneField relationships.
- Refactored monolithic views logic by splitting `views.py` into a clean package (`views/base_views.py`, `views/discovery_views.py`, `views/auth_views.py`, `views/__init__.py`).
- Set up a startup diagnostics process in `apps.py` to perform database pre-flight checks and validate critical configurations (e.g. Google Maps key, Secret Key validation).
- Implemented typing annotations across all python models, services, backends, forms, and views.
- Introduced `MOCK_MODE=True` settings and service support to geolocode, query listings/clusters, solve TSP route coordinates, and analyze targets completely offline.
- Added a diagnostic health utility script `doctor.py`.
- Developed database backup and restoration script `backup_db.py` (with SQLite/PostgreSQL, timestamping, and compression support) and documented it in `README.md`.
- Excluded the `backups/` directory in `.gitignore`.
- Configured non-root execution permissions for container security in `Dockerfile`.
- Partitioned development volume mounts out of `docker-compose.yml` into `docker-compose.override.yml`.

## 🛠️ Active Tasks
- None

## 📌 Architectural Notes
- Database: SQLite (local testing fallback), PostgreSQL (production via DATABASE_URL or individual POSTGRES_* / DATABASE_* variables)
- Verification Command: `$env:DATABASE_URL="sqlite:///db.sqlite3"; python manage.py test`

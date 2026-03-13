# Cultnova Backend

Django CMS that manages blog and project content and generates static detail pages.

## Local run (prod-like)

1. Create and activate a virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and adjust values as needed.
   `.env.example` is the tracked template and source of truth for available app settings.
   Local `.env` may be shorter because some settings have defaults in `cultnova/settings.py`; keep only safe sample values and placeholders in the template.
4. Run:
   `python manage.py migrate`
5. Optional static build:
   `python manage.py collectstatic --noinput`
6. Start:
   `python manage.py runserver 127.0.0.1:8010`

## Blog static generation

- Single article generation happens automatically by signals on article/block save/delete.
- Full rebuild:
  `python manage.py rebuild_articles_html`
- Rebuild and remove unpublished pages:
  `python manage.py rebuild_articles_html --delete-unpublished`

Generated output format:

- `articles/<slug>/index.html` (public URL: `/articles/<slug>/`)

## Projects static generation

- Single project generation happens automatically by signals on project/media save/delete.
- Full rebuild:
  `python manage.py rebuild_projects_html`
- Rebuild and remove unpublished pages:
  `python manage.py rebuild_projects_html --delete-unpublished`

Generated output format:

- `projects/<slug>/index.html` (public URL: `/projects/<slug>/`)

## Sitemap generation

- Backend owns the final public `sitemap.xml`.
- Source of truth is the current content of `GENERATED_HTML_PAGES_PATH`.
- Static `index.html` pages are discovered from disk, `noindex` pages are skipped, and article/project detail page `lastmod` values are taken from the database.
- Manual rebuild:
  `python manage.py rebuild_sitemap`
- `sitemap.xml` is refreshed automatically after article/project publish, unpublish, slug change, delete, and content-block updates.

## SEO in article pages

`templates/article_detail.html` renders common SEO tags (canonical, robots, OG/Twitter).
Current code provides a minimal `article.seo` dict (title/description) and falls back to defaults for other tags.

## SEO and HTML body in project pages

- `templates/project_detail.html` renders canonical, robots, OG/Twitter meta, and JSON-LD for project pages.
- Project content is managed through:
  - `Projects.body_html` (sanitized rich HTML),
  - sidebar media blocks (`image` / `video`) with `media_alt` and `caption`,
  - SEO fields (`seo_title`, `seo_description`, `seo_keywords`, `seo_robots`, `canonical_url`).

## Production deploy (one-click)

1. Create local deploy config from `.env.deploy.example`:
   `copy .env.deploy.example .env.deploy`
2. Fill `SSH_PASS` in `.env.deploy`.
3. Run deploy:
   `powershell -ExecutionPolicy Bypass -File tools/deploy_prod.ps1`

Options:

- Run migrations: `powershell -ExecutionPolicy Bypass -File tools/deploy_prod.ps1 -RunMigrations`
- Skip smoke checks: `powershell -ExecutionPolicy Bypass -File tools/deploy_prod.ps1 -SkipSmoke`

Deploy behavior:

- Deploy always syncs remote Python dependencies from `requirements.txt`.
- Deploy checks for pending migrations before rebuilding generated pages.
- Deploy always runs `python manage.py collectstatic --noinput --clear` on the remote CMS app.
- Deploy always runs:
  `python manage.py rebuild_articles_html --delete-unpublished`
  `python manage.py rebuild_projects_html --delete-unpublished`
  `python manage.py rebuild_sitemap`
- CMS/admin static is published through Django staticfiles into `STATIC_ROOT`.
- Public site assets managed by this repo are synced from `tools/public_static_manifest.json`.
- Only repo-managed public assets are synced or pruned; root-level site files that are not present in this repo are left untouched.
- Deploy resolves the actual `GENERATED_HTML_PAGES_PATH` on the server and copies `sitemap.xml` into the public site root when the generation directory differs from `REMOTE_SITE_ROOT`.
- If pending migrations are detected and `-RunMigrations` was not provided, deploy stops with a clear message and must be re-run with `-RunMigrations`.
- For the current blog HTML-body / WYSIWYG release, use:
  `powershell -ExecutionPolicy Bypass -File tools/deploy_prod.ps1 -RunMigrations`

Manual SSH / rollback helper:

- Default mode (auto-loads `.env.deploy` from repo root):
  `python tools/ssh_run.py "echo connected && whoami"`
- Explicit config path:
  `python tools/ssh_run.py --config .env.deploy "echo connected && whoami"`

Rollback hints printed by `tools/deploy_prod.ps1` are intended to be run from repo root and now work without manually exporting `SSH_HOST`, `SSH_USER`, or `SSH_PASS`.

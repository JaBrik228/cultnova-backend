# Cultnova Backend

Django CMS that manages blog and project content and generates static article pages.

## Local run (prod-like)

1. Create and activate a virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Configure env from `.env.example`.
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

## SEO in article pages

`templates/article_detail.html` renders common SEO tags (canonical, robots, OG/Twitter).
Current code provides a minimal `article.seo` dict (title/description) and falls back to defaults for other tags.

## Production deploy (one-click)

1. Create local deploy config from `.env.deploy.example`:
   `copy .env.deploy.example .env.deploy`
2. Fill `SSH_PASS` in `.env.deploy`.
3. Run deploy:
   `powershell -ExecutionPolicy Bypass -File tools/deploy_prod.ps1`

Options:

- Run migrations: `powershell -ExecutionPolicy Bypass -File tools/deploy_prod.ps1 -RunMigrations`
- Skip smoke checks: `powershell -ExecutionPolicy Bypass -File tools/deploy_prod.ps1 -SkipSmoke`

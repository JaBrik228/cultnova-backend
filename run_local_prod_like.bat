@echo off
cd /d C:\Users\JaBrik\Documents\php\cultnova-backend
set DEBUG=False
set ALLOWED_HOSTS=cms.cultnova.ru,localhost,127.0.0.1
set CSRF_TRUSTED_ORIGINS=https://cms.cultnova.ru,http://127.0.0.1:8010,http://localhost:8010
set ADMIN_URL=backend-admin/
set GENERATED_HTML_PAGES_PATH=C:/Users/JaBrik/Documents/php/cultnova-backend/local_generated_pages
set SITE_PUBLIC_BASE_URL=https://cultnova.ru
set SECRET_KEY=local-prod-like-secret-key
if not exist C:\Users\JaBrik\Documents\php\cultnova-backend\local_generated_pages mkdir C:\Users\JaBrik\Documents\php\cultnova-backend\local_generated_pages
if not exist C:\Users\JaBrik\Documents\php\cultnova-backend\staticfiles mkdir C:\Users\JaBrik\Documents\php\cultnova-backend\staticfiles
"C:\Users\JaBrik\Documents\php\cultnova-backend\.venv_local_prodtest2\Scripts\python.exe" manage.py collectstatic --noinput 1>>"C:\Users\JaBrik\Documents\php\cultnova-backend\runserver_prod_like.out.log" 2>>"C:\Users\JaBrik\Documents\php\cultnova-backend\runserver_prod_like.err.log"
"C:\Users\JaBrik\Documents\php\cultnova-backend\.venv_local_prodtest2\Scripts\python.exe" manage.py runserver 127.0.0.1:8010 --insecure 1>>"C:\Users\JaBrik\Documents\php\cultnova-backend\runserver_prod_like.out.log" 2>>"C:\Users\JaBrik\Documents\php\cultnova-backend\runserver_prod_like.err.log"

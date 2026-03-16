from django.urls import path

from core import views

app_name = "core"


urlpatterns = [
    path("sitemap/", views.sitemap_page, name="sitemap_page"),
]

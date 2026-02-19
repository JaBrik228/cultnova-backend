from django.urls import path
from . import views

app_name = 'blog'


urlpatterns = [
    path('api/articles/', views.get_articles_list, name='articles_list'),
    path('api/articles/<slug:slug>/', views.get_article_detail, name='article_detail'),
]

from django.urls import path
from . import views

app_name = 'projects'


urlpatterns = [
    path('api/projects/categories', views.get_all_categories, name='get_all_categories'),
    path('api/projects/<slug:slug>',views.get_projects_by_category, name='get_projects_by_category'),
    path('api/projects/detail/<slug:slug>',views.get_projects_details, name='get_projects_details'),
]

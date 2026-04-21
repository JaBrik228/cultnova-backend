from django.urls import path

from . import views

app_name = "projects"


urlpatterns = [
    path("api/projects/categories", views.get_all_categories, name="get_all_categories"),
    path("api/projects/", views.get_all_projects, name="get_all_projects"),
    path(
        "api/projects/service-page/<slug:slug>/",
        views.get_service_page_projects,
        name="get_service_page_projects",
    ),
    path("api/projects/category/<slug:slug>/", views.get_projects_by_category, name="get_projects_by_category_explicit"),
    path("api/projects/<slug:slug>", views.get_projects_by_category, name="get_projects_by_category"),
    path("api/projects/detail/<slug:slug>", views.get_projects_details, name="get_projects_details"),
    path("api/projects/detail/<slug:slug>/full", views.get_project_detail_full, name="get_project_detail_full"),
    path("projects/", views.get_projects_list, name="projects_list"),
    path("projects/category/<slug:slug>/", views.get_projects_category_list, name="projects_category_list"),
    path("projects/<slug:slug>/", views.get_project_detail, name="project_detail"),
]

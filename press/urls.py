from django.urls import path

from . import views

app_name = "press"


urlpatterns = [
    path("api/press/", views.get_press_feed, name="feed"),
]


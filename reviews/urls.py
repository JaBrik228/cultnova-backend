from django.urls import path

from . import views

app_name = "reviews"


urlpatterns = [
    path("api/reviews/home/", views.get_home_reviews, name="home_feed"),
]


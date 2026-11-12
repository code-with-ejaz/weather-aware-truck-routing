from django.urls import path

from . import views

urlpatterns = [
    path("routes/", views.routes_view, name="routes"),
    path("health/", views.health_view, name="health"),
]

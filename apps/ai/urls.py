from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("consultar/", views.consult_cfo, name="consult"),
]
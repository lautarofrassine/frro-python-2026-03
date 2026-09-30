from django.urls import path

from . import views

app_name = 'atencion'

urlpatterns = [
    path('triage/', views.triage_view, name='triage'),
]

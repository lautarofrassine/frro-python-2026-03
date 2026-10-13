from django.urls import path

from . import views

app_name = 'atencion'

urlpatterns = [
    path('consultas/', views.consultas_view, name='consultas'),
    path('triage/', views.triage_view, name='triage'),
    path('confirmar-turno/', views.confirmar_turno_seleccionado_view, name='confirmar_turno'),
]

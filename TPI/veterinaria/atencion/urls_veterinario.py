"""Pantallas de los veterinarios (/veterinario/...)."""
from django.urls import path

from . import views

app_name = 'veterinario'

urlpatterns = [
    path('agenda/', views.agenda_view, name='agenda'),
    path('turnos/<int:turno_id>/', views.vet_turno_view, name='turno'),
    path('historias/', views.historias_view, name='historias'),
    path(
        'historias/<int:mascota_id>/',
        views.historia_view,
        name='historia',
    ),
    path(
        'historias/<int:mascota_id>/nueva/',
        views.entrada_nueva_view,
        name='entrada_nueva',
    ),
    path(
        'historias/entradas/<int:entrada_id>/editar/',
        views.entrada_editar_view,
        name='entrada_editar',
    ),
]

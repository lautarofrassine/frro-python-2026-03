from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'clinica'

urlpatterns = [
    path('registro/', views.registro_view, name='registro'),
    path(
        'ingresar/',
        views.IngresarView.as_view(),
        name='ingresar',
    ),
    path('salir/', auth_views.LogoutView.as_view(), name='salir'),
    path('panel/', views.panel_view, name='panel'),
    path('mascotas/', views.mascotas_view, name='mascotas'),
    path(
        'mascotas/nueva/', views.mascota_nueva_view, name='mascota_nueva',
    ),
    path(
        'mascotas/<int:mascota_id>/editar/',
        views.mascota_editar_view,
        name='mascota_editar',
    ),
    path(
        'mascotas/<int:mascota_id>/baja/',
        views.mascota_baja_view,
        name='mascota_baja',
    ),
    path('vacunas/', views.vacunas_view, name='vacunas'),
    path(
        'vacunas/reservar/',
        views.vacuna_reservar_view,
        name='vacuna_reservar',
    ),
    path(
        'vacunas/turno/<int:turno_id>/',
        views.vacuna_turno_view,
        name='vacuna_turno',
    ),
]

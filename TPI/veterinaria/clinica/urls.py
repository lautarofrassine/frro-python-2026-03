from django.contrib.auth import views as auth_views
from django.urls import path

from clinica.forms import LoginForm

from . import views

app_name = 'clinica'

urlpatterns = [
    path('registro/', views.registro_view, name='registro'),
    path(
        'ingresar/',
        auth_views.LoginView.as_view(
            template_name='clinica/ingresar.html',
            authentication_form=LoginForm,
            redirect_authenticated_user=True,
        ),
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
]

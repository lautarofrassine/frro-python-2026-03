from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'atencion'

urlpatterns = [
    path('consultas/', views.consultas_view, name='consultas'),
    path('urgencia/', views.urgencia_view, name='urgencia'),
    path(
        'urgencia/confirmar/',
        views.urgencia_confirmar_view,
        name='urgencia_confirmar',
    ),
    # El triage ahora vive en Urgencia; se conserva la direccion vieja.
    path(
        'triage/',
        RedirectView.as_view(pattern_name='atencion:urgencia'),
        name='triage',
    ),
    path('turnos/nuevo/', views.turno_nuevo_view, name='turno_nuevo'),
    path(
        'turnos/nuevo/confirmar/',
        views.turno_confirmar_view,
        name='turno_confirmar',
    ),
    path(
        'turnos/<int:turno_id>/cancelar/',
        views.turno_cancelar_view,
        name='turno_cancelar',
    ),
]

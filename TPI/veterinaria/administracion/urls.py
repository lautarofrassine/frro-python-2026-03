"""Pagos del dueño, bajo /cuenta/pagos/."""
from django.urls import path

from . import views

app_name = 'pagos'

urlpatterns = [
    path('', views.mis_pagos_view, name='lista'),
    path('retorno/', views.retorno_view, name='retorno'),
    path('<int:pago_id>/', views.confirmacion_view, name='confirmacion'),
    path('<int:pago_id>/pagar/', views.pagar_view, name='pagar'),
    path(
        '<int:pago_id>/en-clinica/',
        views.en_clinica_view,
        name='en_clinica',
    ),
    path(
        '<int:pago_id>/comprobante/',
        views.comprobante_view,
        name='comprobante',
    ),
]

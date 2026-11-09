"""Integracion con Mercado Pago Checkout Pro (SDK oficial `mercadopago`).

Todo lo que habla con la API de Mercado Pago esta aca; las vistas no la
llaman directamente.

Flujo:
1. crear_preferencia: crea la preferencia con el monto a pagar y
   external_reference = id del Pago, y devuelve la URL a la que se
   redirige al dueño.
2. Mercado Pago lo devuelve a /cuenta/pagos/retorno/ con payment_id.
3. verificar_y_registrar_pago consulta ese pago en la API (nunca se
   confia en los parametros de la URL de retorno), valida estado,
   referencia y monto, y recien ahi marca el Pago como PAGADO.

Credenciales: MP_ACCESS_TOKEN y MP_PUBLIC_KEY (variables de entorno). Si
no estan, o Mercado Pago no responde, se lanza MercadoPagoError y la app
ofrece pagar en la clinica.
"""
import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import mercadopago
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from mercadopago.config import RequestOptions

from administracion.models import Pago
from administracion.services.pagos import (
    CONSULTA,
    GUARDIA,
    VACUNACION,
    PagoError,
    PagoNoEncontrado,
    marcar_pagado,
    tipo_servicio,
    validar_pago_online,
)

logger = logging.getLogger(__name__)

# Segundos que se espera a Mercado Pago antes de ofrecer pagar en la
# clinica.
TIMEOUT_SEGUNDOS = 15.0
MENSAJE_NO_DISPONIBLE = (
    'El pago online no está disponible en este momento. Podés pagar en '
    'la clínica el día de la atención.'
)
HOSTS_LOCALES = ('localhost', '127.0.0.1', '0.0.0.0', '::1')

APROBADO = 'aprobado'
PENDIENTE = 'pendiente'
RECHAZADO = 'rechazado'
# status de un pago de Mercado Pago que todavia puede aprobarse.
ESTADOS_MP_PENDIENTES = ('pending', 'in_process', 'authorized', 'in_mediation')


class MercadoPagoError(Exception):
    """Mercado Pago no esta configurado, no respondio o respondio algo
    inesperado. El mensaje es para el usuario."""


def esta_configurado():
    return bool(getattr(settings, 'MP_ACCESS_TOKEN', ''))


def es_modo_prueba():
    """Las credenciales de prueba "clasicas" empiezan con TEST-. Las de
    un usuario vendedor de prueba empiezan con APP_USR- como las reales,
    y con esas se usa init_point."""
    return settings.MP_ACCESS_TOKEN.startswith('TEST-')


def _sdk():
    if not esta_configurado():
        raise MercadoPagoError(MENSAJE_NO_DISPONIBLE)
    return mercadopago.SDK(
        settings.MP_ACCESS_TOKEN,
        request_options=RequestOptions(connection_timeout=TIMEOUT_SEGUNDOS),
    )


def _titulo(pago):
    turno = pago.turno
    cuando = date_format(timezone.localtime(turno.fecha_hora), 'd/m/Y H:i')
    servicio = {
        GUARDIA: 'Guardia',
        VACUNACION: 'Vacunación',
        CONSULTA: 'Consulta',
    }[tipo_servicio(turno)]
    return (
        f'{servicio} de {turno.mascota.nombre} con '
        f'{turno.veterinario.nombre} - {cuando}'
    )


def _admite_auto_return(url):
    """Mercado Pago rechaza auto_return si la URL de exito no es publica
    (localhost o 127.0.0.1). En desarrollo no se manda: el comprador
    vuelve con el boton "Volver al sitio" de Mercado Pago."""
    partes = urlsplit(url)
    return partes.scheme == 'https' and partes.hostname not in HOSTS_LOCALES


def _llamar(funcion, *args):
    """Llama al SDK; cualquier falla de red o del SDK es MercadoPagoError."""
    try:
        resultado = funcion(*args)
    except Exception:  # requests, timeouts o errores del SDK
        logger.exception('Error al llamar a Mercado Pago')
        raise MercadoPagoError(MENSAJE_NO_DISPONIBLE)
    if not isinstance(resultado, dict):
        raise MercadoPagoError(MENSAJE_NO_DISPONIBLE)
    return resultado.get('status'), resultado.get('response') or {}


def crear_preferencia(pago, request):
    """Crea la preferencia de Checkout Pro para un pago PENDIENTE de un
    turno futuro, guarda mp_preference_id y devuelve la URL de pago.
    Lanza PagoError si el pago no se puede pagar online y
    MercadoPagoError si Mercado Pago no esta disponible."""
    validar_pago_online(pago)
    sdk = _sdk()
    url_retorno = request.build_absolute_uri(reverse('pagos:retorno'))
    datos = {
        'items': [{
            'id': str(pago.pk),
            'title': _titulo(pago),
            'quantity': 1,
            'currency_id': 'ARS',
            'unit_price': float(pago.monto_a_pagar),
        }],
        'external_reference': str(pago.pk),
        'back_urls': {
            'success': url_retorno,
            'failure': url_retorno,
            'pending': url_retorno,
        },
        'statement_descriptor': 'CLINICAVET24',
    }
    if _admite_auto_return(url_retorno):
        datos['auto_return'] = 'approved'

    status, respuesta = _llamar(sdk.preference().create, datos)
    if status == 400 and 'auto_return' in datos:
        # Respaldo: si igual rechaza auto_return, se crea sin el.
        datos.pop('auto_return')
        status, respuesta = _llamar(sdk.preference().create, datos)
    if status not in (200, 201) or not respuesta.get('id'):
        logger.error('Mercado Pago rechazo la preferencia: %s %s',
                     status, respuesta)
        raise MercadoPagoError(MENSAJE_NO_DISPONIBLE)

    url = (
        respuesta.get('sandbox_init_point') if es_modo_prueba() else None
    ) or respuesta.get('init_point')
    if not url:
        raise MercadoPagoError(MENSAJE_NO_DISPONIBLE)
    pago.mp_preference_id = respuesta['id']
    pago.save(update_fields=['mp_preference_id'])
    return url


def _monto(valor):
    try:
        return Decimal(str(valor)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def verificar_y_registrar_pago(payment_id, dueno=None):
    """Consulta el pago `payment_id` en Mercado Pago y, si esta aprobado
    y su external_reference y su monto coinciden con un Pago PENDIENTE,
    lo marca PAGADO (metodo MERCADO_PAGO, fecha, comprobante y
    mp_payment_id). Es idempotente: si ya estaba PAGADO no hace nada.

    Devuelve (resultado, pago), con resultado 'aprobado', 'pendiente' o
    'rechazado'. Con `dueno`, el pago tiene que ser suyo (si no,
    PagoNoEncontrado). Lanza PagoError si los datos no coinciden y
    MercadoPagoError si no se pudo consultar."""
    if not str(payment_id or '').isdigit():
        raise PagoError('Mercado Pago no informó un pago válido.')
    sdk = _sdk()
    status, datos = _llamar(sdk.payment().get, str(payment_id))
    if status != 200:
        logger.error('No se pudo consultar el pago %s: %s %s',
                     payment_id, status, datos)
        raise MercadoPagoError(
            'No pudimos verificar el pago con Mercado Pago. Si se debitó, '
            'comunicate con la clínica.'
        )

    referencia = str(datos.get('external_reference') or '')
    if not referencia.isdigit():
        raise PagoError('El pago de Mercado Pago no corresponde a un turno.')
    with transaction.atomic():
        pagos = Pago.objects.select_for_update().select_related(
            'turno', 'turno__mascota',
        )
        if dueno is not None:
            pagos = pagos.filter(turno__mascota__dueno=dueno)
        pago = pagos.filter(pk=int(referencia)).first()
        if pago is None:
            raise PagoNoEncontrado('El pago no existe.')

        estado_mp = datos.get('status')
        if estado_mp != 'approved':
            if estado_mp in ESTADOS_MP_PENDIENTES:
                return PENDIENTE, pago
            return RECHAZADO, pago
        if pago.estado == Pago.Estado.PAGADO:
            return APROBADO, pago  # ya registrado: no se duplica nada
        if pago.estado != Pago.Estado.PENDIENTE:
            raise PagoError(
                'Este pago ya no estaba pendiente. Comunicate con la '
                'clínica para que revisen el cobro.'
            )
        if _monto(datos.get('transaction_amount')) != pago.monto_a_pagar:
            logger.error('Monto de Mercado Pago distinto en el pago %s: %s',
                         pago.pk, datos.get('transaction_amount'))
            raise PagoError(
                'El monto informado por Mercado Pago no coincide con el '
                'del turno. Comunicate con la clínica.'
            )
        marcar_pagado(pago, Pago.Metodo.MERCADO_PAGO, str(datos.get('id')))
    return APROBADO, pago

"""Pagos del dueño (/cuenta/pagos/...). Sin logica de negocio: todo pasa
por administracion.services.pagos y mercadopago_service."""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST 


from administracion.services.mercadopago_service import (
    MercadoPagoError,
    crear_preferencia,
    sincronizar_pago,
    esta_configurado,
    verificar_y_registrar_pago,
)
from administracion.services.pagos import (
    PagoError,
    PagoNoEncontrado,
    motivo_para_no_pagar_online,
    obtener_pago_de_dueno,
    pagos_del_dueno,
)
from clinica.views import dueno_requerido

MENSAJE_PAGAR_EN_CLINICA = (
    'Turno reservado. Podés pagarlo en la clínica el día de la atención o '
    'más tarde desde Mis pagos.'
)


def _pago_o_404(dueno, pago_id):
    try:
        return obtener_pago_de_dueno(dueno, pago_id)
    except PagoNoEncontrado:
        raise Http404('Pago no encontrado.')


@dueno_requerido
def mis_pagos_view(request, dueno):
    if esta_configurado():
        for pago in pagos_del_dueno(dueno)['pendientes']:
            sincronizar_pago(pago)
    return render(request, 'administracion/mis_pagos.html', {
        **pagos_del_dueno(dueno),
        'pago_online_disponible': esta_configurado(),
    })


@dueno_requerido
def confirmacion_view(request, dueno, pago_id):
    pago = _pago_o_404(dueno, pago_id)
    if esta_configurado():
        sincronizar_pago(pago)
        pago = _pago_o_404(dueno, pago_id)  # recarga con el estado actualizado
    return render(request, 'administracion/confirmacion.html', {
        'pago': pago,
        'turno': pago.turno,
        'motivo_no_pagar': motivo_para_no_pagar_online(pago),
        'pago_online_disponible': esta_configurado(),
    })

@dueno_requerido
def en_clinica_view(request, dueno, pago_id):
    """"Pagar en la clinica el dia de la atencion": no cambia nada, solo
    lleva a Mis consultas con el aviso."""
    _pago_o_404(dueno, pago_id)
    messages.success(request, MENSAJE_PAGAR_EN_CLINICA)
    return redirect('atencion:consultas')


@require_POST
@dueno_requerido
def pagar_view(request, dueno, pago_id):
    """Crea la preferencia y redirige a Mercado Pago. Si no se puede,
    vuelve a la confirmacion con el mensaje y la opcion de pagar en la
    clinica."""
    pago = _pago_o_404(dueno, pago_id)
    try:
        url = crear_preferencia(pago, request)
    except (PagoError, MercadoPagoError) as error:
        messages.error(request, str(error))
        return redirect('pagos:confirmacion', pago_id=pago.pk)
    return redirect(url)


@dueno_requerido
def retorno_view(request, dueno):
    """Mercado Pago devuelve al dueño aca. El resultado sale de consultar
    la API, no de los parametros de la URL."""
    print('RETORNO GET:', dict(request.GET))
    payment_id = (
        request.GET.get('payment_id') or request.GET.get('collection_id')
    )
    contexto = {'resultado': 'rechazado', 'pago': None, 'mensaje': ''}
    try:
        if payment_id and payment_id != 'null':
            resultado, pago = verificar_y_registrar_pago(payment_id, dueno)
            contexto.update(resultado=resultado, pago=pago)
        elif request.GET.get('external_reference'):
            # Volvio sin pagar (por ejemplo, con "Volver al sitio").
            contexto['pago'] = obtener_pago_de_dueno(
                dueno, request.GET['external_reference'],
            )
    except PagoNoEncontrado:
        raise Http404('Pago no encontrado.')
    except (PagoError, MercadoPagoError) as error:
        contexto.update(resultado='error', mensaje=str(error))
    pago = contexto['pago']
    contexto['puede_reintentar'] = (
        pago is not None and motivo_para_no_pagar_online(pago) is None
    )
    return render(request, 'administracion/retorno.html', contexto)


@dueno_requerido
def comprobante_view(request, dueno, pago_id):
    pago = _pago_o_404(dueno, pago_id)
    if not pago.numero_comprobante:
        raise Http404('Este pago no tiene comprobante.')
    return render(request, 'administracion/comprobante.html', {
        'pago': pago,
        'turno': pago.turno,
        'dueno': dueno,
    })

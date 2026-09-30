from pathlib import Path

import joblib
import pandas as pd

from atencion.ml.preparar_datos import FEATURES

RUTA_MODELO = Path(__file__).resolve().parent.parent / 'ml' / \
    'modelo_triage.pkl'

ORDEN_NIVELES = ['BAJA', 'MEDIA', 'ALTA', 'CRITICA']
RANGO_NIVELES = {nivel: indice for indice, nivel in enumerate(ORDEN_NIVELES)}

CAMPOS_NUMERICOS = {'edad', 'temperatura', 'dias_evolucion'}

_modelo = None


def _cargar_modelo():
    """Carga el modelo entrenado (atencion/ml/modelo_triage.pkl) una
    sola vez y lo cachea a nivel de modulo."""
    global _modelo
    if _modelo is None:
        if not RUTA_MODELO.exists():
            raise FileNotFoundError(
                f'No se encontro el modelo entrenado en {RUTA_MODELO}. '
                "Corre 'python manage.py entrenar_triage' primero."
            )
        _modelo = joblib.load(RUTA_MODELO)
    return _modelo


def _validar_datos(datos):
    faltantes = sorted(set(FEATURES) - set(datos.keys()))
    if faltantes:
        raise ValueError(
            'Faltan features en los datos de triage: ' + ', '.join(faltantes)
        )


def _normalizar_es_perro(valor):
    especie = str(valor).strip().lower()
    if especie not in ('perro', 'gato'):
        raise ValueError(
            "El valor de 'es_perro' debe ser 'perro' o 'gato', se "
            f'recibio: {valor!r}'
        )
    return 1 if especie == 'perro' else 0


def _armar_fila(datos):
    fila = {}
    for feature in FEATURES:
        valor = datos[feature]
        if feature == 'es_perro':
            fila[feature] = _normalizar_es_perro(valor)
        elif feature in CAMPOS_NUMERICOS:
            fila[feature] = float(valor)
        else:
            fila[feature] = int(bool(valor))
    return fila


def _reglas_de_seguridad(fila):
    """Devuelve [(nivel_minimo, texto), ...] para cada regla de
    seguridad que se cumple, ordenadas de mas a menos severa."""
    dificultad_respiratoria = bool(fila['dificultad_respiratoria'])
    temperatura_alta = fila['temperatura'] >= 40.0
    triada_shock = bool(
        fila['vomitos'] and fila['diarrea'] and fila['deshidratacion']
    )

    reglas = []
    if dificultad_respiratoria and temperatura_alta:
        reglas.append((
            'CRITICA',
            'Dificultad respiratoria junto con temperatura >= 40.0: '
            'nivel elevado a CRITICA.',
        ))
    if dificultad_respiratoria:
        reglas.append((
            'ALTA',
            'Dificultad respiratoria: nivel minimo ALTA.',
        ))
    if temperatura_alta:
        reglas.append((
            'ALTA',
            'Temperatura >= 40.0: nivel minimo ALTA.',
        ))
    if triada_shock:
        reglas.append((
            'ALTA',
            'Vomitos, diarrea y deshidratacion simultaneos: nivel '
            'minimo ALTA.',
        ))
    return reglas


def clasificar_urgencia(datos):
    """Clasifica el nivel de urgencia (BAJA/MEDIA/ALTA/CRITICA) a
    partir de un dict de features en español (ver FEATURES en
    atencion/ml/preparar_datos.py).

    Primero predice con el modelo entrenado y despues aplica reglas de
    seguridad que solo pueden subir el nivel predicho, nunca bajarlo.

    No accede a la base de datos: crear el NivelUrgencia/Turno queda a
    cargo de atencion/services/turnos.py.

    Devuelve {'nivel', 'nivel_modelo', 'regla_aplicada'}.

    Lanza ValueError si falta alguna feature en `datos`.
    """
    _validar_datos(datos)
    fila = _armar_fila(datos)

    modelo = _cargar_modelo()
    entrada = pd.DataFrame([fila], columns=FEATURES)
    nivel_modelo = str(modelo.predict(entrada)[0])

    nivel_final = nivel_modelo
    regla_aplicada = None
    for nivel_regla, texto in _reglas_de_seguridad(fila):
        if RANGO_NIVELES[nivel_regla] > RANGO_NIVELES[nivel_final]:
            nivel_final = nivel_regla
            regla_aplicada = texto

    return {
        'nivel': nivel_final,
        'nivel_modelo': nivel_modelo,
        'regla_aplicada': regla_aplicada,
    }

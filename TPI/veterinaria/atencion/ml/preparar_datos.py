import re
from pathlib import Path

import pandas as pd

RUTA_DATOS = Path(__file__).resolve().parent / 'datos'
RUTA_DATASET = RUTA_DATOS / 'cleaned_animal_disease_prediction.csv'
RUTA_MAPEO = RUTA_DATOS / 'mapeo_urgencia.csv'

ANIMALES_SOPORTADOS = ('Dog', 'Cat')

# Lista ordenada y unica de nombres de features: la usan tanto el
# entrenamiento (preparar_datos/entrenar_triage) como la prediccion
# (services/triage.py), para garantizar que el orden de columnas
# coincida siempre con el que espera el modelo entrenado.
FEATURES = [
    'perdida_apetito',
    'vomitos',
    'diarrea',
    'tos',
    'dificultad_respiratoria',
    'cojera',
    'lesiones_piel',
    'secrecion_nasal',
    'secrecion_ocular',
    'es_perro',
    'edad',
    'temperatura',
    'dias_evolucion',
    'letargo',
    'fiebre',
    'estornudos',
    'deshidratacion',
    'perdida_peso',
]

# Los 9 sintomas Si/No ya vienen como columna dedicada en el dataset.
COLUMNAS_SI_NO = {
    'perdida_apetito': 'Appetite_Loss',
    'vomitos': 'Vomiting',
    'diarrea': 'Diarrhea',
    'tos': 'Coughing',
    'dificultad_respiratoria': 'Labored_Breathing',
    'cojera': 'Lameness',
    'lesiones_piel': 'Skin_Lesions',
    'secrecion_nasal': 'Nasal_Discharge',
    'secrecion_ocular': 'Eye_Discharge',
}

COLUMNAS_SINTOMA_LIBRE = ['Symptom_1', 'Symptom_2', 'Symptom_3', 'Symptom_4']

# Sinonimos en ingles de cada concepto buscado en Symptom_1..4. La
# columna Appetite_Loss ya cubre la perdida de apetito como Si/No, pero
# en el texto libre aparece bajo dos nombres distintos ("Appetite
# Loss" y "Loss of Appetite"); se unifican aca aunque no generen una
# feature propia, para no perder ese concepto si en el futuro se
# necesita.
SINONIMOS_SINTOMA_LIBRE = {
    'letargo': {'Lethargy'},
    'fiebre': {'Fever'},
    'estornudos': {'Sneezing'},
    'deshidratacion': {'Dehydration'},
    'perdida_peso': {'Weight Loss'},
    'apetito_perdido': {'Appetite Loss', 'Loss of Appetite'},
}

SINTOMAS_LIBRES = (
    'letargo', 'fiebre', 'estornudos', 'deshidratacion', 'perdida_peso',
)


def _convertir_dias_evolucion(valor):
    coincidencia = re.match(r'(\d+)\s*(day|week)', str(valor).strip(), re.I)
    if not coincidencia:
        raise ValueError(f'No se pudo interpretar la duracion: {valor!r}')
    cantidad = int(coincidencia.group(1))
    unidad = coincidencia.group(2).lower()
    return cantidad * 7 if unidad == 'week' else cantidad


def _convertir_temperatura(valor):
    coincidencia = re.match(r'([\d.]+)', str(valor).strip())
    if not coincidencia:
        raise ValueError(f'No se pudo interpretar la temperatura: {valor!r}')
    return float(coincidencia.group(1))


def _sintoma_libre_presente(fila, conceptos):
    valores_fila = {fila[columna] for columna in COLUMNAS_SINTOMA_LIBRE}
    return int(bool(valores_fila & conceptos))


def cargar_mapeo_urgencia():
    """Lee mapeo_urgencia.csv (enfermedad -> nivel_urgencia)."""
    return pd.read_csv(RUTA_MAPEO)


def preparar_datos_entrenamiento():
    """Carga el dataset de Kaggle, lo filtra a perros y gatos, lo cruza
    con mapeo_urgencia.csv y arma las features de FEATURES.

    Devuelve (X, y): X es un DataFrame con las columnas de FEATURES en
    ese orden, y es una Series con el nivel_urgencia (BAJA/MEDIA/ALTA/
    CRITICA) de cada fila.

    Lanza ValueError si alguna enfermedad de perros/gatos presente en
    el dataset no tiene nivel_urgencia mapeado.
    """
    df = pd.read_csv(RUTA_DATASET)
    df = df[df['Animal_Type'].isin(ANIMALES_SOPORTADOS)].copy()

    mapeo = cargar_mapeo_urgencia()
    enfermedades_mapeadas = set(mapeo['enfermedad'])
    enfermedades_dataset = set(df['Disease_Prediction'])
    sin_mapear = sorted(enfermedades_dataset - enfermedades_mapeadas)
    if sin_mapear:
        raise ValueError(
            'Las siguientes enfermedades de perros/gatos no tienen '
            'nivel_urgencia mapeado en mapeo_urgencia.csv: '
            + ', '.join(sin_mapear)
        )

    df = df.merge(
        mapeo[['enfermedad', 'nivel_urgencia']],
        left_on='Disease_Prediction',
        right_on='enfermedad',
        how='left',
    )

    datos = pd.DataFrame(index=df.index)

    for feature, columna in COLUMNAS_SI_NO.items():
        datos[feature] = (df[columna] == 'Yes').astype(int)

    datos['es_perro'] = (df['Animal_Type'] == 'Dog').astype(int)
    datos['edad'] = df['Age'].astype(float)
    datos['temperatura'] = df['Body_Temperature'].apply(
        _convertir_temperatura
    )
    datos['dias_evolucion'] = df['Duration'].apply(_convertir_dias_evolucion)

    for feature in SINTOMAS_LIBRES:
        conceptos = SINONIMOS_SINTOMA_LIBRE[feature]
        datos[feature] = df.apply(
            lambda fila, c=conceptos: _sintoma_libre_presente(fila, c),
            axis=1,
        )

    X = datos[FEATURES]
    y = df['nivel_urgencia']
    return X, y

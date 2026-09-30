from pathlib import Path

import joblib
from django.core.management.base import BaseCommand
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import (
    StratifiedKFold,
    cross_val_predict,
    cross_val_score,
)

from atencion.ml.preparar_datos import preparar_datos_entrenamiento

RUTA_MODELO = Path(__file__).resolve().parent.parent.parent / 'ml' / \
    'modelo_triage.pkl'
RANDOM_STATE = 42
ORDEN_NIVELES = ['BAJA', 'MEDIA', 'ALTA', 'CRITICA']


class Command(BaseCommand):
    help = (
        'Entrena el modelo de triage (RF02) con el dataset de Kaggle '
        'filtrado a perros/gatos y lo guarda en atencion/ml/'
        'modelo_triage.pkl'
    )

    def handle(self, *args, **options):
        X, y = preparar_datos_entrenamiento()

        cv = StratifiedKFold(
            n_splits=5, shuffle=True, random_state=RANDOM_STATE,
        )
        modelo = RandomForestClassifier(
            class_weight='balanced', random_state=RANDOM_STATE,
        )
        baseline = DummyClassifier(
            strategy='most_frequent', random_state=RANDOM_STATE,
        )

        scores = cross_val_score(modelo, X, y, cv=cv)
        scores_baseline = cross_val_score(baseline, X, y, cv=cv)

        self.stdout.write(f'Filas de entrenamiento: {len(X)}')
        self.stdout.write(
            'Accuracy RandomForest (5-fold CV): '
            f'{scores.mean():.3f} (+/- {scores.std():.3f})'
        )
        self.stdout.write(
            'Accuracy baseline (clase mayoritaria, 5-fold CV): '
            f'{scores_baseline.mean():.3f} (+/- {scores_baseline.std():.3f})'
        )

        y_pred = cross_val_predict(modelo, X, y, cv=cv)
        self.stdout.write('')
        self.stdout.write('Classification report (predicciones out-of-fold):')
        self.stdout.write(
            classification_report(
                y, y_pred, labels=ORDEN_NIVELES, zero_division=0,
            )
        )

        modelo.fit(X, y)
        RUTA_MODELO.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(modelo, RUTA_MODELO)
        self.stdout.write(
            self.style.SUCCESS(f'Modelo guardado en {RUTA_MODELO}')
        )

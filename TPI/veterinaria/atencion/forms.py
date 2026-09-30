from django import forms

from atencion.ml.preparar_datos import FEATURES

# Temperatura corporal normal aproximada de un perro/gato sano, en °C.
# Se usa cuando el dueño no sabe/no midio la temperatura de la mascota.
TEMPERATURA_POR_DEFECTO = 38.5

CAMPOS_NO_SINTOMA = {'es_perro', 'edad', 'temperatura', 'dias_evolucion'}
CAMPOS_SINTOMAS = [
    campo for campo in FEATURES if campo not in CAMPOS_NO_SINTOMA
]


class TriageForm(forms.Form):
    especie = forms.ChoiceField(
        choices=[('perro', 'Perro'), ('gato', 'Gato')],
        label='Especie',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    edad = forms.IntegerField(
        label='Edad (en años)',
        min_value=0,
        max_value=30,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    dias_evolucion = forms.IntegerField(
        label='¿Hace cuántos días empezaron los síntomas?',
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    temperatura = forms.DecimalField(
        label='Temperatura en °C, si la sabe',
        required=False,
        max_digits=4,
        decimal_places=1,
        min_value=30,
        max_value=45,
        widget=forms.NumberInput(
            attrs={'class': 'form-control', 'step': '0.1'},
        ),
    )

    perdida_apetito = forms.BooleanField(
        required=False, label='¿Perdió el apetito?',
    )
    vomitos = forms.BooleanField(required=False, label='¿Vomita?')
    diarrea = forms.BooleanField(required=False, label='¿Tiene diarrea?')
    tos = forms.BooleanField(required=False, label='¿Tose?')
    dificultad_respiratoria = forms.BooleanField(
        required=False, label='¿Respira con dificultad?',
    )
    cojera = forms.BooleanField(required=False, label='¿Cojea?')
    lesiones_piel = forms.BooleanField(
        required=False, label='¿Tiene lesiones o heridas en la piel?',
    )
    secrecion_nasal = forms.BooleanField(
        required=False, label='¿Tiene secreción o moqueo nasal?',
    )
    secrecion_ocular = forms.BooleanField(
        required=False,
        label='¿Tiene secreción en los ojos (legañas)?',
    )
    letargo = forms.BooleanField(
        required=False,
        label='¿Está decaído o con muy poca energía?',
    )
    fiebre = forms.BooleanField(required=False, label='¿Tiene fiebre?')
    estornudos = forms.BooleanField(
        required=False, label='¿Estornuda seguido?',
    )
    deshidratacion = forms.BooleanField(
        required=False,
        label='¿Notás signos de deshidratación (encías secas, poca '
              'elasticidad de la piel)?',
    )
    perdida_peso = forms.BooleanField(
        required=False, label='¿Perdió peso de forma notoria?',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in CAMPOS_SINTOMAS:
            self.fields[campo].widget.attrs['class'] = 'form-check-input'

    @property
    def sintomas(self):
        """Bound fields de los sintomas, en el mismo orden que
        CAMPOS_SINTOMAS, para que la plantilla los agrupe facil."""
        return [self[campo] for campo in CAMPOS_SINTOMAS]

    def a_datos_triage(self):
        """Convierte cleaned_data al dict que espera
        atencion.services.triage.clasificar_urgencia.

        Solo traduce nombres/formatos de campos del formulario a las
        features del modelo (por ej. especie -> es_perro, temperatura
        vacia -> TEMPERATURA_POR_DEFECTO); no aplica ninguna regla de
        negocio, eso es responsabilidad del service.
        """
        datos = {
            campo: self.cleaned_data[campo] for campo in CAMPOS_SINTOMAS
        }
        datos['es_perro'] = self.cleaned_data['especie']
        datos['edad'] = self.cleaned_data['edad']
        datos['dias_evolucion'] = self.cleaned_data['dias_evolucion']

        temperatura = self.cleaned_data.get('temperatura')
        datos['temperatura'] = (
            float(temperatura)
            if temperatura is not None
            else TEMPERATURA_POR_DEFECTO
        )
        return datos

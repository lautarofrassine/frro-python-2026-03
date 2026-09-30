# Regla del proyecto: las vistas solo llaman a funciones de services/,
# nunca acceden a los modelos ni contienen reglas de negocio.
from django.shortcuts import render

from atencion.forms import TriageForm
from atencion.services.triage import clasificar_urgencia


def triage_view(request):
    if request.method == 'POST':
        form = TriageForm(request.POST)
        if form.is_valid():
            resultado = clasificar_urgencia(form.a_datos_triage())
            return render(
                request,
                'atencion/triage_resultado.html',
                {'resultado': resultado},
            )
    else:
        form = TriageForm()
    return render(request, 'atencion/triage_form.html', {'form': form})

import re
import unicodedata
from datetime import time

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from atencion.models import HorarioAtencion, Veterinario

# Franjas de atencion. HorarioAtencion guarda una fila por veterinario
# y dia; los turnos de 30 minutos se calculan entre hora_inicio y
# hora_fin (ver services/turnos.py).
MANANA = (time(8, 0), time(13, 0))
TARDE = (time(13, 0), time(19, 0))
# La guardia cubre las 24 horas en 3 franjas de 8 horas que no cruzan
# la medianoche. El campo no admite 24:00: 23:59 es el fin del dia.
GUARDIA_MADRUGADA = (time(0, 0), time(8, 0))
GUARDIA_DIA = (time(8, 0), time(16, 0))
GUARDIA_NOCHE = (time(16, 0), time(23, 59))
DIAS_DE_ATENCION = (
    HorarioAtencion.DiaSemana.LUNES,
    HorarioAtencion.DiaSemana.MARTES,
    HorarioAtencion.DiaSemana.MIERCOLES,
    HorarioAtencion.DiaSemana.JUEVES,
    HorarioAtencion.DiaSemana.VIERNES,
    HorarioAtencion.DiaSemana.SABADO,
)

TODOS_LOS_DIAS = tuple(HorarioAtencion.DiaSemana)

_E = Veterinario.Especialidad

# Datos ficticios: 3 veterinarios por especialidad de consulta. En cada
# una hay al menos uno de mañana y uno de tarde. Las matriculas MP-50xx
# no chocan con las ya cargadas (MP-1234, MP-5678, MP-9012).
VETERINARIOS_INICIALES = [
    ('MP-5001', 'Dra. Laura Fernández', _E.CLINICA_GENERAL, MANANA),
    ('MP-5002', 'Dr. Martín Sosa', _E.CLINICA_GENERAL, TARDE),
    ('MP-5003', 'Dra. Carolina Benítez', _E.CLINICA_GENERAL, MANANA),
    ('MP-5004', 'Dr. Federico Acosta', _E.CARDIOLOGIA, MANANA),
    ('MP-5005', 'Dra. Valeria Medina', _E.CARDIOLOGIA, TARDE),
    ('MP-5006', 'Dr. Gonzalo Herrera', _E.CARDIOLOGIA, TARDE),
    ('MP-5007', 'Dra. Florencia Aguirre', _E.DERMATOLOGIA, MANANA),
    ('MP-5008', 'Dr. Nicolás Cabrera', _E.DERMATOLOGIA, TARDE),
    ('MP-5009', 'Dra. Julieta Molina', _E.DERMATOLOGIA, MANANA),
    ('MP-5010', 'Dr. Sebastián Romero', _E.TRAUMATOLOGIA, MANANA),
    ('MP-5011', 'Dra. Micaela Castro', _E.TRAUMATOLOGIA, TARDE),
    ('MP-5012', 'Dr. Agustín Ledesma', _E.TRAUMATOLOGIA, TARDE),
    ('MP-5013', 'Dra. Camila Ortiz', _E.GASTROENTEROLOGIA, MANANA),
    ('MP-5014', 'Dr. Ezequiel Villalba', _E.GASTROENTEROLOGIA, TARDE),
    ('MP-5015', 'Dra. Rocío Peralta', _E.GASTROENTEROLOGIA, MANANA),
    ('MP-5016', 'Dr. Tomás Giménez', _E.OFTALMOLOGIA, MANANA),
    ('MP-5017', 'Dra. Antonella Luna', _E.OFTALMOLOGIA, TARDE),
    ('MP-5018', 'Dr. Ramiro Correa', _E.OFTALMOLOGIA, TARDE),
]

# Los de VACUNACION solo se crean si la clinica todavia no tiene ningun
# veterinario de esa especialidad.
VETERINARIOS_VACUNACION = [
    ('MP-5019', 'Dra. Paula Navarro', _E.VACUNACION, MANANA),
    ('MP-5020', 'Dr. Ignacio Ferreyra', _E.VACUNACION, TARDE),
    ('MP-5021', 'Dra. Milagros Suárez', _E.VACUNACION, MANANA),
]

# Guardia: 2 veterinarios por franja, los 7 dias. Como los de
# VACUNACION, solo se crean si no hay ninguno de GUARDIA.
VETERINARIOS_GUARDIA = [
    ('MP-5022', 'Dr. Hernán Quiroga', _E.GUARDIA, GUARDIA_MADRUGADA),
    ('MP-5023', 'Dra. Soledad Ibáñez', _E.GUARDIA, GUARDIA_MADRUGADA),
    ('MP-5024', 'Dr. Maximiliano Vera', _E.GUARDIA, GUARDIA_DIA),
    ('MP-5025', 'Dra. Luciana Paz', _E.GUARDIA, GUARDIA_DIA),
    ('MP-5026', 'Dr. Cristian Maldonado', _E.GUARDIA, GUARDIA_NOCHE),
    ('MP-5027', 'Dra. Brenda Coronel', _E.GUARDIA, GUARDIA_NOCHE),
]

# Especialidades cuyos veterinarios se cargan solo si no hay ninguno.
CARGA_SI_NO_HAY = {
    _E.VACUNACION: VETERINARIOS_VACUNACION,
    _E.GUARDIA: VETERINARIOS_GUARDIA,
}


@transaction.atomic
def cargar_veterinarios_iniciales():
    """Crea los veterinarios de VETERINARIOS_INICIALES que todavia no
    existen (se busca por matricula, asi se puede correr varias veces),
    todos ACTIVO y con su horario (de lunes a sabado; la guardia, los 7
    dias). Los de VACUNACION y los de GUARDIA se crean solo si no hay
    ninguno de esa especialidad.

    Devuelve {etiqueta_especialidad: {'creados': n, 'existentes': n}}.
    """
    resumen = {
        etiqueta: {'creados': 0, 'existentes': 0}
        for etiqueta in Veterinario.Especialidad.labels
    }
    a_cargar = list(VETERINARIOS_INICIALES)
    for especialidad, veterinarios in CARGA_SI_NO_HAY.items():
        ya_cargados = Veterinario.objects.filter(
            especialidad=especialidad,
        ).count()
        if ya_cargados:
            resumen[especialidad.label]['existentes'] = ya_cargados
        else:
            a_cargar += veterinarios

    for matricula, nombre, especialidad, franja in a_cargar:
        veterinario, creado = Veterinario.objects.get_or_create(
            matricula=matricula,
            defaults={
                'nombre': nombre,
                'especialidad': especialidad,
                'estado': Veterinario.Estado.ACTIVO,
            },
        )
        if creado:
            hora_inicio, hora_fin = franja
            HorarioAtencion.objects.bulk_create([
                HorarioAtencion(
                    veterinario=veterinario,
                    dia_semana=dia,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
                for dia in (
                    TODOS_LOS_DIAS if especialidad == _E.GUARDIA
                    else DIAS_DE_ATENCION
                )
            ])
        clave = 'creados' if creado else 'existentes'
        resumen[especialidad.label][clave] += 1
    return resumen


# ---------------------------------------------------------------------
# Cuentas de los veterinarios (no se registran por la web)
# ---------------------------------------------------------------------

DOMINIO_EMAIL = 'clinicavet24.com'
_TITULOS = {'dr', 'dra'}


class CuentaVeterinarioError(Exception):
    """No se pueden crear las cuentas (falta o no sirve la contraseña
    inicial)."""


def obtener_veterinario_de_usuario(user):
    """El Veterinario vinculado al usuario, o None (dueños, personal o
    usuario anonimo)."""
    if not getattr(user, 'is_authenticated', False):
        return None
    return Veterinario.objects.filter(usuario=user).first()


def _palabras_del_nombre(nombre):
    """'Dra. Laura Fernández' -> ['Laura', 'Fernández'] (sin el titulo)."""
    return [
        palabra for palabra in nombre.split()
        if palabra.lower().rstrip('.') not in _TITULOS
    ]


def _para_email(palabra):
    sin_tildes = ''.join(
        caracter
        for caracter in unicodedata.normalize('NFKD', palabra)
        if not unicodedata.combining(caracter)
    )
    return re.sub(r'[^a-z]', '', sin_tildes.lower())


def _email_libre(nombre):
    """nombre.apellido@clinicavet24.com, con un numero si ya existe."""
    palabras = [_para_email(p) for p in _palabras_del_nombre(nombre)]
    palabras = [p for p in palabras if p] or ['veterinario']
    local = '.'.join([palabras[0], palabras[-1]] if len(palabras) > 1
                     else palabras)
    User = get_user_model()
    candidato = f'{local}@{DOMINIO_EMAIL}'
    numero = 2
    while (User.objects.filter(username__iexact=candidato).exists()
           or User.objects.filter(email__iexact=candidato).exists()):
        candidato = f'{local}{numero}@{DOMINIO_EMAIL}'
        numero += 1
    return candidato


@transaction.atomic
def crear_usuarios_veterinarios(password):
    """Crea la cuenta de cada veterinario activo que todavia no tiene
    (email nombre.apellido@clinicavet24.com) con la contraseña inicial,
    guardada hasheada. No toca a los que ya tienen cuenta.

    Devuelve la lista de veterinarios a los que se les creo cuenta.
    Lanza CuentaVeterinarioError si falta la contraseña o no cumple los
    validadores de Django.
    """
    if not password:
        raise CuentaVeterinarioError(
            'Falta la contraseña inicial: definí la variable de entorno '
            'VET_PASSWORD_INICIAL (por ejemplo en el archivo .env).'
        )
    try:
        validate_password(password)
    except ValidationError as error:
        raise CuentaVeterinarioError(
            'La contraseña inicial (VET_PASSWORD_INICIAL) no es válida: '
            + ' '.join(error.messages)
        )

    User = get_user_model()
    creados = []
    sin_cuenta = Veterinario.objects.filter(
        estado=Veterinario.Estado.ACTIVO, usuario__isnull=True,
    ).order_by('nombre')
    for veterinario in sin_cuenta:
        email = _email_libre(veterinario.nombre)
        palabras = _palabras_del_nombre(veterinario.nombre)
        # create_user guarda la contraseña con set_password (hasheada).
        veterinario.usuario = User.objects.create_user(
            username=email,
            email=email,
            first_name=palabras[0] if palabras else '',
            last_name=' '.join(palabras[1:]),
            password=password,
        )
        veterinario.save(update_fields=['usuario'])
        creados.append(veterinario)
    return creados


def veterinarios_con_cuenta():
    """Veterinarios que ya tienen cuenta, por especialidad y nombre."""
    return list(
        Veterinario.objects.filter(usuario__isnull=False)
        .select_related('usuario')
        .order_by('especialidad', 'nombre')
    )

import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q

from clinica.models import Dueno

MENSAJE_EMAIL_EN_USO = 'Este email ya está en uso.'
MENSAJE_DNI_REGISTRADO = 'Este DNI ya está registrado.'
MENSAJE_DNI_INVALIDO = 'El DNI debe tener 7 u 8 dígitos.'
MENSAJE_PASSWORD_ACTUAL = 'La contraseña actual no es correcta.'


class RegistroError(Exception):
    """Error de negocio al registrar un dueño. `campo` indica a que
    campo del formulario corresponde, si se puede determinar."""

    def __init__(self, mensaje, campo=None):
        super().__init__(mensaje)
        self.campo = campo


class CuentaError(Exception):
    """Error al cambiar el email o la contraseña. `campo` indica a que
    campo del formulario corresponde."""

    def __init__(self, mensaje, campo=None):
        super().__init__(mensaje)
        self.campo = campo


def normalizar_email(email):
    return email.strip().lower()


def normalizar_dni(dni):
    return re.sub(r'\D', '', dni)


def dni_tiene_formato_valido(dni):
    return re.fullmatch(r'\d{7,8}', normalizar_dni(dni)) is not None


def email_en_uso(email):
    """True si el email ya pertenece a un Dueno o a cualquier User
    (incluido el personal de la clinica)."""
    email = normalizar_email(email)
    User = get_user_model()
    return (
        Dueno.objects.filter(email=email).exists()
        or User.objects.filter(email__iexact=email).exists()
        or User.objects.filter(username__iexact=email).exists()
    )


def dni_registrado(dni):
    return Dueno.objects.filter(dni=normalizar_dni(dni)).exists()


def validar_password(password, email='', nombre='', apellido=''):
    """Aplica los AUTH_PASSWORD_VALIDATORS de Django. Lanza
    ValidationError con la lista de mensajes si no cumple."""
    User = get_user_model()
    usuario_tentativo = User(
        username=email, email=email, first_name=nombre, last_name=apellido,
    )
    validate_password(password, user=usuario_tentativo)


def registrar_dueno(nombre, apellido, dni, email, telefono, password):
    """Registra un dueño con su propia cuenta: crea el User de Django
    (contraseña hasheada con PBKDF2) y el Dueno vinculado, de forma
    atomica. Nunca queda un User sin Dueno.

    Lanza RegistroError si el email o el DNI ya estan en uso, si el DNI
    no tiene formato valido o si la contraseña no cumple los
    validadores.
    """
    email = normalizar_email(email)
    dni = normalizar_dni(dni)

    if not dni_tiene_formato_valido(dni):
        raise RegistroError(MENSAJE_DNI_INVALIDO, campo='dni')
    if email_en_uso(email):
        raise RegistroError(MENSAJE_EMAIL_EN_USO, campo='email')
    if dni_registrado(dni):
        raise RegistroError(MENSAJE_DNI_REGISTRADO, campo='dni')
    try:
        validar_password(password, email, nombre, apellido)
    except ValidationError as exc:
        raise RegistroError(' '.join(exc.messages), campo='password1')

    User = get_user_model()
    try:
        with transaction.atomic():
            usuario = User.objects.create_user(
                username=email,
                email=email,
                first_name=nombre,
                last_name=apellido,
                password=password,
            )
            return Dueno.objects.create(
                usuario=usuario,
                nombre=nombre,
                apellido=apellido,
                dni=dni,
                email=email,
                telefono=telefono,
            )
    except IntegrityError as exc:
        # Registro simultaneo con el mismo email/DNI: el atomic ya
        # deshizo el User, asi que no queda una cuenta huerfana.
        raise RegistroError(
            'No se pudo completar el registro: el email o el DNI ya '
            'están en uso.'
        ) from exc


def obtener_dueno_de_usuario(user):
    """Devuelve el Dueno vinculado al usuario, o None si no tiene
    (personal de la clinica o usuario anonimo)."""
    if not user.is_authenticated:
        return None
    return (
        Dueno.objects.select_related('obra_social')
        .filter(usuario=user)
        .first()
    )


@transaction.atomic
def actualizar_datos_personales(dueno, nombre, apellido, telefono):
    """Guarda nombre, apellido y telefono del dueño (el DNI no se
    cambia; el email, con cambiar_email). Lanza RegistroError si falta
    un dato."""
    datos = {
        'nombre': (nombre or '').strip(),
        'apellido': (apellido or '').strip(),
        'telefono': (telefono or '').strip(),
    }
    for campo, valor in datos.items():
        if not valor:
            raise RegistroError('Este dato es obligatorio.', campo=campo)
    for campo, valor in datos.items():
        setattr(dueno, campo, valor)
    dueno.save(update_fields=list(datos))
    # El User tambien tiene el nombre (se usa en el menu).
    usuario = dueno.usuario
    usuario.first_name = datos['nombre']
    usuario.last_name = datos['apellido']
    usuario.save(update_fields=['first_name', 'last_name'])
    return dueno


def _email_en_uso_por_otro(email, dueno):
    User = get_user_model()
    return (
        Dueno.objects.filter(email__iexact=email)
        .exclude(pk=dueno.pk).exists()
        or User.objects.filter(
            Q(email__iexact=email) | Q(username__iexact=email),
        ).exclude(pk=dueno.usuario_id).exists()
    )


def cambiar_email(dueno, nuevo_email, password_actual):
    """Cambia el email del dueño, que tambien es su usuario para
    ingresar. Pide la contraseña actual. Actualiza email y username del
    User y el email del Dueno en la misma transaccion. Lanza CuentaError
    si el email no es valido, ya es el suyo o lo usa otra persona, o si
    la contraseña no es correcta; en ese caso no cambia nada."""
    email = normalizar_email(nuevo_email or '')
    try:
        validate_email(email)
    except ValidationError:
        raise CuentaError('Ingresá un email válido.', 'nuevo_email')
    usuario = dueno.usuario
    if not usuario.check_password(password_actual or ''):
        raise CuentaError(MENSAJE_PASSWORD_ACTUAL, 'password_actual')
    if email == normalizar_email(dueno.email):
        raise CuentaError('Ese ya es tu email.', 'nuevo_email')
    if _email_en_uso_por_otro(email, dueno):
        raise CuentaError(MENSAJE_EMAIL_EN_USO, 'nuevo_email')
    try:
        with transaction.atomic():
            usuario.email = email
            usuario.username = email
            usuario.save(update_fields=['email', 'username'])
            dueno.email = email
            dueno.save(update_fields=['email'])
    except IntegrityError:
        # Otro usuario tomo ese email al mismo tiempo.
        raise CuentaError(MENSAJE_EMAIL_EN_USO, 'nuevo_email')
    return dueno


def cambiar_password(user, actual, nueva):
    """Cambia la contraseña (queda hasheada) si la actual es correcta y
    la nueva cumple los AUTH_PASSWORD_VALIDATORS. Lanza CuentaError.
    La vista se encarga de mantener la sesion iniciada."""
    if not user.check_password(actual or ''):
        raise CuentaError(MENSAJE_PASSWORD_ACTUAL, 'old_password')
    try:
        validate_password(nueva, user=user)
    except ValidationError as exc:
        raise CuentaError(' '.join(exc.messages), 'new_password2')
    user.set_password(nueva)
    user.save(update_fields=['password'])
    return user

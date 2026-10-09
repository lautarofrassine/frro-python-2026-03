import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from clinica.models import Dueno

MENSAJE_EMAIL_EN_USO = 'Este email ya está en uso.'
MENSAJE_DNI_REGISTRADO = 'Este DNI ya está registrado.'
MENSAJE_DNI_INVALIDO = 'El DNI debe tener 7 u 8 dígitos.'


class RegistroError(Exception):
    """Error de negocio al registrar un dueño. `campo` indica a que
    campo del formulario corresponde, si se puede determinar."""

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

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    UsernameField,
)
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from clinica.services.mascotas import ESPECIES
from clinica.services.usuarios import (
    MENSAJE_DNI_INVALIDO,
    MENSAJE_DNI_REGISTRADO,
    MENSAJE_EMAIL_EN_USO,
    dni_registrado,
    dni_tiene_formato_valido,
    email_en_uso,
    normalizar_dni,
    normalizar_email,
    validar_password,
)


class RegistroForm(forms.Form):
    nombre = forms.CharField(label='Nombre', max_length=100)
    apellido = forms.CharField(label='Apellido', max_length=100)
    dni = forms.CharField(
        label='DNI',
        max_length=12,
        help_text='7 u 8 dígitos, con o sin puntos.',
    )
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}),
    )
    telefono = forms.CharField(
        label='Teléfono',
        max_length=20,
        validators=[
            RegexValidator(
                r'^[\d\s()+-]{6,20}$',
                'Ingresá un teléfono válido (números, espacios, +, - o '
                'paréntesis).',
            ),
        ],
    )
    password1 = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Al menos 8 caracteres, no solo números ni muy común.',
    )
    password2 = forms.CharField(
        label='Repetir contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs.setdefault('class', 'form-control')

    def clean_email(self):
        email = normalizar_email(self.cleaned_data['email'])
        if email_en_uso(email):
            raise ValidationError(MENSAJE_EMAIL_EN_USO)
        return email

    def clean_dni(self):
        dni = normalizar_dni(self.cleaned_data['dni'])
        if not dni_tiene_formato_valido(dni):
            raise ValidationError(MENSAJE_DNI_INVALIDO)
        if dni_registrado(dni):
            raise ValidationError(MENSAJE_DNI_REGISTRADO)
        return dni

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
        elif password1:
            try:
                validar_password(
                    password1,
                    email=cleaned_data.get('email', ''),
                    nombre=cleaned_data.get('nombre', ''),
                    apellido=cleaned_data.get('apellido', ''),
                )
            except ValidationError as exc:
                self.add_error('password1', exc)
        return cleaned_data

    def datos_registro(self):
        """Argumentos para clinica.services.usuarios.registrar_dueno."""
        return {
            'nombre': self.cleaned_data['nombre'],
            'apellido': self.cleaned_data['apellido'],
            'dni': self.cleaned_data['dni'],
            'email': self.cleaned_data['email'],
            'telefono': self.cleaned_data['telefono'],
            'password': self.cleaned_data['password1'],
        }


class LoginForm(AuthenticationForm):
    username = UsernameField(
        label='Email',
        widget=forms.EmailInput(
            attrs={
                'autofocus': True,
                'autocomplete': 'email',
                'class': 'form-control',
            },
        ),
    )
    password = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'autocomplete': 'current-password',
                'class': 'form-control',
            },
        ),
    )

    error_messages = {
        'invalid_login': 'Email o contraseña incorrectos.',
        'inactive': 'Email o contraseña incorrectos.',
    }

    def clean_username(self):
        return normalizar_email(self.cleaned_data['username'])


# Sugerencias para el <datalist> de raza; se puede escribir cualquier
# otra.
RAZAS_SUGERIDAS = {
    'PERRO': [
        'Mestizo', 'Labrador Retriever', 'Golden Retriever', 'Caniche',
        'Bulldog Francés', 'Pastor Alemán', 'Beagle', 'Salchicha',
        'Yorkshire Terrier', 'Boxer', 'Border Collie', 'Rottweiler',
        'Chihuahua', 'Shih Tzu', 'Pitbull', 'Dogo Argentino',
    ],
    'GATO': [
        'Mestizo', 'Común europeo', 'Siamés', 'Persa', 'Maine Coon',
        'Bengalí', 'Ragdoll', 'Británico de pelo corto', 'Sphynx',
        'Angora', 'Azul ruso',
    ],
}


class MascotaForm(forms.Form):
    """Solo valida formato. Las reglas de negocio (especie, fecha
    futura, rango de peso, nombre repetido) las valida
    clinica.services.mascotas y sus errores se agregan al form."""

    nombre = forms.CharField(label='Nombre', max_length=100)
    especie = forms.ChoiceField(
        label='Especie', choices=ESPECIES, widget=forms.RadioSelect,
    )
    raza = forms.CharField(
        label='Raza',
        max_length=50,
        help_text='Elegí de la lista o escribila. Si no la sabés, poné '
                  '"Mestizo".',
    )
    fecha_nacimiento = forms.DateField(
        label='Fecha de nacimiento',
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        help_text='Si no la sabés exacta, poné una aproximada.',
    )
    peso_kg = forms.DecimalField(
        label='Peso (kg)',
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={'step': '0.01', 'min': '0.01', 'inputmode': 'decimal'},
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre, campo in self.fields.items():
            if nombre != 'especie':
                campo.widget.attrs.setdefault('class', 'form-control')
        self.fields['raza'].widget.attrs['list'] = (
            f'razas-{self.especie_seleccionada.lower()}'
        )

    @classmethod
    def desde_mascota(cls, mascota):
        return cls(initial={
            'nombre': mascota.nombre,
            'especie': mascota.especie,
            'raza': mascota.raza,
            'fecha_nacimiento': mascota.fecha_nacimiento,
            'peso_kg': mascota.peso_kg,
        })

    @property
    def especie_seleccionada(self):
        valor = self['especie'].value() or 'PERRO'
        return valor if valor in RAZAS_SUGERIDAS else 'PERRO'

    @property
    def razas_sugeridas(self):
        return RAZAS_SUGERIDAS

    def datos_mascota(self):
        """Argumentos para registrar_mascota / actualizar_mascota."""
        return {campo: self.cleaned_data[campo] for campo in (
            'nombre', 'especie', 'raza', 'fecha_nacimiento', 'peso_kg',
        )}


TELEFONO_VALIDATOR = RegexValidator(
    r'^[\d\s()+-]{6,20}$',
    'Ingresá un teléfono válido (números, espacios, +, - o paréntesis).',
)


def _con_clase_bootstrap(form):
    for campo in form.fields.values():
        campo.widget.attrs.setdefault('class', 'form-control')


class DatosPersonalesForm(forms.Form):
    """Mi perfil > Datos personales (el DNI es solo lectura)."""

    nombre = forms.CharField(label='Nombre', max_length=100)
    apellido = forms.CharField(label='Apellido', max_length=100)
    telefono = forms.CharField(
        label='Teléfono', max_length=20, validators=[TELEFONO_VALIDATOR],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _con_clase_bootstrap(self)

    @classmethod
    def desde_dueno(cls, dueno):
        return cls(initial={
            'nombre': dueno.nombre,
            'apellido': dueno.apellido,
            'telefono': dueno.telefono,
        })


class ObraSocialForm(forms.Form):
    """Mi perfil > Obra social. Las opciones son las obras sociales
    activas que la vista obtiene del service."""

    obra_social = forms.ChoiceField(
        label='Obra social', required=False, choices=[],
    )
    numero_afiliado = forms.CharField(
        label='Número de afiliado', max_length=30, required=False,
    )

    def __init__(self, *args, **kwargs):
        obras_sociales = kwargs.pop('obras_sociales', ())
        super().__init__(*args, **kwargs)
        self.fields['obra_social'].choices = (
            [('', 'Sin obra social')]
            + [(str(obra.pk), obra.nombre) for obra in obras_sociales]
        )
        _con_clase_bootstrap(self)
        self.fields['obra_social'].widget.attrs['class'] = 'form-select'

    @classmethod
    def desde_dueno(cls, dueno, obras_sociales):
        return cls(obras_sociales=obras_sociales, initial={
            'obra_social': (
                str(dueno.obra_social_id) if dueno.obra_social_id else ''
            ),
            'numero_afiliado': dueno.numero_afiliado,
        })

    def datos_obra_social(self):
        """Argumentos para asignar_obra_social_a_dueno."""
        return {
            'obra_social_id': self.cleaned_data['obra_social'] or None,
            'numero_afiliado': self.cleaned_data['numero_afiliado'],
        }


class CambiarEmailForm(forms.Form):
    """Mi perfil > Cambiar email. Las reglas (email en uso, contraseña)
    las valida clinica.services.usuarios.cambiar_email."""

    nuevo_email = forms.EmailField(
        label='Nuevo email',
        max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}),
    )
    password_actual = forms.CharField(
        label='Contraseña actual',
        strip=False,
        widget=forms.PasswordInput(
            attrs={'autocomplete': 'current-password'},
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _con_clase_bootstrap(self)


class CambiarPasswordForm(PasswordChangeForm):
    """Mi perfil > Cambiar contraseña: el PasswordChangeForm de Django
    (con sus validadores) con estilos del sitio. Guarda el service
    cambiar_password, no este formulario."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = 'Contraseña actual'
        self.fields['old_password'].widget.attrs.pop('autofocus', None)
        self.fields['new_password1'].label = 'Nueva contraseña'
        self.fields['new_password2'].label = 'Repetir nueva contraseña'
        _con_clase_bootstrap(self)

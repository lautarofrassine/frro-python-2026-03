from django import forms
from django.contrib.auth.forms import AuthenticationForm, UsernameField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

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

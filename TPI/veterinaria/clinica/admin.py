from django.contrib import admin

from .models import AplicacionVacuna, Dueno, HistorialClinico, Mascota, Vacuna


@admin.register(Dueno)
class DuenoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre', 'apellido', 'dni', 'email', 'telefono', 'usuario',
        'obra_social', 'fecha_registro',
    )
    search_fields = ('nombre', 'apellido', 'dni', 'email', 'usuario__username')
    list_select_related = ('usuario', 'obra_social')
    raw_id_fields = ('usuario',)


@admin.register(Mascota)
class MascotaAdmin(admin.ModelAdmin):
    list_display = (
        'nombre', 'especie', 'raza', 'fecha_nacimiento', 'peso_kg', 'dueno',
    )
    search_fields = ('nombre', 'especie', 'raza')
    list_filter = ('especie',)


@admin.register(Vacuna)
class VacunaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'nombre_corto', 'especie', 'periodicidad_dias')
    list_filter = ('especie',)
    search_fields = ('nombre',)


@admin.register(AplicacionVacuna)
class AplicacionVacunaAdmin(admin.ModelAdmin):
    list_display = ('mascota', 'vacuna', 'fecha_aplicacion')
    list_filter = ('vacuna',)


@admin.register(HistorialClinico)
class HistorialClinicoAdmin(admin.ModelAdmin):
    list_display = ('mascota', 'fecha', 'diagnostico')
    search_fields = ('diagnostico', 'tratamiento')

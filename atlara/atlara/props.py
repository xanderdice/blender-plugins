# SPDX-License-Identifier: GPL-3.0-or-later
"""Ajustes del panel y ficha del informe."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

MODOS = (
    ('TODO', "Un atlas para todo",
     "Un unico material compartido por todos los objetos seleccionados. "
     "Es lo que menos drawcalls deja"),
    ('OBJETO', "Un atlas por objeto",
     "Cada objeto se queda con su propio material y su propio atlas"),
)

RESOLUCIONES = (
    ('0', "Automatica", "La calcula a partir de las texturas de origen"),
    ('128', "128", ""),
    ('256', "256", ""),
    ('512', "512", ""),
    ('1024', "1024", ""),
    ('2048', "2048", ""),
    ('4096', "4096", ""),
    ('8192', "8192", ""),
)

FORMAS = (
    ('CONCAVE', "Contorno exacto",
     "Sigue el borde real de la isla. Es el que mejor aprovecha"),
    ('CONVEX', "Envoltura convexa",
     "Contorno simplificado, sin entrantes"),
    ('AABB', "Caja",
     "Solo la caja envolvente. El mas rapido y el que peor aprovecha"),
)

EMPAQUETADORES = (
    ('AUTO', "Automatico",
     "Reparte de las dos maneras y se queda con la que deja mas texeles "
     "utiles. Nunca sale peor que la mejor de las dos, pero paga el "
     "tiempo de las dos"),
    ('FORMA', "Por la forma real",
     "Usa el empaquetador de Blender, que mira el contorno de cada isla y "
     "puede meter una en el hueco de otra. Aprovecha mas el atlas"),
    ('CAJA', "Por caja envolvente",
     "El empaquetador propio de Atlara. Mas rapido y siempre igual, pero "
     "desperdicia lo que sobra dentro de la caja de cada isla"),
)

AGRUPACIONES = (
    ('AUTO', "Automatico",
     "Prueba las dos formas y se queda con la que da mas texeles por "
     "centimetro de modelo. Es lo mas seguro"),
    ('GRUPO', "Por material",
     "Cada material conserva su reparto de UV tal cual y se le reserva un "
     "rectangulo. Rapido y no toca lo que ya estaba bien"),
    ('ISLA', "Por isla",
     "Reparte isla a isla. Aprovecha mas el atlas pero tarda mas y separa "
     "trozos que estaban juntos"),
)

DENSIDADES = (
    ('UNIFORME', "Uniforme",
     "Los mismos texeles por metro en toda la seleccion. Es lo que se "
     "espera de un asset de videojuego"),
    ('TEXEL', "Como el original",
     "Respeta los texeles que tenia cada textura de origen. Conserva mejor "
     "el detalle de las texturas grandes"),
    ('ORIGINAL', "Proporcion UV",
     "Reparte segun el tamano que ya tenian las UV"),
)

EMPAQUETADOS = (
    ('ORM', "ORM (glTF, Unreal)",
     "R oclusion, G rugosidad, B metalico. Tres mapas en uno"),
    ('MASCARA', "Mask Map (Unity)",
     "R metalico, G oclusion, B libre, A suavidad"),
    ('SIN', "Mapas sueltos",
     "Un archivo para cada canal. Ocupa mas memoria en el motor"),
)

ORIGENES = (
    ('CAJA', "Centro de la caja",
     "Centro geometrico de la caja envolvente"),
    ('MEDIANA', "Centro de masa",
     "Media de la geometria. Se va hacia donde hay mas malla"),
    ('BASE', "A los pies",
     "Centrado en XY y apoyado en la Z mas baja. Comodo para personajes "
     "y props que van sobre el suelo"),
    ('SIN', "No tocar", "Deja el origen donde este"),
)

CAPAS_UV = (
    ('CONSERVAR', "Atlas primero, y guardar las viejas",
     "El atlas queda como canal 0, que es el que usan los materiales en "
     "cualquier motor, y las UV originales se conservan detras por si "
     "hacen falta para mapas de detalle o decals"),
    ('UNA', "Solo el atlas",
     "Borra los demas canales UV. Es lo mas ligero en memoria de vertice"),
)

GUARDADO = (
    ('EMPAQUETAR', "Dentro del .blend",
     "Las texturas viajan empaquetadas en el archivo"),
    ('DISCO', "En una carpeta",
     "Escribe los PNG en la carpeta que elijas"),
)


class ATLARA_Informe(PropertyGroup):
    valido: BoolProperty(default=False)

    objetos: IntProperty(default=0)
    ignorados: IntProperty(default=0)
    luces: IntProperty(default=0)
    materiales: IntProperty(default=0)
    ranuras: IntProperty(default=0)
    planos: IntProperty(default=0)
    texturizados: IntProperty(default=0)
    sin_material: IntProperty(default=0)
    sin_entender: IntProperty(default=0)
    imagenes: IntProperty(default=0)
    sin_uv: IntProperty(default=0)
    texeles: FloatProperty(default=0.0)
    resolucion: IntProperty(default=0)

    usa_metal: BoolProperty(default=False)
    usa_rugosidad: BoolProperty(default=False)
    usa_normal: BoolProperty(default=False)
    usa_emision: BoolProperty(default=False)
    usa_alfa: BoolProperty(default=False)

    ocupacion: FloatProperty(default=0.0)
    util: FloatProperty(default=0.0)
    resultado: StringProperty(default="")
    avance: StringProperty(default="")

    def limpiar(self) -> None:
        self.valido = False
        self.resultado = ""
        self.avance = ""

    def cargar(self, datos: dict) -> None:
        for clave, valor in datos.items():
            if hasattr(self, clave):
                setattr(self, clave, valor)
        self.valido = True

    @property
    def drawcalls_antes(self) -> int:
        return max(self.ranuras, self.objetos)


class ATLARA_Ajustes(PropertyGroup):
    informe: PointerProperty(type=ATLARA_Informe)

    modo: EnumProperty(name="Modo", items=MODOS, default='TODO')
    resolucion: EnumProperty(name="Resolucion", items=RESOLUCIONES,
                             default='0')
    margen_auto: BoolProperty(
        name="Margen automatico", default=True,
        description="Lo calcula segun la resolucion del atlas, que es de "
                    "lo que depende el sangrado de los mipmaps")
    margen: IntProperty(
        name="Margen", default=8, min=0, soft_max=64,
        description="Texeles de relleno alrededor de cada trozo. Evita que "
                    "se cuelen colores del vecino al alejarse (mipmaps)")
    empaquetador: EnumProperty(name="Empaquetado", items=EMPAQUETADORES,
                               default='AUTO')
    forma: EnumProperty(
        name="Contorno", items=FORMAS, default='CONCAVE',
        description="Cuanto detalle del contorno se tiene en cuenta al "
                    "encajar unas islas con otras")
    agrupacion: EnumProperty(name="Reparto", items=AGRUPACIONES,
                             default='AUTO')
    densidad: EnumProperty(name="Densidad", items=DENSIDADES,
                           default='UNIFORME')
    celda_plana: IntProperty(
        name="Celda de color", default=16, min=2, soft_max=64,
        description="Lado en texeles de la casilla que se lleva cada "
                    "material sin texturas")
    rotar: BoolProperty(
        name="Girar trozos", default=True,
        description="Permite girar 90 grados para que quepa mas")
    orientar: BoolProperty(
        name="Enderezar trozos", default=True,
        description="Gira cada trozo hasta que su rectangulo envolvente es "
                    "el mas pequeno posible. Las islas en diagonal dejan de "
                    "malgastar atlas. Como despues se hornea, girar no "
                    "estropea nada")

    empaquetado: EnumProperty(name="Canales", items=EMPAQUETADOS,
                              default='ORM')
    auto_canales: BoolProperty(
        name="Detectar canales", default=True,
        description="Solo hornea los canales que los materiales usan de "
                    "verdad. Menos texturas y menos espera")
    usar_normal: BoolProperty(name="Normal", default=True)
    usar_metal: BoolProperty(name="Metalico", default=True)
    usar_rugosidad: BoolProperty(name="Rugosidad", default=True)
    usar_emision: BoolProperty(
        name="Emision", default=True,
        description="Con la deteccion de canales encendida no cuesta nada: "
                    "solo se genera si algun material emite luz")
    usar_alfa: BoolProperty(
        name="Alfa", default=True,
        description="Con la deteccion de canales encendida no cuesta nada: "
                    "solo se genera si algun material es transparente")
    usar_ao: BoolProperty(
        name="Oclusion", default=False,
        description="Calcula la oclusion ambiental de la geometria y la "
                    "mete en el mapa. Es lo que mas tarda")
    ao_muestras: IntProperty(
        name="Muestras", default=64, min=1, soft_max=512,
        description="Calidad de la oclusion. El horneado va sin reduccion "
                    "de ruido, asi que por debajo de 64 se nota el grano")
    voltear_verde: BoolProperty(
        name="Verde invertido (DirectX)", default=False,
        description="Unreal y 3ds Max esperan el canal verde al reves que "
                    "Blender, Unity o glTF")

    prefijo: StringProperty(
        name="Nombre", default="Atlas",
        description="Con el que se nombran el material y las texturas")
    guardado: EnumProperty(name="Texturas", items=GUARDADO,
                           default='EMPAQUETAR')
    carpeta: StringProperty(
        name="Carpeta", default="//texturas/", subtype='DIR_PATH')

    aplicar_transformaciones: BoolProperty(
        name="Aplicar rotacion y escala", default=True,
        description="Deja la escala en 1. Hace falta para que la densidad "
                    "de texel salga igual en todos los objetos")
    origen: EnumProperty(name="Pivote", items=ORIGENES, default='CAJA')
    mover_a_cero: BoolProperty(
        name="Llevar a 0,0,0", default=True,
        description="Coloca cada objeto en el origen del mundo. Se "
                    "amontonan en el visor, pero en el motor cada asset "
                    "entra centrado")
    capas_uv: EnumProperty(
        name="Canales UV", items=CAPAS_UV, default='CONSERVAR')
    reproyectar: BoolProperty(
        name="Reproyectar UVs", default=False,
        description="Vuelve a desplegar con Smart UV Project antes de "
                    "atlasear. Para mallas con las UV rotas o solapadas")
    angulo: FloatProperty(
        name="Angulo", default=1.15, min=0.0, max=1.5708, subtype='ANGLE',
        description="Limite de angulo del Smart UV Project")


def filas_informe(i) -> list:
    filas = [
        ("Seleccion", None, None, True, False),
        ("Objetos de malla", i.objetos, None, i.objetos > 0, True),
    ]
    if i.luces:
        filas.append(("Luces omitidas", i.luces, None, True, False))
    if i.ignorados:
        filas.append(("Otros objetos omitidos", i.ignorados, None,
                      True, False))
    filas.extend([
        ("Materiales", None, None, True, False),
        ("Distintos", i.materiales, None, True, False),
        ("Ranuras (drawcalls)", i.ranuras, None, True, False),
        ("Con textura", i.texturizados, None, True, False),
        ("Planos, solo color", i.planos, None, True, False),
    ])
    if i.sin_material:
        filas.append(("Objetos sin material", i.sin_material, None,
                      True, False))
    if i.sin_entender:
        filas.append(("Shaders no reconocidos", i.sin_entender, None,
                      i.sin_entender == 0, True))
    filas.extend([
        ("Texturas", None, None, True, False),
        ("Imagenes distintas", i.imagenes, None, True, False),
        ("Megatexeles de origen", None, "%.1f" % (i.texeles / 1e6),
         True, False),
        ("Resolucion del atlas", None, "%d" % i.resolucion, True, False),
    ])
    if i.sin_uv:
        filas.append(("Objetos sin UV", i.sin_uv, None, True, False))
    canales = []
    for etiqueta, activo in (("normal", i.usa_normal), ("metal", i.usa_metal),
                             ("rugosidad", i.usa_rugosidad),
                             ("emision", i.usa_emision), ("alfa", i.usa_alfa)):
        if activo:
            canales.append(etiqueta)
    filas.append(("Canales en uso", None,
                  ", ".join(canales) if canales else "solo color",
                  True, False))
    filas.extend([
        ("Resultado", None, None, True, False),
        ("Drawcalls ahora", i.drawcalls_antes, None, True, False),
        ("Drawcalls despues", i.objetos, None, True, False),
    ])
    if i.util > 0.0:
        # Texeles que llevan triangulos de verdad. No es lo mismo que
        # cuanto atlas ocupan las cajas: dentro de la caja de una isla en
        # forma de L sobra sitio, y ese sitio no da nitidez ninguna.
        filas.append(("Texeles utiles", None, "%d%%" % int(i.util * 100),
                      i.util > 0.45, False))
    return filas


CLASES = (ATLARA_Informe, ATLARA_Ajustes)


def register():
    for clase in CLASES:
        bpy.utils.register_class(clase)
    bpy.types.Scene.atlara = PointerProperty(type=ATLARA_Ajustes)


def unregister():
    del bpy.types.Scene.atlara
    for clase in reversed(CLASES):
        bpy.utils.unregister_class(clase)

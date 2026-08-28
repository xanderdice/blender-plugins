# SPDX-License-Identifier: GPL-3.0-or-later
"""Horneado de los canales y mezcla en los mapas finales.

Cada canal se hornea por separado sobre la misma imagen compartida por
todos los objetos, con `use_clear` apagado: asi cada objeto escribe solo
en su parcela del atlas y los demas no se pisan.

Despues, metalico, rugosidad y oclusion se meten en los canales R, G y B
de un unico mapa. Tres texturas en blanco y negro pasan a ser una sola:
un tercio de memoria en el motor de juego.
"""

from __future__ import annotations

import os

import bpy
import numpy as np

from . import materiales

SUFIJOS = {
    'BASE': "BaseColor",
    'NORMAL': "Normal",
    'EMISION': "Emission",
    'METAL': "Metallic",
    'RUGOSIDAD': "Roughness",
    'AO': "AO",
    'ORM': "ORM",
    'MASCARA': "MaskMap",
}

TIPO_HORNEADO = {
    'BASE': 'EMIT',
    'METAL': 'EMIT',
    'RUGOSIDAD': 'EMIT',
    'EMISION': 'EMIT',
    'ALFA': 'EMIT',
    'NORMAL': 'NORMAL',
    'AO': 'AO',
}

FONDO = {
    'BASE': (0.0, 0.0, 0.0, 1.0),
    'METAL': (0.0, 0.0, 0.0, 1.0),
    'RUGOSIDAD': (0.5, 0.5, 0.5, 1.0),
    'EMISION': (0.0, 0.0, 0.0, 1.0),
    'ALFA': (1.0, 1.0, 1.0, 1.0),
    'NORMAL': (0.5, 0.5, 1.0, 1.0),
    'AO': (1.0, 1.0, 1.0, 1.0),
}

DATOS = ('NORMAL', 'METAL', 'RUGOSIDAD', 'AO', 'ALFA', 'ORM', 'MASCARA')


# --------------------------------------------------------------- imagenes

def nueva_imagen(nombre, ancho, alto, canal, alfa=False):
    """Imagen nueva del tamano del atlas, con el fondo del canal.

    Devuelve (imagen, renombrada). `renombrada` es la del mismo nombre
    que hubiera de una pasada anterior, apartada con sufijo, por si hay
    que devolverle el nombre al cancelar.
    """
    renombrada = None
    previa = bpy.data.images.get(nombre)
    if previa is not None:
        renombrada = (previa, nombre)
        previa.name = nombre + ".viejo"
        previa.use_fake_user = False
    img = bpy.data.images.new(nombre, ancho, alto, alpha=alfa,
                              float_buffer=False, is_data=canal in DATOS)
    img.colorspace_settings.name = 'Non-Color' if canal in DATOS else 'sRGB'
    if canal in DATOS or alfa:
        img.alpha_mode = 'CHANNEL_PACKED'
    img.generated_color = FONDO.get(canal, (0.0, 0.0, 0.0, 1.0))
    return img, renombrada


def leer_pixeles(img):
    ancho, alto = img.size
    datos = np.empty(ancho * alto * 4, dtype=np.float32)
    img.pixels.foreach_get(datos)
    return datos.reshape(alto, ancho, 4)


def escribir_pixeles(img, datos) -> None:
    img.pixels.foreach_set(np.ascontiguousarray(
        datos, dtype=np.float32).reshape(-1))
    img.update()


PROHIBIDOS = '<>:"/\\|?*'


def nombre_de_fichero(nombre) -> str:
    """Quita de un nombre lo que Windows no admite en un fichero.

    El nombre del objeto acaba dentro del nombre de la imagen, y basta
    una barra para que el PNG se vaya a una subcarpeta inventada, o dos
    puntos para que no se escriba y nadie se entere.
    """
    limpio = "".join("_" if c in PROHIBIDOS or ord(c) < 32 else c
                     for c in nombre).strip(" .")
    return limpio or "atlas"


def guardar(img, carpeta) -> str:
    """A disco si hay carpeta, si no empaquetada dentro del .blend."""
    img.file_format = 'PNG'
    if carpeta and not (carpeta.startswith("//") and not bpy.data.filepath):
        ruta = os.path.join(bpy.path.abspath(carpeta),
                            nombre_de_fichero(img.name) + ".png")
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        img.filepath_raw = ruta
        img.save()
        return ruta
    img.filepath_raw = "//" + img.name + ".png"
    try:
        img.pack()
    except RuntimeError:
        return ""
    return "(empaquetada)"


def tirar_imagenes(imagenes) -> None:
    for img in imagenes:
        if img is None:
            continue
        try:
            bpy.data.images.remove(img, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass


# ----------------------------------------------------------------- escena

def preparar_escena(context, margen, muestras):
    escena = context.scene
    previo = {
        'motor': escena.render.engine,
        'margen': escena.render.bake.margin,
        'tipo_margen': escena.render.bake.margin_type,
        'limpiar': escena.render.bake.use_clear,
        'a_activo': escena.render.bake.use_selected_to_active,
        'destino': escena.render.bake.target,
        'muestras': getattr(escena.cycles, "samples", 1)
        if hasattr(escena, "cycles") else 1,
        'ruido': getattr(escena.cycles, "use_denoising", False)
        if hasattr(escena, "cycles") else False,
    }
    escena.render.engine = 'CYCLES'
    escena.render.bake.margin = margen
    escena.render.bake.margin_type = 'ADJACENT_FACES'
    escena.render.bake.use_clear = False
    escena.render.bake.use_selected_to_active = False
    escena.render.bake.target = 'IMAGE_TEXTURES'
    if hasattr(escena, "cycles"):
        escena.cycles.samples = max(1, muestras)
        escena.cycles.use_denoising = False
    return previo


def restaurar_escena(context, previo) -> None:
    escena = context.scene
    try:
        escena.render.engine = previo['motor']
    except TypeError:
        pass
    escena.render.bake.margin = previo['margen']
    escena.render.bake.margin_type = previo['tipo_margen']
    escena.render.bake.use_clear = previo['limpiar']
    escena.render.bake.use_selected_to_active = previo['a_activo']
    escena.render.bake.target = previo['destino']
    if hasattr(escena, "cycles"):
        escena.cycles.samples = previo['muestras']
        escena.cycles.use_denoising = previo['ruido']


def solo(context, obj) -> None:
    for o in context.view_layer.objects:
        if o.select_get():
            o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def visible(obj):
    """Deja el objeto visible para el horneado y devuelve como estaba."""
    estado = (obj.hide_render, obj.hide_viewport, obj.hide_get())
    obj.hide_render = False
    obj.hide_viewport = False
    obj.hide_set(False)
    return estado


def restaurar_visible(obj, estado) -> None:
    obj.hide_render, obj.hide_viewport, oculto = estado
    obj.hide_set(oculto)


# --------------------------------------------------------------- horneado

def hornear_objeto(context, obj, canal, imagen, capa_uv, nombre_uv,
                   voltear_verde=False) -> str:
    """Hornea un canal de un objeto sobre la imagen del atlas."""
    ranuras = list(obj.material_slots)
    originales = [r.material for r in ranuras]
    temporales = []
    sin_ranura = not ranuras

    try:
        if sin_ranura:
            obj.data.materials.append(None)
            ranuras = list(obj.material_slots)
            originales = [None]
        for ranura in ranuras:
            copia = materiales.copia_para(ranura.material, canal, nombre_uv,
                                          imagen)
            temporales.append(copia)
            ranura.material = copia

        solo(context, obj)
        argumentos = {
            'type': TIPO_HORNEADO[canal],
            'use_clear': False,
            'use_selected_to_active': False,
            'target': 'IMAGE_TEXTURES',
            'uv_layer': capa_uv,
        }
        if canal == 'NORMAL':
            argumentos['normal_space'] = 'TANGENT'
            if voltear_verde:
                argumentos['normal_g'] = 'NEG_Y'
        bpy.ops.object.bake(**argumentos)
        return ""
    except RuntimeError as ex:
        return "%s / %s: %s" % (obj.name, materiales.NOMBRE_CANAL[canal], ex)
    finally:
        for ranura, mat in zip(ranuras, originales):
            try:
                ranura.material = mat
            except ReferenceError:
                pass
        if sin_ranura and obj.data.materials:
            obj.data.materials.pop()
        materiales.tirar(temporales)


def apagar_los_demas(context, obj):
    """Para la oclusion: que los vecinos no proyecten sombra encima."""
    guardado = []
    for otro in context.scene.objects:
        if otro is obj or otro.type not in ('MESH', 'CURVE', 'SURFACE',
                                            'META', 'FONT'):
            continue
        guardado.append((otro, otro.hide_render))
        otro.hide_render = True
    return guardado


def encender_los_demas(guardado) -> None:
    for otro, estado in guardado:
        try:
            otro.hide_render = estado
        except ReferenceError:
            pass


# ------------------------------------------------------------- composicion

def pintar_celdas(img, celdas) -> None:
    """Escribe el color exacto de cada material plano en su celda."""
    if not celdas:
        return
    datos = leer_pixeles(img)
    alto, ancho = datos.shape[0], datos.shape[1]
    for (x, y, lado), color in celdas:
        x0, y0 = int(max(0, x)), int(max(0, y))
        x1, y1 = int(min(ancho, x + lado)), int(min(alto, y + lado))
        if x1 <= x0 or y1 <= y0:
            continue
        datos[y0:y1, x0:x1] = np.asarray(color, dtype=np.float32)
    escribir_pixeles(img, datos)


def meter_alfa(base, alfa) -> None:
    datos = leer_pixeles(base)
    datos[:, :, 3] = leer_pixeles(alfa)[:, :, 0]
    escribir_pixeles(base, datos)


def mezclar(nombre, ancho, alto, canales, modo):
    """Junta metalico, rugosidad y oclusion en un solo mapa RGB(A).

    ORM     : R oclusion, G rugosidad, B metalico  (glTF, Unreal)
    MASCARA : R metalico, G oclusion, B 1, A suavidad  (Unity)
    """
    uno = np.ones((alto, ancho), dtype=np.float32)
    metal = leer_pixeles(canales['METAL'])[:, :, 0] \
        if canales.get('METAL') is not None else uno * 0.0
    rugo = leer_pixeles(canales['RUGOSIDAD'])[:, :, 0] \
        if canales.get('RUGOSIDAD') is not None else uno * 0.5
    ao = leer_pixeles(canales['AO'])[:, :, 0] \
        if canales.get('AO') is not None else uno

    if modo == 'MASCARA':
        img, _vieja = nueva_imagen(nombre, ancho, alto, 'MASCARA', alfa=True)
        datos = np.stack([metal, ao, uno, 1.0 - rugo], axis=-1)
    else:
        img, _vieja = nueva_imagen(nombre, ancho, alto, 'ORM', alfa=False)
        datos = np.stack([ao, rugo, metal, uno], axis=-1)
    escribir_pixeles(img, datos)
    return img

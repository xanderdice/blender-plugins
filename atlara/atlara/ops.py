# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores de Atlara.

El orden importa y es este:

  1. Se descartan luces, camaras y todo lo que no sea malla.
  2. Se crea la capa UV "Atlas" copiando la original.
  3. Se leen los materiales: cuales tienen textura y cuales son un color.
  4. Se reparte el atlas y se mueven las UV a su parcela.
  5. Se hornea cada canal de cada objeto sobre las mismas imagenes.
  6. Se pintan las celdas de los materiales planos con su color exacto.
  7. Se mezclan metalico, rugosidad y oclusion en un solo mapa.
  8. Se crea un unico material y se le cuelga a todos los objetos.
  9. Ahora, y no antes, se aplican rotacion y escala, se centra el pivote
     y se lleva cada objeto a 0,0,0.

Que el paso 9 vaya al final no es capricho: mientras solo se hayan
tocado capas UV nuevas y las imagenes del atlas, cancelar a media faena
puede dejar la escena exactamente como estaba.

Los objetos nunca se unen: siguen siendo objetos separados, solo que
comparten material.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator
from mathutils import Vector

from . import proceso
from .proceso import canales_pedidos, fichas_de, resolucion_de, texeles_de

INTERVALO = 0.05


# ------------------------------------------------------------- seleccion

def clasificar(context):
    """Separa la seleccion en mallas, luces y el resto."""
    mallas, luces, otros = [], [], []
    vistos = set()
    candidatos = list(context.selected_objects)
    activo = context.active_object
    if activo is not None and activo not in candidatos:
        candidatos.append(activo)
    for obj in candidatos:
        if obj.name in vistos:
            continue
        vistos.add(obj.name)
        if obj.type == 'MESH':
            mallas.append(obj)
        elif obj.type == 'LIGHT':
            luces.append(obj)
        else:
            otros.append(obj)
    return mallas, luces, otros


def volver_a_objeto(context):
    activo = context.active_object
    if activo is not None and activo.mode != 'OBJECT':
        modo = activo.mode
        bpy.ops.object.mode_set(mode='OBJECT')
        return modo
    return None


def sobre(context, obj):
    return context.temp_override(
        object=obj, active_object=obj, selected_objects=[obj],
        selected_editable_objects=[obj])


def colocar_origen(context, obj, donde) -> None:
    if donde == 'SIN':
        return
    cursor = context.scene.cursor
    previo = cursor.location.copy()
    try:
        if donde == 'MEDIANA':
            with sobre(context, obj):
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY',
                                          center='MEDIAN')
        elif donde == 'CAJA':
            with sobre(context, obj):
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY',
                                          center='BOUNDS')
        else:
            esquinas = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            cursor.location = Vector((
                (min(v.x for v in esquinas)
                 + max(v.x for v in esquinas)) / 2.0,
                (min(v.y for v in esquinas)
                 + max(v.y for v in esquinas)) / 2.0,
                min(v.z for v in esquinas)))
            with sobre(context, obj):
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    except RuntimeError:
        pass
    finally:
        cursor.location = previo


def unico_usuario(obj, avisos) -> None:
    if obj.data.users <= 1:
        return
    obj.data = obj.data.copy()
    avisos.append("%s compartia la malla con otro objeto: se le hizo una "
                  "copia propia" % obj.name)


def colocar_objeto(context, obj, ajustes, avisos) -> None:
    """Transformaciones, pivote y traslado al origen. Va al final."""
    if ajustes.aplicar_transformaciones:
        if obj.parent is not None:
            avisos.append("%s cuelga de un padre: no se aplicaron las "
                          "transformaciones" % obj.name)
        else:
            try:
                with sobre(context, obj):
                    bpy.ops.object.transform_apply(
                        location=False, rotation=True, scale=True)
            except RuntimeError as ex:
                avisos.append("%s: no se pudo aplicar la transformacion (%s)"
                              % (obj.name, ex))
    colocar_origen(context, obj, ajustes.origen)
    if ajustes.mover_a_cero:
        obj.location = (0.0, 0.0, 0.0)
        obj.delta_location = (0.0, 0.0, 0.0)


# --------------------------------------------------------------- informe

def informe_de(context, ajustes) -> dict:
    mallas, luces, otros = clasificar(context)
    fichas = fichas_de(mallas)
    imagenes = set()
    ranuras = 0
    planos = texturizados = sin_entender = sin_material = sin_uv = 0

    for ficha in fichas.values():
        if ficha['plano']:
            planos += 1
        else:
            texturizados += 1
        if not ficha['entendido']:
            sin_entender += 1
        imagenes |= ficha['imagenes']

    for obj in mallas:
        ranuras += max(1, len(obj.material_slots))
        if not obj.material_slots:
            sin_material += 1
        if not obj.data.uv_layers:
            sin_uv += 1

    texeles = texeles_de(fichas)
    canales = canales_pedidos(ajustes, fichas)
    return {
        'objetos': len(mallas), 'luces': len(luces), 'ignorados': len(otros),
        'materiales': len(fichas), 'ranuras': ranuras,
        'planos': planos, 'texturizados': texturizados,
        'sin_entender': sin_entender, 'sin_material': sin_material,
        'sin_uv': sin_uv, 'imagenes': len(imagenes), 'texeles': texeles,
        'resolucion': resolucion_de(ajustes, texeles, planos, texturizados),
        'usa_metal': 'METAL' in canales,
        'usa_rugosidad': 'RUGOSIDAD' in canales,
        'usa_normal': 'NORMAL' in canales,
        'usa_emision': 'EMISION' in canales,
        'usa_alfa': 'ALFA' in canales,
    }


# ------------------------------------------------------------ operadores

class ATLARA_OT_analizar(Operator):
    bl_idname = "atlara.analizar"
    bl_label = "Analizar seleccion"
    bl_description = ("Cuenta objetos, materiales y texturas, y dice cuantos "
                      "drawcalls te vas a ahorrar")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        ajustes = context.scene.atlara
        datos = informe_de(context, ajustes)
        ajustes.informe.cargar(datos)
        ajustes.informe.resultado = ""
        ajustes.informe.avance = ""
        if not datos['objetos']:
            self.report({'WARNING'}, "No hay ninguna malla seleccionada")
            return {'CANCELLED'}
        self.report({'INFO'}, "%d objetos, %d materiales, %d ranuras -> "
                    "%d drawcalls" % (datos['objetos'], datos['materiales'],
                                      datos['ranuras'], datos['objetos']))
        return {'FINISHED'}


class ATLARA_OT_atlas(Operator):
    bl_idname = "atlara.atlas"
    bl_label = "Fundir en un atlas"
    bl_description = ("Hornea todos los materiales de la seleccion en un "
                      "unico atlas y deja un solo material, sin unir los "
                      "objetos. Escape para cancelar")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    # ------------------------------------------------------ dos caminos

    def execute(self, context):
        """De un tiron. Es lo que se usa desde scripts y en background."""
        if not self._arrancar(context):
            return {'CANCELLED'}
        ventana = context.window_manager
        ventana.progress_begin(0.0, 1.0)
        self._barra = True
        try:
            while not self.tanda.terminado:
                if not self.tanda.avanzar(context):
                    break
                ventana.progress_update(self.tanda.fraccion())
        except BaseException:
            self.tanda.tirar_todo(context)
            self._soltar(context)
            raise
        self._soltar(context)
        return self._acabar(context)

    def invoke(self, context, event):
        """En la interfaz: modal, con avance a la vista y cancelable."""
        if bpy.app.background or context.window is None:
            return self.execute(context)
        if not self._arrancar(context):
            return {'CANCELLED'}
        ventana = context.window_manager
        self._reloj = ventana.event_timer_add(INTERVALO, window=context.window)
        ventana.modal_handler_add(self)
        ventana.progress_begin(0.0, 1.0)
        self._barra = True
        self._pintar(context)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        """Blender la llama si aborta el modal por su cuenta.

        Pasa, por ejemplo, al abrir otro .blend a media faena. Lo que no
        puede quedarse colgado es el reloj, la barra de progreso ni el
        texto de la barra de estado.
        """
        try:
            self._soltar(context)
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        tanda = getattr(self, "tanda", None)
        if tanda is not None:
            try:
                tanda.tirar_todo(context)
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def modal(self, context, event):
        if event.type in {'ESC'} and event.value == 'PRESS':
            return self._cancelar(context)
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        try:
            self.tanda.avanzar(context)
        except BaseException as ex:
            self._soltar(context)
            self.tanda.tirar_todo(context)
            self.report({'ERROR'}, "Atlara se rompio: %s" % ex)
            return {'CANCELLED'}
        if self.tanda.error or self.tanda.terminado:
            self._soltar(context)
            return self._acabar(context)
        self._pintar(context)
        return {'RUNNING_MODAL'}

    # -------------------------------------------------------------- tramos

    @staticmethod
    def _marcar_historial(mensaje) -> bool:
        """Deja un punto de retorno en el historial de deshacer.

        Hace falta por dos motivos: `ed.undo` ni siquiera se puede llamar
        mientras no haya un `undo_push` previo, y un modal que acaba en
        CANCELLED no empuja paso ninguno, asi que sin esto el siguiente
        Ctrl+Z del usuario se comeria lo que hizo *antes* de Atlara.
        """
        try:
            bpy.ops.ed.undo_push(message=mensaje)
            return True
        except RuntimeError:
            return False

    def _arrancar(self, context) -> bool:
        ajustes = context.scene.atlara
        ajustes.informe.avance = ""
        self.tanda = None
        self._reloj = None
        self._barra = False
        self._ultimo = None
        volver_a_objeto(context)
        mallas, luces, _otros = clasificar(context)
        if not mallas:
            self.report({'ERROR'}, "Selecciona al menos una malla")
            return False
        for obj in mallas:
            if obj.library is not None or obj.data.library is not None:
                self.report({'ERROR'}, "%s viene de una biblioteca enlazada: "
                            "hazlo local primero" % obj.name)
                return False

        avisos = []
        for obj in mallas:
            unico_usuario(obj, avisos)

        if ajustes.modo == 'TODO':
            lotes = [("", mallas)]
        else:
            lotes = [("_" + o.name, [o]) for o in mallas]
        self.tanda = proceso.Tanda(lotes, ajustes)
        self.tanda.avisos.extend(avisos)
        self.mallas = mallas
        self.luces = luces
        self._historial = self._marcar_historial("Atlara: antes de fundir")
        return True

    def _pintar(self, context) -> None:
        ventana = context.window_manager
        ventana.progress_update(self.tanda.fraccion())
        texto = "Atlara: %s  —  %d%%   [Esc para cancelar]" % (
            self.tanda.etiqueta(), int(self.tanda.fraccion() * 100))
        # El reloj dispara veinte veces por segundo: repintar solo cuando
        # el texto cambia de verdad.
        if texto == getattr(self, "_ultimo", None):
            return
        self._ultimo = texto
        try:
            context.workspace.status_text_set(texto)
        except AttributeError:
            pass
        context.scene.atlara.informe.avance = texto
        # Por todas las ventanas, no solo la del raton: Blender puede
        # tener varias abiertas.
        for pantalla in ventana.windows:
            for area in pantalla.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    def _soltar(self, context) -> None:
        ventana = context.window_manager
        if getattr(self, "_reloj", None) is not None:
            ventana.event_timer_remove(self._reloj)
            self._reloj = None
        if getattr(self, "_barra", False):
            ventana.progress_end()
            self._barra = False
        self._ultimo = None
        try:
            context.workspace.status_text_set(None)
        except AttributeError:
            pass
        context.scene.atlara.informe.avance = ""

    def _cancelar(self, context):
        self._soltar(context)
        hechos = len(self.tanda.resultados)
        self.tanda.tirar_todo(context)
        if not hechos:
            self.report({'WARNING'},
                        "Cancelado. La escena se quedo como estaba")
            return {'CANCELLED'}

        # Ya habia atlas terminados. Deshacerlos a mano no se puede: al
        # rematar se borraron las capas UV originales. Se vuelve por el
        # historial, y despues de eso no se puede tocar nada mas: todas
        # las referencias de Python han quedado muertas.
        self.report({'WARNING'}, "Cancelado con %d atlas ya hechos: se "
                    "deshacen tambien" % hechos)
        if self._historial and self._marcar_historial("Atlara: cancelado"):
            try:
                bpy.ops.ed.undo()
            except RuntimeError:
                self.report({'WARNING'}, "No se pudo deshacer solo: usa "
                            "Ctrl+Z para volver atras")
        else:
            self.report({'WARNING'}, "Usa Ctrl+Z para deshacer los atlas "
                        "que ya se habian hecho")
        return {'CANCELLED'}

    def _acabar(self, context):
        ajustes = context.scene.atlara
        tanda = self.tanda
        if tanda.error:
            hechos = len(tanda.resultados)
            tanda.tirar_todo(context)
            for aviso in tanda.avisos[:6]:
                self.report({'WARNING'}, aviso)
            self.report({'ERROR'}, tanda.error)
            if hechos:
                # Igual que al cancelar: los atlas ya rematados no se
                # pueden deshacer a mano porque al rematar se borraron
                # sus capas UV viejas. Se vuelve por el historial, y
                # despues de eso no se puede tocar nada mas.
                self.report({'WARNING'}, "Se deshacen tambien los %d atlas "
                            "que ya estaban hechos" % hechos)
                if self._historial \
                        and self._marcar_historial("Atlara: cancelado"):
                    try:
                        bpy.ops.ed.undo()
                    except RuntimeError:
                        self.report({'WARNING'}, "Usa Ctrl+Z para volver "
                                    "atras")
                else:
                    self.report({'WARNING'}, "Usa Ctrl+Z para deshacer los "
                                "atlas que ya se habian hecho")
            return {'CANCELLED'}

        for obj in self.mallas:
            colocar_objeto(context, obj, ajustes, tanda.avisos)

        datos = informe_de(context, ajustes)
        if tanda.resultados:
            datos['ocupacion'] = tanda.resultados[0]['ocupacion']
            datos['util'] = tanda.resultados[0]['util']
        ajustes.informe.cargar(datos)

        for aviso in tanda.avisos[:8]:
            self.report({'WARNING'}, aviso)
        if len(tanda.avisos) > 8:
            self.report({'WARNING'}, "y %d avisos mas"
                        % (len(tanda.avisos) - 8))

        resumen = self._resumen(tanda)
        ajustes.informe.resultado = resumen
        ajustes.informe.avance = ""
        self.report({'INFO'}, resumen)
        return {'FINISHED'}

    def _resumen(self, tanda) -> str:
        if not tanda.resultados:
            return "No se genero ningun atlas"
        uno = tanda.resultados[0]
        reparto = {
            'FORMA': "por la forma real",
            'ISLA': "por isla",
        }.get(uno['agrupacion'], "por material")
        if len(tanda.resultados) == 1:
            texto = ("%s: %d objetos con un solo material, atlas de %d px, "
                     "%d%% de texeles utiles, reparto %s"
                     % (uno['material'], uno['objetos'], uno['resolucion'],
                        int(uno['util'] * 100), reparto))
        else:
            texto = ("%d atlas creados, uno por objeto, de %d px, reparto %s"
                     % (len(tanda.resultados), uno['resolucion'], reparto))
        if self.luces:
            texto += ". %d luces omitidas" % len(self.luces)
        return texto


class ATLARA_OT_centrar(Operator):
    bl_idname = "atlara.centrar"
    bl_label = "Centrar y llevar a cero"
    bl_description = ("Aplica rotacion y escala, pone el pivote en el centro "
                      "y coloca cada objeto en 0,0,0")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        ajustes = context.scene.atlara
        volver_a_objeto(context)
        mallas, luces, _otros = clasificar(context)
        if not mallas:
            self.report({'ERROR'}, "Selecciona al menos una malla")
            return {'CANCELLED'}
        avisos = []
        for obj in mallas:
            unico_usuario(obj, avisos)
            colocar_objeto(context, obj, ajustes, avisos)
        for aviso in avisos[:6]:
            self.report({'WARNING'}, aviso)
        self.report({'INFO'}, "%d objetos centrados%s" % (
            len(mallas), ", %d luces omitidas" % len(luces) if luces else ""))
        return {'FINISHED'}


CLASES = (ATLARA_OT_analizar, ATLARA_OT_atlas, ATLARA_OT_centrar)


def register():
    for clase in CLASES:
        bpy.utils.register_class(clase)


def unregister():
    for clase in reversed(CLASES):
        bpy.utils.unregister_class(clase)

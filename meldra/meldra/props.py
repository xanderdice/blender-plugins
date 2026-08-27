from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

TOLERANCIAS = (
    ('PRECISO', "Precise",
     "Only merges vertices sitting in the same spot. Best for AI meshes and "
     "glTF imports"),
    ('NORMAL', "Normal", "Medium tolerance. For scans and photogrammetry"),
    ('AGRESIVO', "Aggressive", "High tolerance. May remove fine detail"),
    ('MANUAL', "Manual", "Exact distance in Blender units"),
)

OBJETIVOS = (
    ('RATIO', "Ratio", "Fraction of triangles kept"),
    ('TRIS', "Triangles", "Triangle count to aim for"),
)

ORIGENES = (
    ('SIN', "Leave As Is", "Keeps the origin where it is"),
    ('CENTRO', "To Center", "Origin at the center of the geometry"),
    ('BASE', "To The Feet", "Origin centered in XY and at the lowest Z"),
)

EJES = (('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", ""))


class MELDRA_Informe(PropertyGroup):
    valido: BoolProperty(default=False)
    objeto: StringProperty(default="")

    verts: IntProperty(default=0)
    aristas: IntProperty(default=0)
    caras: IntProperty(default=0)
    tris: IntProperty(default=0)
    quads: IntProperty(default=0)
    ngons: IntProperty(default=0)
    triangulos: IntProperty(default=0)

    duplicados: IntProperty(default=0)
    islas: IntProperty(default=0)
    isla_mayor: IntProperty(default=0)
    isla_menor: IntProperty(default=0)
    bordes: IntProperty(default=0)
    multiples: IntProperty(default=0)
    alambre: IntProperty(default=0)
    no_contiguas: IntProperty(default=0)
    v_sueltos: IntProperty(default=0)
    v_nomanifold: IntProperty(default=0)
    area_cero: IntProperty(default=0)
    interiores: IntProperty(default=0)

    euler: IntProperty(default=0)
    volumen: FloatProperty(default=0.0)
    cerrada: BoolProperty(default=False)
    invertida: BoolProperty(default=False)
    diagonal: FloatProperty(default=0.0)
    umbral: FloatProperty(default=0.0, precision=6)

    escala_ok: BoolProperty(default=True)
    rotacion_ok: BoolProperty(default=True)
    uvs: IntProperty(default=0)
    shapekeys: IntProperty(default=0)
    modificadores: IntProperty(default=0)
    normales_custom: BoolProperty(default=False)
    usuarios: IntProperty(default=1)

    def cargar(self, datos: dict, obj) -> None:
        for clave, valor in datos.items():
            if hasattr(self, clave):
                setattr(self, clave, valor)
        self.objeto = obj.name
        self.escala_ok = all(abs(s - 1.0) < 1e-4 for s in obj.scale)
        self.rotacion_ok = all(abs(a) < 1e-4 for a in obj.rotation_euler)
        self.uvs = len(obj.data.uv_layers)
        claves = obj.data.shape_keys
        self.shapekeys = len(claves.key_blocks) if claves else 0
        self.modificadores = len(obj.modifiers)
        self.normales_custom = bool(getattr(obj.data, "has_custom_normals", False))
        self.usuarios = obj.data.users
        self.valido = True

    @property
    def apto_para_rig(self) -> bool:
        return (self.cerrada and not self.duplicados and not self.area_cero
                and not self.interiores and not self.v_nomanifold
                and not self.no_contiguas and self.escala_ok
                and self.islas <= 1)


def _solo_armaduras(self, obj) -> bool:
    return obj.type == 'ARMATURE'


class MELDRA_Ajustes(PropertyGroup):
    informe: PointerProperty(type=MELDRA_Informe)

    modo_umbral: EnumProperty(
        name="Tolerance", items=TOLERANCIAS, default='PRECISO')
    umbral_manual: FloatProperty(
        name="Distance", default=0.0001, min=0.0, precision=6, step=0.01,
        unit='LENGTH', description="Weld distance in Blender units")

    aplicar_transformaciones: BoolProperty(
        name="Apply Rotation and Scale", default=True,
        description="Sets scale to 1. Needed for the weld distance and the "
                    "automatic weights to behave")
    quitar_shapekeys: BoolProperty(
        name="Remove Shape Keys", default=True,
        description="Repairing changes the topology and invalidates them. "
                    "They also block the Decimate modifier")
    limpiar_normales_custom: BoolProperty(
        name="Clear Custom Normals", default=True,
        description="Split normals ruin the shading after welding")
    borrar_sueltos: BoolProperty(
        name="Delete Loose Geometry", default=True,
        description="Vertices and edges that belong to no face")
    soldar: BoolProperty(
        name="Weld Vertices", default=True,
        description="Merges duplicate vertices. This is what stops Decimate "
                    "from opening holes")
    degenerados: BoolProperty(
        name="Dissolve Degenerates", default=True,
        description="Zero area faces and zero length edges")
    interiores: BoolProperty(
        name="Delete Interior Faces", default=True,
        description="The inner shell most generated models carry")
    rellenar: BoolProperty(
        name="Fill Holes", default=True,
        description="Closes every remaining boundary loop")
    lados_max: IntProperty(
        name="Max Sides", default=0, min=0, soft_max=64,
        description="Only fill holes with this many sides or fewer. 0 fills all")
    triangular_parches: BoolProperty(
        name="Triangulate Patches", default=True,
        description="Turns the n-gons created when capping into triangles")
    normales: BoolProperty(
        name="Recalculate Normals", default=True,
        description="Makes them consistent and facing outwards")
    borrar_islas: BoolProperty(
        name="Delete Small Loose Parts", default=False,
        description="Deletes geometry. Check with the select button first")
    islas_porcentaje: FloatProperty(
        name="Smaller Than", default=1.0, min=0.0, max=100.0,
        subtype='PERCENTAGE',
        description="Percentage of faces compared to the largest part")

    decimar_modo: EnumProperty(name="Target", items=OBJETIVOS, default='RATIO')
    decimar_ratio: FloatProperty(
        name="Ratio", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        description="Fraction of triangles kept")
    decimar_tris: IntProperty(
        name="Triangles", default=20000, min=4, soft_max=1000000,
        description="Triangle count to aim for")
    decimar_simetria: BoolProperty(
        name="Symmetry", default=False,
        description="Collapse the same way on both sides of the axis")
    decimar_eje: EnumProperty(name="Axis", items=EJES, default='X')
    decimar_aplicar: BoolProperty(
        name="Apply the Modifier", default=True,
        description="Uncheck to add the modifier without applying it")

    armadura: PointerProperty(
        name="Armature", type=bpy.types.Object, poll=_solo_armaduras)
    rig_quitar_grupos: BoolProperty(
        name="Clear Vertex Groups", default=False,
        description="Delete the existing vertex groups before parenting")
    rig_origen: EnumProperty(name="Origin", items=ORIGENES, default='SIN')

    voxel_auto: BoolProperty(
        name="Automatic Size", default=True,
        description="Works the voxel size out from the model diagonal")
    voxel_tam: FloatProperty(
        name="Voxel", default=0.02, min=0.00001, precision=5, unit='LENGTH')
    voxel_detalle: IntProperty(
        name="Detail", default=300, min=16, soft_max=1500,
        description="Voxels along the diagonal. More is finer and heavier")
    quad_caras: IntProperty(
        name="Target Faces", default=5000, min=16, soft_max=500000,
        description="Face count to aim for")


def filas_informe(i) -> list:
    filas = [
        ("Connection", None, None, True, True),
        ("Duplicate vertices", i.duplicados, None, i.duplicados == 0, True),
        ("Loose parts", i.islas, None, i.islas <= 1, True),
        ("Watertight", None, None, True, True),
        ("Holes (boundary edges)", i.bordes, None, i.bordes == 0, True),
        ("Edges with over 2 faces", i.multiples, None, i.multiples == 0, True),
        ("Wire edges", i.alambre, None, i.alambre == 0, True),
        ("Loose vertices", i.v_sueltos, None, i.v_sueltos == 0, True),
        ("Non-manifold vertices", i.v_nomanifold, None,
         i.v_nomanifold == 0, True),
        ("Faces", None, None, True, True),
        ("Zero area", i.area_cero, None, i.area_cero == 0, True),
        ("Interior", i.interiores, None, i.interiores == 0, True),
        ("Inconsistent normals", i.no_contiguas, None,
         i.no_contiguas == 0, True),
        ("N-gons", i.ngons, None, i.ngons == 0, False),
        ("Object", None, None, True, True),
        ("Scale applied", None, "yes" if i.escala_ok else "no",
         i.escala_ok, True),
        ("Shape keys", i.shapekeys, None, i.shapekeys == 0, False),
        ("Modifiers", i.modificadores, None, i.modificadores == 0, False),
        ("UV layers", i.uvs, None, True, False),
    ]
    if i.usuarios > 1:
        filas.append(("Objects sharing the mesh", i.usuarios, None, False, True))
    filas.extend([
        ("Summary", None, None, True, True),
        ("Triangles", i.triangulos, None, True, False),
        ("Euler V-E+F", i.euler, None, True, False),
    ])
    if i.cerrada:
        filas.append(("Volume", None, "%.4g" % i.volumen, True, False))
    filas.append(("Weld distance", None, "%.6f" % i.umbral, True, False))
    return filas


def filas_rig(i) -> list:
    return [
        ("Watertight", None, "yes" if i.cerrada else "no", i.cerrada, True),
        ("No duplicates", i.duplicados, None, i.duplicados == 0, True),
        ("One single piece", i.islas, None, i.islas <= 1, True),
        ("No zero area faces", i.area_cero, None, i.area_cero == 0, True),
        ("No interior faces", i.interiores, None, i.interiores == 0, True),
        ("No non-manifold vertices", i.v_nomanifold, None,
         i.v_nomanifold == 0, True),
        ("Consistent normals", i.no_contiguas, None, i.no_contiguas == 0, True),
        ("Scale applied", None, "yes" if i.escala_ok else "no",
         i.escala_ok, True),
    ]


CLASES = (MELDRA_Informe, MELDRA_Ajustes)


def register():
    for clase in CLASES:
        bpy.utils.register_class(clase)
    bpy.types.Scene.meldra = PointerProperty(type=MELDRA_Ajustes)


def unregister():
    del bpy.types.Scene.meldra
    for clase in reversed(CLASES):
        bpy.utils.unregister_class(clase)

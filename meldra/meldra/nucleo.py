from __future__ import annotations

from collections import defaultdict

import bmesh

FACTORES = {
    'PRECISO': 1e-5,
    'NORMAL': 1e-4,
    'AGRESIVO': 1e-3,
}


def diagonal(bm) -> float:
    it = iter(bm.verts)
    try:
        co = next(it).co
    except StopIteration:
        return 0.0
    minx = maxx = co.x
    miny = maxy = co.y
    minz = maxz = co.z
    for v in it:
        c = v.co
        if c.x < minx:
            minx = c.x
        elif c.x > maxx:
            maxx = c.x
        if c.y < miny:
            miny = c.y
        elif c.y > maxy:
            maxy = c.y
        if c.z < minz:
            minz = c.z
        elif c.z > maxz:
            maxz = c.z
    dx, dy, dz = maxx - minx, maxy - miny, maxz - minz
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def umbral(bm, modo: str = 'PRECISO', manual: float = 1e-4) -> float:
    if modo == 'MANUAL':
        return max(float(manual), 0.0)
    d = diagonal(bm)
    if d <= 0.0:
        return 1e-6
    return max(d * FACTORES.get(modo, 1e-5), 1e-9)


def umbral_por_defecto(d: float) -> float:
    return max(d * 1e-5, 1e-9) if d > 0.0 else 1e-6


def epsilon_area(d: float) -> float:
    return (d * 1e-5) ** 2 if d > 0.0 else 1e-12


def raices(bm) -> list:
    bm.verts.index_update()
    n = len(bm.verts)
    padre = list(range(n))

    def raiz(x: int) -> int:
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for e in bm.edges:
        a, b = raiz(e.verts[0].index), raiz(e.verts[1].index)
        if a != b:
            padre[a] = b
    for i in range(n):
        padre[i] = raiz(i)
    return padre


def islas(bm):
    padre = raices(bm)
    caras = defaultdict(int)
    verts = defaultdict(int)
    for v in bm.verts:
        verts[padre[v.index]] += 1
    for f in bm.faces:
        caras[padre[f.verts[0].index]] += 1
    return padre, caras, verts


def contar_duplicados(bm, dist: float) -> int:
    tmp = bm.copy()
    try:
        antes = len(tmp.verts)
        bmesh.ops.remove_doubles(tmp, verts=list(tmp.verts), dist=dist)
        return antes - len(tmp.verts)
    finally:
        tmp.free()


def es_interior(f) -> bool:
    return all(len(e.link_faces) > 2 for e in f.edges)


def analizar(bm, dist=None) -> dict:
    d = diagonal(bm)
    if dist is None:
        dist = umbral_por_defecto(d)
    eps_area = epsilon_area(d)

    n_borde = n_alambre = n_multi = n_nocontig = 0
    for e in bm.edges:
        nf = len(e.link_faces)
        if nf == 0:
            n_alambre += 1
        elif nf == 1:
            n_borde += 1
        elif nf == 2:
            if not e.is_contiguous:
                n_nocontig += 1
        else:
            n_multi += 1

    n_tris = n_quads = n_ngons = n_area0 = n_interiores = n_equiv = 0
    area_total = 0.0
    for f in bm.faces:
        lados = len(f.verts)
        n_equiv += lados - 2
        if lados == 3:
            n_tris += 1
        elif lados == 4:
            n_quads += 1
        else:
            n_ngons += 1
        area = f.calc_area()
        area_total += area
        if area <= eps_area:
            n_area0 += 1
        if es_interior(f):
            n_interiores += 1

    n_sueltos = n_nomanifold = 0
    for v in bm.verts:
        if not v.link_faces:
            n_sueltos += 1
        elif not v.is_boundary and not v.is_manifold:
            n_nomanifold += 1

    _, caras_isla, _ = islas(bm)
    tam = sorted(caras_isla.values(), reverse=True)

    cerrada = bool(bm.faces) and not (n_borde or n_alambre or n_multi or n_sueltos)
    volumen = bm.calc_volume(signed=True) if cerrada else 0.0

    return {
        'verts': len(bm.verts),
        'aristas': len(bm.edges),
        'caras': len(bm.faces),
        'tris': n_tris,
        'quads': n_quads,
        'ngons': n_ngons,
        'triangulos': n_equiv,
        'duplicados': contar_duplicados(bm, dist),
        'islas': len(tam),
        'isla_mayor': tam[0] if tam else 0,
        'isla_menor': tam[-1] if tam else 0,
        'bordes': n_borde,
        'multiples': n_multi,
        'alambre': n_alambre,
        'no_contiguas': n_nocontig,
        'v_sueltos': n_sueltos,
        'v_nomanifold': n_nomanifold,
        'area_cero': n_area0,
        'interiores': n_interiores,
        'euler': len(bm.verts) - len(bm.edges) + len(bm.faces),
        'area': area_total,
        'volumen': volumen,
        'cerrada': cerrada,
        'invertida': cerrada and volumen < 0.0,
        'diagonal': d,
        'umbral': dist,
    }


def bucles_de_borde(bm) -> list:
    borde = [e for e in bm.edges if e.is_boundary]
    if not borde:
        return []

    vecinas = defaultdict(list)
    for e in borde:
        vecinas[e.verts[0]].append(e)
        vecinas[e.verts[1]].append(e)

    vistas = set()
    bucles = []
    for e0 in borde:
        if e0 in vistas:
            continue
        inicio = e0.verts[0]
        v, e = inicio, e0
        camino = []
        cerrado = False
        while True:
            vistas.add(e)
            camino.append(v)
            v = e.other_vert(v)
            if v is inicio:
                cerrado = True
                break
            siguientes = [x for x in vecinas[v] if x not in vistas]
            if len(siguientes) != 1:
                break
            e = siguientes[0]
        if cerrado and len(camino) >= 3:
            bucles.append(camino)
    return bucles


def cerrar_bucles(bm) -> list:
    nuevas = []
    for camino in bucles_de_borde(bm):
        try:
            nuevas.append(bm.faces.new(camino))
        except ValueError:
            pass
    return nuevas


def barrer_basura(bm) -> int:
    basura = [v for v in bm.verts if not v.link_faces]
    if basura:
        bmesh.ops.delete(bm, geom=basura, context='VERTS')
    return len(basura)


def reparar(bm, **kw) -> dict:
    d = diagonal(bm)
    dist = kw.get('dist')
    if dist is None:
        dist = umbral_por_defecto(d)
    eps_area = epsilon_area(d)
    limpiar = kw.get('borrar_sueltos', True)

    hecho = {
        'sueltos': 0, 'soldados': 0, 'degenerados': 0, 'area_cero': 0,
        'interiores': 0, 'parches': 0, 'islas': 0, 'volteada': False,
        'medio_interior': 0,
    }

    if limpiar:
        hecho['sueltos'] += barrer_basura(bm)

    if kw.get('soldar', True):
        antes = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=dist)
        hecho['soldados'] = antes - len(bm.verts)

    if kw.get('degenerados', True):
        antes = len(bm.faces)
        bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=list(bm.edges))
        hecho['degenerados'] = antes - len(bm.faces)
        malas = [f for f in bm.faces if f.calc_area() <= eps_area]
        if malas:
            bmesh.ops.delete(bm, geom=malas, context='FACES')
        hecho['area_cero'] = len(malas)

    if kw.get('interiores', True):
        malas = [f for f in bm.faces if es_interior(f)]
        if malas and len(malas) * 2 >= len(bm.faces):
            hecho['medio_interior'] = len(malas)
        elif malas:
            bmesh.ops.delete(bm, geom=malas, context='FACES')
            hecho['interiores'] = len(malas)

    if limpiar:
        hecho['sueltos'] += barrer_basura(bm)

    if kw.get('rellenar', True):
        lados = int(kw.get('lados_max', 0))
        nuevas = []
        for _ in range(3):
            bordes = [e for e in bm.edges if e.is_boundary]
            if not bordes:
                break
            res = bmesh.ops.holes_fill(bm, edges=bordes, sides=lados)
            creadas = [f for f in res.get('faces', ()) if f.is_valid]
            if not creadas:
                break
            nuevas.extend(creadas)
        nuevas.extend(cerrar_bucles(bm))
        nuevas = [f for f in nuevas if f.is_valid]
        hecho['parches'] = len(nuevas)
        if nuevas and kw.get('triangular_parches', True):
            grandes = [f for f in nuevas if len(f.verts) > 3]
            if grandes:
                bmesh.ops.triangulate(bm, faces=grandes)

    if kw.get('borrar_islas', False):
        pct = float(kw.get('islas_porcentaje', 1.0))
        padre, caras_isla, _ = islas(bm)
        if caras_isla:
            limite = max(caras_isla.values()) * pct / 100.0
            fuera = set(r for r, n in caras_isla.items() if n < limite)
            if fuera:
                basura = [v for v in bm.verts if padre[v.index] in fuera]
                if basura:
                    bmesh.ops.delete(bm, geom=basura, context='VERTS')
                hecho['islas'] = len(fuera)

    if limpiar:
        hecho['sueltos'] += barrer_basura(bm)

    if kw.get('normales', True):
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        if kw.get('voltear_invertida', True) and bm.faces:
            cerrada = not any(
                e.is_boundary or e.is_wire or len(e.link_faces) > 2
                for e in bm.edges)
            if cerrada and bm.calc_volume(signed=True) < 0.0:
                bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
                hecho['volteada'] = True

    return hecho

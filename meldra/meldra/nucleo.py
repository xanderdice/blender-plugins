from __future__ import annotations

from collections import defaultdict

import bmesh
from mathutils import Vector

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


def recortar(valores) -> float:
    n = len(valores)
    if n < 16:
        return max(valores) - min(valores)
    valores.sort()
    k = max(1, int(n * 0.01))
    return valores[n - 1 - k] - valores[k]


def escala(bm) -> float:
    if not bm.verts:
        return 0.0
    xs, ys, zs = [], [], []
    for v in bm.verts:
        c = v.co
        xs.append(c.x)
        ys.append(c.y)
        zs.append(c.z)
    dx, dy, dz = recortar(xs), recortar(ys), recortar(zs)
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def umbral(bm, modo: str = 'PRECISO', manual: float = 1e-4) -> float:
    if modo == 'MANUAL':
        return max(float(manual), 0.0)
    d = escala(bm)
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


def es_aleta(f) -> bool:
    multiple = suelta = 0
    for e in f.edges:
        nf = len(e.link_faces)
        if nf > 2:
            multiple += 1
        elif nf < 2:
            suelta += 1
    return multiple > 0 and suelta > 0


def es_hoja_suelta(f) -> bool:
    return all(e.is_boundary for e in f.edges)


def pelar_hojas(bm, tope: float = 0.5) -> int:
    total = 0
    for _ in range(8):
        if not bm.faces:
            break
        malas = [f for f in bm.faces if es_hoja_suelta(f)]
        if not malas or len(malas) > len(bm.faces) * tope:
            break
        bmesh.ops.delete(bm, geom=malas, context='FACES')
        total += len(malas)
    return total


def pelar_aletas(bm, tope: float = 0.5) -> int:
    total = 0
    for _ in range(8):
        if not bm.faces:
            break
        malas = [f for f in bm.faces if es_aleta(f)]
        if not malas or len(malas) > len(bm.faces) * tope:
            break
        bmesh.ops.delete(bm, geom=malas, context='FACES')
        total += len(malas)
    return total


def abanicos(v) -> list:
    caras = list(v.link_faces)
    if len(caras) < 2:
        return [caras] if caras else []
    indice = {f: i for i, f in enumerate(caras)}
    padre = list(range(len(caras)))

    def raiz(x: int) -> int:
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for e in v.link_edges:
        if len(e.link_faces) != 2:
            continue
        vecinas = [indice[f] for f in e.link_faces if f in indice]
        for otra in vecinas[1:]:
            a, b = raiz(vecinas[0]), raiz(otra)
            if a != b:
                padre[a] = b

    grupos = defaultdict(list)
    for i, f in enumerate(caras):
        grupos[raiz(i)].append(f)
    return list(grupos.values())


def divisible(v, grupos) -> bool:
    indice = {}
    for n, grupo in enumerate(grupos):
        for f in grupo:
            indice[f] = n
    for e in v.link_edges:
        if len(e.link_faces) < 2:
            continue
        cuenta = defaultdict(int)
        for f in e.link_faces:
            cuenta[indice.get(f, -1)] += 1
        if len(cuenta) > 1 and any(n < 2 for n in cuenta.values()):
            return False
    return True


def copiar_bucles(origen, destino) -> None:
    for a, b in zip(origen.loops, destino.loops):
        b.copy_from(a)


def dividir_abanico(bm, v, grupo) -> bool:
    nuevo = bm.verts.new(v.co, v)
    viejas = []
    for f in grupo:
        verts = [nuevo if x is v else x for x in f.verts]
        try:
            cara = bm.faces.new(verts, f)
        except ValueError:
            continue
        copiar_bucles(f, cara)
        viejas.append(f)

    if not viejas:
        bm.verts.remove(nuevo)
        return False
    for f in viejas:
        bm.faces.remove(f)
    return True


def resolver_multiples(bm, tope: float = 0.25) -> int:
    total = 0
    limite = max(1, int(len(bm.faces) * tope))
    for _ in range(8):
        malas = [e for e in bm.edges if len(e.link_faces) > 2]
        if not malas:
            break
        fuera = set()
        for e in malas:
            caras = sorted(e.link_faces, key=lambda f: f.calc_area())
            for f in caras[:len(caras) - 2]:
                fuera.add(f)
        fuera = [f for f in fuera if f.is_valid]
        if not fuera or total + len(fuera) > limite:
            break
        bmesh.ops.delete(bm, geom=fuera, context='FACES')
        total += len(fuera)
    return total


def separar_vertices(bm) -> int:
    total = 0
    for _ in range(6):
        sospechosos = [v for v in bm.verts
                       if len(v.link_faces) > 1 and not v.is_manifold]
        hechos = 0
        for v in sospechosos:
            if not v.is_valid:
                continue
            grupos = abanicos(v)
            if len(grupos) < 2 or not divisible(v, grupos):
                continue
            for grupo in grupos[1:]:
                if dividir_abanico(bm, v, grupo):
                    hechos += 1
        if not hechos:
            break
        barrer_alambre(bm)
        total += hechos
    return total


def males(bm) -> int:
    total = 0
    for e in bm.edges:
        nf = len(e.link_faces)
        if nf == 1 or nf > 2:
            total += 1
    return total


def conviene_quitar_interiores(bm, malas) -> bool:
    if not malas or len(malas) == len(bm.faces):
        return False
    if len(malas) * 2 < len(bm.faces):
        return True
    prueba = bm.copy()
    try:
        otras = [f for f in prueba.faces if es_interior(f)]
        if not otras or len(otras) == len(prueba.faces):
            return False
        antes = males(prueba)
        bmesh.ops.delete(prueba, geom=otras, context='FACES')
        if not prueba.faces:
            return False
        return males(prueba) < antes
    finally:
        prueba.free()


def analizar(bm, dist=None) -> dict:
    d = escala(bm)
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
        pisados = set()
        cerrado = False
        while True:
            vistas.add(e)
            camino.append(v)
            pisados.add(v)
            v = e.other_vert(v)
            if v is inicio:
                cerrado = True
                break
            siguientes = [x for x in vecinas[v] if x not in vistas]
            if not siguientes:
                break
            e = siguientes[0]
            if len(siguientes) > 1:
                frescas = [x for x in siguientes
                           if x.other_vert(v) not in pisados]
                if frescas:
                    e = frescas[0]
        if cerrado and len(camino) >= 3:
            bucles.append(camino)
    return bucles


def centro(camino):
    medio = Vector((0.0, 0.0, 0.0))
    for v in camino:
        medio += v.co
    return medio / float(len(camino))


def cerrar_en_abanico(bm, camino) -> list:
    if len(camino) < 3:
        return []
    medio = bm.verts.new(centro(camino))
    nuevas = []
    n = len(camino)
    for i in range(n):
        a, b = camino[i], camino[(i + 1) % n]
        if a is b:
            continue
        try:
            nuevas.append(bm.faces.new((medio, a, b)))
        except ValueError:
            pass
    if not nuevas:
        bm.verts.remove(medio)
    return nuevas


def triangular_en_abanico(bm, caras) -> int:
    total = 0
    viejas = []
    for f in caras:
        if not f.is_valid or len(f.verts) <= 3:
            continue
        creadas = cerrar_en_abanico(bm, list(f.verts))
        if not creadas:
            continue
        for cara in creadas:
            cara.material_index = f.material_index
            cara.smooth = f.smooth
        viejas.append(f)
        total += len(creadas)
    for f in viejas:
        bm.faces.remove(f)
    return total


def cerrar_bucles(bm, lados: int = 0) -> list:
    nuevas = []
    for camino in bucles_de_borde(bm):
        if lados and len(camino) > lados:
            continue
        if len(set(camino)) == len(camino):
            try:
                nuevas.append(bm.faces.new(camino))
            except ValueError:
                pass
        else:
            nuevas.extend(cerrar_en_abanico(bm, camino))
    return nuevas


def barrer_alambre(bm) -> int:
    hilos = [e for e in bm.edges if not e.link_faces]
    if hilos:
        bmesh.ops.delete(bm, geom=hilos, context='EDGES')
    return len(hilos)


def barrer_basura(bm) -> int:
    hilos = barrer_alambre(bm)
    basura = [v for v in bm.verts if not v.link_faces]
    if basura:
        bmesh.ops.delete(bm, geom=basura, context='VERTS')
    return hilos + len(basura)


def reparar(bm, **kw) -> dict:
    d = escala(bm)
    dist = kw.get('dist')
    if dist is None:
        dist = umbral_por_defecto(d)
    eps_area = epsilon_area(d)
    limpiar = kw.get('borrar_sueltos', True)

    hecho = {
        'sueltos': 0, 'soldados': 0, 'degenerados': 0, 'area_cero': 0,
        'interiores': 0, 'parches': 0, 'islas': 0, 'volteada': False,
        'medio_interior': 0, 'divididos': 0,
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
        quitadas = pelar_aletas(bm)
        malas = [f for f in bm.faces if es_interior(f)]
        if malas and not conviene_quitar_interiores(bm, malas):
            hecho['medio_interior'] = len(malas)
        elif malas:
            bmesh.ops.delete(bm, geom=malas, context='FACES')
            quitadas += len(malas) + pelar_aletas(bm)
        hecho['interiores'] = quitadas

    hecho['divididos'] = separar_vertices(bm)

    if kw.get('interiores', True):
        sobrantes = resolver_multiples(bm)
        if sobrantes:
            hecho['interiores'] += sobrantes + pelar_aletas(bm)
            hecho['divididos'] += separar_vertices(bm)

    if limpiar:
        hecho['sueltos'] += pelar_hojas(bm)
        hecho['sueltos'] += barrer_basura(bm)

    if kw.get('rellenar', True):
        lados = int(kw.get('lados_max', 0))
        nuevas = []
        for _ in range(8):
            bordes = [e for e in bm.edges if e.is_boundary]
            if not bordes:
                break
            res = bmesh.ops.holes_fill(bm, edges=bordes, sides=lados)
            creadas = [f for f in res.get('faces', ()) if f.is_valid]
            creadas.extend(cerrar_bucles(bm, lados))
            creadas = [f for f in creadas if f.is_valid]
            if not creadas:
                break
            nuevas.extend(creadas)
        nuevas = [f for f in nuevas if f.is_valid]
        hecho['parches'] = len(nuevas)
        if nuevas and kw.get('triangular_parches', True):
            grandes = [f for f in nuevas if len(f.verts) > 3]
            if grandes:
                triangular_en_abanico(bm, grandes)

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

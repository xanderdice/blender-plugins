# SPDX-License-Identifier: GPL-3.0-or-later
"""Nucleo de Atlara: reparto del espacio del atlas.

No importa bpy a proposito, asi se puede probar con python a secas.

El atlas se reparte en dos zonas:

  - una franja arriba con celdas cuadradas para los materiales planos
    (los que no tienen ninguna textura, solo colores), que ocupan unos
    pocos texeles cada uno;
  - el resto para los grupos de UV con textura, escalados todos por el
    mismo factor y colocados con un arbol binario de huecos, o por
    horizonte en el caso extremo de miles y miles de islas.

El factor de escala se busca por biseccion: el mayor que sigue entrando.
Asi el atlas queda lo mas lleno posible, que es lo mismo que decir que
cada isla se lleva todos los texeles que puede.
"""

from __future__ import annotations

import math

LIMITE_ARBOL = 4000  # por encima manda el horizonte, que es lineal


def siguiente_potencia(n: int) -> int:
    n = max(int(n), 1)
    return 1 << (n - 1).bit_length()


def resolucion_sugerida(texeles: float, minimo: int = 256,
                        maximo: int = 4096) -> int:
    """Lado del atlas que conserva mas o menos los texeles de origen.

    Redondea a la potencia de dos *mas cercana* en escala logaritmica, no
    a la de arriba. Subir de 2048 a 4096 cuadruplica la memoria en el
    motor para ganar un 9% de nitidez: casi nunca sale a cuenta. Y el
    automatico no pasa de 4096; para 8192 hay que pedirlo a mano.
    """
    if texeles <= 0.0:
        return minimo
    lado = math.sqrt(texeles)
    arriba = siguiente_potencia(int(lado))
    abajo = max(1, arriba // 2)
    elegido = arriba if lado > abajo * math.sqrt(2.0) else abajo
    return max(minimo, min(maximo, elegido))


def _por_arbol(tam, ancho, alto, rotar):
    """Arbol binario de huecos, con los huecos libres en lista plana.

    Es el mismo algoritmo de toda la vida (partir el hueco por el lado
    que deja el resto mas ancho), pero guardando solo las hojas libres en
    el orden en que las visitaria el recorrido en profundidad. Coloca
    exactamente igual que la version con nodos y va entre cinco y nueve
    veces mas rapido, porque deja de recorrer los nodos internos en cada
    insercion.
    """
    libres = [[0, 0, ancho, alto]]
    salida = [None] * len(tam)
    # De mayor a menor lado: los grandes primero, que son los que luego
    # no encuentran sitio.
    for i in sorted(range(len(tam)),
                    key=lambda k: (-max(tam[k]), -min(tam[k]))):
        w0, h0 = tam[i]
        giros = ((w0, h0, False), (h0, w0, True)) \
            if (rotar and w0 != h0) else ((w0, h0, False),)
        puesto = None
        for w, h, girado in giros:
            for j, hueco in enumerate(libres):
                hw, hh = hueco[2], hueco[3]
                if w > hw or h > hh:
                    continue
                x, y = hueco[0], hueco[1]
                if w == hw and h == hh:
                    del libres[j]
                elif hw - w > hh - h:
                    libres[j:j + 1] = ([[x, y + h, w, hh - h],
                                        [x + w, y, hw - w, hh]]
                                       if h < hh else
                                       [[x + w, y, hw - w, hh]])
                else:
                    libres[j:j + 1] = ([[x + w, y, hw - w, h],
                                        [x, y + h, hw, hh - h]]
                                       if w < hw else
                                       [[x, y + h, hw, hh - h]])
                puesto = (x, y, girado)
                break
            if puesto is not None:
                break
        if puesto is None:
            return None
        salida[i] = puesto
    return salida


def _altura(horizonte, i, w, ancho):
    """Y minima a la que apoya un rectangulo de ancho w desde el tramo i."""
    if horizonte[i][0] + w > ancho:
        return None
    y = horizonte[i][1]
    queda = w
    j = i
    while queda > 0:
        if j >= len(horizonte):
            return None
        if horizonte[j][1] > y:
            y = horizonte[j][1]
        queda -= horizonte[j][2]
        j += 1
    return y


def _asentar(horizonte, x, y, w, h):
    """Sube el horizonte por encima del rectangulo recien puesto."""
    salida = []
    for sx, sy, sw in horizonte:
        if sx + sw <= x or sx >= x + w:
            salida.append((sx, sy, sw))
            continue
        if sx < x:
            salida.append((sx, sy, x - sx))
        if sx + sw > x + w:
            salida.append((x + w, sy, sx + sw - (x + w)))
    salida.append((x, y + h, w))
    salida.sort()
    fusion = []
    for tramo in salida:
        if fusion and fusion[-1][1] == tramo[1] \
                and fusion[-1][0] + fusion[-1][2] == tramo[0]:
            previo = fusion[-1]
            fusion[-1] = (previo[0], previo[1], previo[2] + tramo[2])
        else:
            fusion.append(tramo)
    return fusion


def _por_horizonte(tam, ancho, alto, rotar):
    """Empaquetado por horizonte (skyline) con el mejor apoyo.

    Va colocando cada rectangulo donde su borde superior quede lo mas
    bajo posible. Es casi tan bueno como el arbol y no se dispara con
    miles de islas, que es cuando el arbol se vuelve inviable.
    """
    horizonte = [(0, 0, ancho)]
    salida = [None] * len(tam)
    for i in sorted(range(len(tam)),
                    key=lambda k: (-max(tam[k]), -min(tam[k]))):
        w0, h0 = tam[i]
        giros = (False, True) if (rotar and w0 != h0) else (False,)
        mejor = None
        for girado in giros:
            w, h = (h0, w0) if girado else (w0, h0)
            if w > ancho or h > alto:
                continue
            for tramo in range(len(horizonte)):
                # Apoyar aqui nunca puede quedar por debajo del propio
                # tramo, asi que si ni con eso mejora al favorito, no hace
                # falta ni mirar cuanto tapa. Esta poda de una linea se
                # lleva por delante casi todas las llamadas a _altura.
                base = horizonte[tramo][1]
                if base + h > alto:
                    continue
                tope = (base + h, horizonte[tramo][0])
                if mejor is not None and tope >= mejor[0]:
                    continue
                y = _altura(horizonte, tramo, w, ancho)
                if y is None or y + h > alto:
                    continue
                clave = (y + h, horizonte[tramo][0])
                if mejor is None or clave < mejor[0]:
                    mejor = (clave, horizonte[tramo][0], y, w, h, girado)
        if mejor is None:
            return None
        _clave, x, y, w, h, girado = mejor
        horizonte = _asentar(horizonte, x, y, w, h)
        salida[i] = (x, y, girado)
    return salida


def empaquetar(tam, ancho, alto, rotar=True):
    """tam: lista de (ancho, alto) en texeles. Devuelve [(x, y, girado)].

    Antes de intentarlo descarta lo imposible por lado o por area: eso se
    lleva por delante la mitad cara de la biseccion, que es justo la que
    siempre acaba fallando.
    """
    if not tam:
        return []
    if ancho <= 0 or alto <= 0:
        return None
    total = 0
    for w, h in tam:
        if w > ancho or h > alto:
            if not rotar or h > ancho or w > alto:
                return None
        total += w * h
    if total > ancho * alto:
        return None
    metodo = _por_arbol if len(tam) <= LIMITE_ARBOL else _por_horizonte
    return metodo(tam, ancho, alto, rotar)


def ajustar(rects, ancho, alto, margen=4, rotar=True, pasos=0):
    """Busca la mayor escala con la que `rects` entra en el rectangulo.

    rects: lista de (ancho, alto) en unidades cualesquiera.
    Devuelve (escala, tam, colocaciones) o None si no entra ni al minimo.
    Cada rectangulo reserva `margen` texeles por lado; el contenido va
    dentro, en (x + margen, y + margen).
    """
    if not rects:
        return 0.0, [], []
    if ancho <= 0 or alto <= 0:
        return None
    if pasos <= 0:
        # Con muchas islas cada intento cuesta, y afinar la escala mas
        # alla de una milesima no se ve en la textura.
        pasos = 18 if len(rects) <= LIMITE_ARBOL else 12

    def probar(escala):
        tam = []
        for w, h in rects:
            tam.append((max(1, int(w * escala + 0.5)) + 2 * margen,
                        max(1, int(h * escala + 0.5)) + 2 * margen))
        return tam, empaquetar(tam, ancho, alto, rotar)

    area = sum(max(w, 1e-9) * max(h, 1e-9) for w, h in rects)
    alto_ = float(ancho * alto) / area if area > 0.0 else 1.0
    bajo, alto_escala = 0.0, math.sqrt(alto_) * 1.05

    tam, col = probar(0.0)
    if col is None:
        return None
    mejor = (0.0, tam, col)

    for _ in range(pasos):
        medio = (bajo + alto_escala) / 2.0
        tam, col = probar(medio)
        if col is None:
            alto_escala = medio
        else:
            bajo = medio
            mejor = (medio, tam, col)
    return mejor


def franja_planos(cantidad, celda, ancho, alto):
    """Celdas cuadradas para los materiales planos, en la parte de arriba.

    Devuelve (alto_de_la_franja, [(x, y, lado)]). Encoge la celda si con
    el tamano pedido no cabrian.
    """
    if cantidad <= 0:
        return 0, []
    celda = max(2, int(celda))
    while True:
        columnas = max(1, ancho // celda)
        filas = int(math.ceil(cantidad / float(columnas)))
        franja = filas * celda
        if franja <= alto // 2 or celda <= 2:
            break
        # Nunca por debajo de 2: con lado 1 no queda sitio para meter la
        # UV dentro y se iria a la celda del vecino.
        celda = max(2, celda // 2)

    columnas = max(1, ancho // celda)
    filas = int(math.ceil(cantidad / float(columnas)))
    franja = min(filas * celda, alto)
    base = alto - franja
    celdas = []
    for i in range(cantidad):
        celdas.append((
            (i % columnas) * celda,
            base + (i // columnas) * celda,
            celda,
        ))
    return franja, celdas


def repartir(rects, planos, ancho, alto, margen=4, celda=16, rotar=True):
    """Reparte el atlas entero.

    rects  : [(ancho, alto)] de los grupos con textura, unidades libres.
    planos : cuantos materiales planos hay.
    Devuelve dict con 'celdas', 'colocaciones', 'tam' y 'escala', o None.
    """
    franja, celdas = franja_planos(planos, celda, ancho, alto)
    libre = alto - franja
    if rects and libre < 4:
        return None
    hecho = ajustar(rects, ancho, max(libre, 1), margen, rotar) if rects \
        else (0.0, [], [])
    if hecho is None:
        return None
    escala, tam, colocaciones = hecho
    return {
        'escala': escala,
        'tam': tam,
        'colocaciones': colocaciones,
        'celdas': celdas,
        'franja': franja,
        'ocupacion': ocupacion(tam, celdas, ancho, alto),
    }


def ocupacion(tam, celdas, ancho, alto) -> float:
    """Que parte del atlas se llena de verdad, celdas de color incluidas."""
    if ancho <= 0 or alto <= 0:
        return 0.0
    usado = sum(w * h for w, h in tam)
    usado += sum(lado * lado for _x, _y, lado in celdas)
    return min(1.0, usado / float(ancho * alto))

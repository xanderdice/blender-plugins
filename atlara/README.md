# Atlara

Add-on de Blender que coge todos los materiales de todos los objetos que
tengas seleccionados y los funde en **un solo atlas y un solo material**,
sin unir los objetos.

Está pensado para assets de videojuego: menos materiales significa menos
*drawcalls*, y menos drawcalls significa más FPS. Un escenario con veinte
props y sesenta materiales pasa a tener un material.

*Atlara* viene de **atlas**, que es exactamente lo que fabrica.

## Qué resuelve

| Lo que tienes | Lo que sale |
| --- | --- |
| Un objeto con 8 materiales | El mismo objeto con 1 material, con los 8 colores y texturas metidos en un atlas |
| 12 objetos con 1 material cada uno | Los 12 objetos, separados, compartiendo 1 material |
| Difuso, normal, metálico y rugosidad en archivos sueltos | Color base + un mapa ORM que lleva oclusión, rugosidad y metálico en R, G y B |
| Objetos desperdigados por la escena | Cada uno con el pivote en su centro y en 0,0,0 |
| UV repartidas a ojo, con huecos | El atlas empaquetado por la forma real de cada isla, hasta un 64% más de texeles aprovechados |

## Instalación

Necesita **Blender 4.2 o superior**, incluido 5.x.

1. Genera el zip con doble clic en `empaquetar.bat`, o desde la consola:

```bash
empaquetar.bat
```

2. En Blender: `Edit > Preferences > Add-ons`, botón `▾` arriba a la
   derecha, **Install from Disk…**, y eliges `dist\atlara-1.0.0.zip`.
   También vale arrastrar el zip a la ventana de Blender.

3. El panel sale en la **Vista 3D > barra lateral (tecla `N`) > pestaña
   "Atlara"**.

## Cómo se usa

1. Selecciona los objetos. Si en la selección se cuelan luces, cámaras o
   *empties*, no pasa nada: **se ignoran solos**. Las luces las pondrás
   luego en el motor.
2. Pulsa **Analizar selección**. Te dice cuántos objetos, materiales y
   texturas hay, y cuántos drawcalls te vas a ahorrar.
3. Elige el modo:
   - **Un atlas para todo**: un único material compartido por toda la
     selección. Es lo que menos drawcalls deja.
   - **Un atlas por objeto**: cada objeto con su propio material y su
     propio atlas.
4. Pulsa **Fundir en un atlas**.

Mientras trabaja verás el avance en la barra de estado, en el propio panel
y en el cursor: *qué canal está horneando, de qué objeto, y el porcentaje*.
**Se cancela con `Esc`.**

Al terminar cada objeto tiene una sola ranura de material, el atlas como
primer canal UV, el pivote centrado y está en 0,0,0. Los objetos **no se
unen**: siguen siendo objetos separados.

### Si lo cancelas

No deja nada a medias. El proceso está ordenado de forma que hasta el
último momento solo ha tocado cosas que se pueden quitar: capas UV
*nuevas* y las imágenes del atlas. Al pulsar `Esc` se borran las dos, se
devuelve el motor de render a como estaba, y la escena se queda
**exactamente igual que antes de empezar**. Ni siquiera hace falta
`Ctrl+Z`.

Por eso las transformaciones, el pivote y el traslado a 0,0,0 se aplican
al final del todo y no al principio, que sería lo natural.

En modo **un atlas por objeto** puede haber objetos ya terminados cuando
cancelas. Ésos no se pueden deshacer a mano, porque al rematarlos ya se
borraron sus mapas UV viejos: para ellos Atlara deja un punto de retorno
en el historial nada más empezar y vuelve a él. El resultado es el mismo
—la escena queda como estaba— pero por otro camino, y te lo dice en el
aviso.

El horneado en marcha no se interrumpe: el `Esc` se atiende **entre**
pasos. Si estás horneando oclusión con muchas muestras, la cancelación
puede tardar lo que tarde ese paso.

> Se amontonan en el visor, porque todos están en el origen. Es lo que
> quieres para exportarlos como assets: cada uno entra centrado en el
> motor. Si prefieres verlos en su sitio, desmarca *Llevar a 0,0,0*.

## Lo que hace por dentro

El orden es este, y importa:

1. Descarta todo lo que no sea malla.
2. Crea una capa UV nueva llamada `Atlas`, copiada de la original.
3. Lee los materiales y los separa en dos montones: los que tienen
   textura y los que son **solo un color**.
4. Reparte el atlas y mueve las UV a su parcela.
5. Hornea cada canal de cada objeto sobre las mismas imágenes.
6. Pinta las celdas de los materiales planos con su color exacto.
7. Mezcla metálico, rugosidad y oclusión en un único mapa.
8. Crea un material y se lo cuelga a todos los objetos.
9. Y ahora, no antes, aplica rotación y escala, centra el pivote y lleva
   cada objeto a 0,0,0.

### El truco del horneado

Para cada canal (color base, metálico, rugosidad, alfa, emisión) se hace
una copia temporal del material, se coge lo que alimenta a esa entrada
del BSDF y se enchufa a un nodo *Emission* conectado a la salida.
Horneando **EMIT** sale el valor crudo, sin luces ni sombras, igual de
bien para un color plano que para una textura o para un nodo procedural
de ruido.

Mientras tanto, las texturas de origen se anclan a la UV vieja con nodos
*UV Map*, para que la malla se lea con el reparto de antes y se escriba
con el del atlas. Es lo que permite hacerlo todo en una sola pasada.

Las normales se hornean con el pase `NORMAL` en espacio tangente, así que
los mapas de normales originales se conservan.

### Materiales de un solo color

Un material sin ninguna textura no necesita ni un centímetro de atlas:
solo un cuadradito de 16 px con su color. Atlara los detecta, les reserva
una celda en una franja aparte y les escribe el color **exacto** con
numpy, sin pasar por el horneado.

Esto es lo que hace que un asset con veinte materiales de colores planos
quepa en un atlas de 256 px sin perder nada. Y también es lo que responde
a la pregunta de siempre: *un objeto con más de un material queda como si
siguiera teniendo más de uno, pero es uno solo*.

Si enciendes la oclusión ambiental, los materiales planos dejan de
tratarse como planos: la oclusión necesita sitio de verdad en el atlas
para poder pintarse.

### Canales en un solo archivo

Tres texturas en blanco y negro ocupan tres veces lo que una en color.
Atlara las mete en los canales de una sola imagen:

| Modo | R | G | B | A |
| --- | --- | --- | --- | --- |
| **ORM** (glTF, Unreal) | oclusión | rugosidad | metálico | — |
| **Mask Map** (Unity) | metálico | oclusión | libre | suavidad |
| **Mapas sueltos** | un archivo por canal | | | |

El alfa, si lo enciendes, viaja en el canal A del color base.

Con **Detectar canales** puesto solo se hornea lo que los materiales usan
de verdad. Si ninguno tiene mapa de normales, no se genera el archivo de
normales. Menos texturas, menos espera y menos memoria.

Por eso vienen encendidos también emisión y alfa: con la detección puesta
no cuestan nada si nadie los usa, y si alguien los usa habrías perdido
esa información sin enterarte.

### Las UV

Aquí es donde se gana o se pierde la calidad. El atlas puede tener 2048
píxeles de lado, pero si la mitad se queda vacía entre isla e isla, es
como si tuviera 1448.

Por eso el add-on no mide *cuánto atlas ocupan las cajas* sino los
**texeles útiles**: qué porcentaje del atlas queda cubierto por triángulos
UV de verdad. Es el número que sale en el informe y en el resumen, y es el
que se corresponde con la nitidez que vas a ver.

**Empaquetado**:

- *Automático* — reparte de las dos maneras de abajo y se queda con la que
  deja más texeles útiles. Es lo que trae de fábrica, porque **ninguna de
  las dos gana siempre**. Midiendo texeles útiles sobre escenas reales,
  con el mismo margen exacto en los dos lados:

  | escena | por caja | por forma | automático |
  | --- | --- | --- | --- |
  | 3 Suzannes, 1 material | **52,3%** | 52,5% | 52,5% |
  | 3 Suzannes, 3 materiales | 44,6% | **55,4%** | 55,4% |
  | 5 Suzannes subdivididas | 27,5% | **45,0%** | 45,0% |
  | 12 cubos mezclados | 36,1% | **47,7%** | 47,7% |

  Un +64% de texeles útiles, como en la tercera fila, es un **+28% de
  resolución efectiva**: el mismo atlas, la misma memoria en el motor, y
  la textura se ve como si fuera de una talla más.

- *Por la forma real* — delega en el empaquetador de Blender, que sigue el
  contorno de cada isla y puede meter una en el hueco de otra.
- *Por caja envolvente* — el empaquetador propio de Atlara: árbol binario
  de huecos, o por *horizonte* cuando hay miles de islas, con la escala
  buscada por bisección. Instantáneo y siempre igual, pero desperdicia lo
  que sobra dentro de la caja de cada isla.

**Lo que cuesta**: el de cajas tarda medio segundo largo. El de forma es
una sola llamada al packer de Blender y **puede tirarse quince segundos**
sin dar señales, así que el automático paga ese tiempo. Si tienes prisa,
pon *Por caja envolvente*. Y el **contorno** tiene tres niveles: *caja* es
instantáneo y a veces ya se lleva toda la ganancia, *envoltura convexa* y
*contorno exacto* afinan más y cuestan.

| escena | caja | AABB | convexo | exacto |
| --- | --- | --- | --- | --- |
| 3 Suzannes, 1 material | 52,3% · 0,4 s | 46,7% · 0,4 s | 49,7% · 27 s | 52,5% · 17 s |
| 3 Suzannes, 3 materiales | 44,6% · 0,4 s | 49,8% · 0,4 s | 52,6% · 13 s | 55,4% · 14 s |
| 5 Suzannes subdivididas | 27,5% · 0,8 s | 45,0% · 0,7 s | 45,0% · 1,5 s | 45,0% · 1,6 s |
| 12 cubos mezclados | 36,1% · 0,5 s | 35,5% · 0,5 s | 39,5% · 5,2 s | 47,7% · 0,9 s |

Con *por caja* siguen valiendo sus dos mandos: **reparto** (automático,
por material o por isla) y **enderezar trozos**, que busca el rectángulo
envolvente mínimo girando la isla —una isla en diagonal puede estar
malgastando el triple de atlas del que necesita—.

**Densidad**:

- *Uniforme* — los mismos texeles por metro en toda la selección. Es lo
  que se espera de un asset de videojuego: una caja pequeña no se lleva
  la misma cantidad de atlas que una casa.
- *Como el original* — respeta los texeles que tenía cada textura de
  origen. Si vienes de texturas 4K y no quieres perder ese detalle.
- *Proporción UV* — reparte según el tamaño que ya tenían las UV.

**Margen**: texeles de relleno alrededor de cada trozo. Súbelo si al
alejarte ves colores del vecino colándose (es cosa de los mipmaps). Los
dos empaquetadores dejan **exactamente** los texeles que les pides, cosa
que hay que forzar: de las tres formas que tiene Blender de pedir margen,
dos lo escalan por un factor que no controlas y sólo `FRACTION` da lo
pedido. Y si te pasas con el margen, el packer no protesta: manda las UV
fuera del cuadrado sin decir nada, así que Atlara lo acota según cuántas
islas haya.

### Los canales UV

Atlara **nunca escribe encima de tus UV**: el atlas va siempre a un canal
UV nuevo, y de fábrica el original se conserva detrás.

Lo importante es el **orden**. Los exportadores —glTF y FBX— mandan al
canal 0 la *primera* capa de la lista, no la activa ni la marcada para
render. Está medido exportando y reimportando: con la capa del atlas en
segundo lugar, `TEXCOORD_0` se lleva las UV viejas y el atlas se ve mal en
el motor. Así que Atlara reordena las capas para dejar el atlas el
primero, y el material generado lleva un nodo *UV Map* que dice
explícitamente de qué capa lee, para que no dependa de cuál esté activa.

| Modo | Resultado |
| --- | --- |
| *Atlas primero, y guardar las viejas* | `UV0 = Atlas`, `UV1 = UVMap` original. Las UV de partida siguen ahí para mapas de detalle, decals o lo que necesites |
| *Solo el atlas* | Un único canal `UVMap`. Lo más ligero en memoria de vértice |

Si tus objetos ya traían un canal de lightmap, usa el primer modo: el
segundo lo borraría, y te avisa cuando eso va a pasar.

## Ajustes

### Atlas

| Ajuste | Para qué |
| --- | --- |
| Resolución | Lado del atlas. *Automática* la calcula para conservar más o menos los texeles de origen, redondeando a la potencia de dos más cercana y sin pasar de 4096 |
| Margen | Relleno alrededor de cada trozo, en texeles. *Automático* lo saca del tamaño de parcela (resolución ÷ √trozos ÷ 32, entre 2 y 32): con margen fijo, mil islas en un atlas de 2048 se comerían casi la mitad del atlas en puro relleno |
| Empaquetado | Automático (prueba los dos), por la forma real (Blender) o por caja envolvente (Atlara) |
| Contorno | Con el de forma: exacto, envoltura convexa o caja |
| Reparto | Con el de cajas: automático, por material o por isla |
| Densidad | Cómo se reparte el espacio |
| Girar trozos | Permite girar 90° para que quepa más |
| Enderezar trozos | Con el de cajas: busca el rectángulo envolvente mínimo |
| Celda de color | Lado en texeles de la casilla de cada material sin texturas |

### Canales y texturas

| Ajuste | Para qué |
| --- | --- |
| Canales | ORM, Mask Map o mapas sueltos |
| Detectar canales | Hornea solo lo que se usa |
| Normal / Metálico / Rugosidad / Emisión / Alfa | Qué canales quieres |
| Oclusión | Calcula la oclusión ambiental de la geometría. Es lo que más tarda |
| Verde invertido (DirectX) | Unreal y 3ds Max esperan el verde al revés que Blender, Unity o glTF |
| Nombre | Prefijo del material y de las texturas |
| Texturas | Empaquetadas dentro del .blend o escritas en una carpeta |

### Objetos

| Ajuste | Para qué |
| --- | --- |
| Aplicar rotación y escala | Deja la escala en 1. Hace falta para que la densidad de texel salga igual en todos |
| Pivote | Centro de la caja, centro de masa, a los pies, o no tocar |
| Llevar a 0,0,0 | Coloca cada objeto en el origen del mundo |
| Canales UV | Atlas como canal 0 conservando los viejos, o solo el atlas |
| Reproyectar UVs | Vuelve a desplegar con Smart UV Project antes de atlasear |

El botón **Centrar y llevar a cero** hace solo la parte de pivotes, sin
tocar materiales.

## Cosas que conviene saber

- **Hace falta Cycles.** El horneado es de Cycles; el add-on cambia el
  motor mientras trabaja y lo deja como estaba al terminar.
- **Las UV que repetían textura** (fuera del cuadrado 0–1) se hornean con
  la repetición dentro de su parcela. El resultado se ve igual, pero con
  menos resolución: una textura que se repetía 8 veces ahora ocupa 8
  veces menos por baldosa. Es inevitable en cualquier atlas.
- **Mipmaps.** Al alejarse mucho, los niveles bajos de mipmap acaban
  mezclando parcelas vecinas. Es propio de los atlas. Sube el margen o
  limita los mipmaps en el motor si te molesta.
- **Malla compartida.** Si dos objetos comparten la misma malla, se le
  hace una copia a cada uno: cada uno necesita sus propias UV.
- **Es destructivo.** Sustituye materiales y UV. Un solo `Ctrl+Z` lo
  deshace entero, pero guarda antes de una tanda grande.
- **El horneado bloquea Blender** mientras dura cada paso. Entre paso y
  paso la interfaz respira y atiende al `Esc`.
- **Objetos con padre**: no se les aplican las transformaciones, y se
  avisa. Desemparéntalos antes si quieres la densidad uniforme exacta.

## Pruebas

```bash
blender --background --factory-startup --python pruebas/prueba.py
```

Monta una escena como las que salen de un importador (un objeto con dos
materiales, otro con uno plano y una luz en medio de la selección) y
comprueba las 227 cosas que importan: que queda un solo material, que los
objetos siguen separados y en 0,0,0, que las UV caben en el cuadrado, y
—lo más importante— que **al muestrear el atlas en la UV de cada cara sale
el color que tenía esa cara antes**. También cubre emisión, alfa, reparto
por isla y automático, oclusión, guardado en disco, atlasear dos veces
seguidas, que el empaquetador no solape nunca dos parcelas, y que cancelar
a media faena devuelve las UV originales intactas —también cuando ya
había atlas terminados—. También cubre los shaders raros: un Principled
metido en un grupo de nodos, un Mix Shader según su Fac, y un material
que no se entiende.

## Empaquetar y publicar

```bash
empaquetar.bat
```

Pasa las pruebas, genera `dist\atlara-<versión>.zip`, valida el
manifiesto con el propio Blender y te dice dónde subirlo. Si Blender no
está instalado, se salta las pruebas y la validación, pero genera el zip
igual.

Para subir de versión: cambia `version` en
`atlara/blender_manifest.toml` y vuelve a lanzar el batch. El `id` no
cambia, así que Blender reemplaza la instalación anterior en vez de
duplicarla.

También funciona sin Windows:

```bash
python empaquetar.py
```

## Créditos

**xander.dice**

- Instagram: [@xander.dice](https://www.instagram.com/xander.dice)
- YouTube: [@xanderdice](https://www.youtube.com/@xanderdice)
- Facebook: [djxanderdice](https://www.facebook.com/djxanderdice)

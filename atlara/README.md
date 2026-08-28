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
| El mismo material repetido en 12 objetos | Una sola copia en el atlas: 3× de resolución efectiva |

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

### Reutilizar lo que se repite

Si cinco objetos usan el mismo material y sus UV leen el mismo trozo de
esa textura, hornear cinco copias del mismo dibujo en cinco sitios del
atlas es tirar el atlas a la basura. Atlara lo detecta y les da **una
sola parcela entre todos**.

Lo que se gana no es espacio: es **nitidez**. El sitio que sobra se lo
reparten los demás, así que el factor de escala de la bisección sube para
todo el mundo. Medido, atlas de 512, objetos que comparten un material:

| caso | texeles por objeto | lado equivalente |
| --- | --- | --- |
| 5 objetos, sin reutilizar | 21.907 | 148 |
| 5 objetos, **reutilizando** | 86.400 | **294** |
| 12 objetos, sin reutilizar | 9.322 | 97 |
| 12 objetos, **reutilizando** | 86.400 | **294** |

Con doce objetos son **3 veces más resolución efectiva**, 9,3 veces más
texeles. Y fíjate en que la cifra ya no baja al añadir objetos: el
contenido está una vez, así que da igual cuántos lo usen.

**La vara de medir tuvo que cambiar para que esto funcionara.** El
porcentaje de "texeles útiles" sumaba el área de cada parcela sin
descontar las repetidas, así que **cinco copias del mismo dibujo puntuaban
cinco veces** y el reparto automático elegía el que duplicaba. Ahora cada
contenido se cuenta una sola vez: la firma de un pedazo es su material más
el rectángulo de textura que lee, y se calcula antes de mover nada, porque
después de empaquetar ya no se sabe quién era copia de quién.

**Cuándo se fusionan dos parcelas.** Sólo si no sale más caro: la caja
que envuelve a las dos no puede ocupar más que las dos por separado. Dos
objetos con las UV encima se funden (la unión es la misma caja, se ahorra
una entera); dos que usan esquinas opuestas de la textura no, porque la
unión sería un caserón medio vacío.

**Cuándo NO se comparte, pase lo que pase.** Compartir parcela sólo vale
si los dos hornean lo mismo, y hay materiales que no. Atlara mira el
árbol de nodos —entrando en los grupos— y se echa atrás si encuentra algo
que dependa del objeto y no sólo de la UV:

> Object Info · Geometry (posición, normal, pointiness, random) ·
> atributos y colores de vértice · Particle/Hair Info · Tangent · Bevel ·
> Ambient Occlusion · Wireframe · Layer Weight · Fresnel · Camera Data ·
> y las salidas de Texture Coordinate que no sean UV

Dos objetos con un material que multiplica por *Object Info > Random* se
ven distintos aunque compartan UV: ahí cada uno se queda con su parcela.
Lo mismo con la oclusión ambiental encendida, que es geométrica por
definición.

Hay una prueba que hornea un degradado —donde el color de cada texel
*dice* su coordenada UV— sobre cinco objetos que comparten parcela, y
comprueba cara por cara que cada una sigue leyendo exactamente su color.
Y otra que lo comprueba **con los ajustes tal y como vienen de fábrica**,
sin tocar nada, porque la primera versión de esto funcionaba sólo si
forzabas el empaquetador a mano.

**UV apiladas.** Si has apilado islas a propósito —el brazo izquierdo y el
derecho sobre el mismo sitio de la textura, que es una optimización de
toda la vida— eso es un caso particular de contenido repetido, y se
respeta. Antes se separaban y cada mitad se llevaba una copia: medido, 4,1
veces menos texeles por cara para pintar exactamente lo mismo.

> Si fuerzas el empaquetador **por la forma real**, no hay reutilización:
> el packer de Blender ve islas geométricas independientes y las separa,
> sin saber que hornean lo mismo. En *Automático* eso ya no importa,
> porque compara las dos opciones contando contenido único y se queda con
> la que de verdad da más texeles.

> **Sobre los trim sheets.** Esto no es un trim sheet, y no lo puede ser.
> Un trim sheet es una técnica de *autoría*: modelas la geometría contra
> una tira de molduras que diseñaste antes. No hay nada en una malla ya
> hecha de la que se pueda deducir cuál de sus franjas era una moldura
> reutilizable. Lo que sí es automatizable —y es de donde sale la
> ganancia de arriba— es detectar contenido repetido y no guardarlo dos
> veces.

### El formato de las texturas

Los mapas del atlas se escriben en **PNG** o en **WebP**. WebP pesa
bastante menos, y hay un detalle que lo hace seguro: en Blender,
**calidad 100 es sin pérdida**, y aun así ocupa un 38% menos que el PNG
equivalente. Medido, ida y vuelta, error máximo `0.0000` por canal.

Por eso Atlara reparte así:

| mapa | cómo se guarda | por qué |
| --- | --- | --- |
| Color base, Emisión | WebP con la calidad que pidas (90 de fábrica) | Son colores; el ojo perdona |
| Normal, ORM, Mask Map | WebP **siempre sin pérdida** | Comprimir esto con pérdida mezcla entre sí canales que no tienen nada que ver: la rugosidad se contamina con el metálico, y el normal se llena de artefactos en el sombreado |

Hay una trampa de Blender aquí que conviene saber: **`pack()` ignora el
formato y empaqueta siempre un PNG**, y encima te cambia el `file_format`
a `PNG` por la espalda. Se ve mirando los bytes empaquetados: la cabecera
sigue siendo PNG. Para meter WebP de verdad dentro del `.blend` hay que
escribir un fichero temporal y empaquetar ése, que es lo que hace Atlara
—y luego lo borra—. Hay una prueba que lee la firma de los bytes
empaquetados para que esto no se rompa sin que nadie se entere.

En una escena de prueba, escribir en carpeta pasó de **11,4 KB a 2,2 KB**
(un 80% menos), y empaquetado dentro del `.blend`, de **238,9 KB a
106,6 KB** (un 55% menos), dejando el archivo en 222,5 KB en vez de
335,7 KB.

#### Y en el GLB

Aquí hay que saber una cosa: **para el tamaño del GLB manda el
exportador de glTF, no Atlara**. Medido con un atlas de 1024 y tres
mapas:

| atlas de Atlara | exportador glTF | GLB | mapas de datos |
| --- | --- | --- | --- |
| PNG | AUTO | 390,8 KB | sin pérdida |
| PNG | WEBP | **167,6 KB** | con pérdida, también el normal |
| WebP | AUTO | 210,0 KB | **sin pérdida** |

La combinación que recomiendo para un asset serio es la tercera:
**Atlara en WebP y el exportador en AUTO**. El GLB baja casi a la mitad
y los mapas de normales y ORM llegan intactos, porque el exportador se
limita a copiar los bytes que ya escribió Atlara en vez de recomprimirlo
todo a calidad 75.

**Dos avisos importantes:**

- El WebP en glTF entra por la extensión `EXT_texture_webp`, y Blender la
  declara en **`extensionsRequired`**, no en `extensionsUsed`. Eso
  significa que un visor que no la soporte **rechaza el archivo entero**,
  no es que se vea peor. Si el GLB tiene que abrirse en cualquier sitio,
  quédate en PNG.
- **En un motor AAA esto no te da FPS.** PNG, JPEG y WebP son formatos de
  *disco*: se descomprimen en CPU al cargar y suben a la GPU sin
  comprimir. Una textura de 4096 con mipmaps ocupa unos 90 MB en memoria
  venga del fichero que venga. Unreal y Unity además recomprimen a
  BC7/BC5/ASTC al importar. Así que el formato de origen sólo cambia lo
  que pesa en disco y lo que tardas en descargarlo. Donde sí se nota de
  verdad es en un GLB servido por web (three.js, model-viewer, Babylon).

Quién soporta `EXT_texture_webp`: **sí** three.js, `<model-viewer>`,
babylon.js (5.0+), Godot (4.1+, sólo importar) y **PlayCanvas**. **No de
fábrica** Unity (glTFast lo tiene como incidencia abierta) ni Unreal
(hace falta un plugin de terceros).

En PlayCanvas hay que mirar las dos capas por separado: el motor lo
resuelve en `texture-source.js`, que lee `EXT_texture_webp` y da
prioridad a `KHR_texture_basisu`; y el **Editor** no lo importaba —el
modelo entraba blanco— hasta que lo arreglaron el **22 de abril de
2025**. Si el Editor os deja los materiales en blanco, es que está sin
actualizar.

> **Para PlayCanvas, WebP no es lo mejor que puedes hacer.** Fíjate en
> que el motor prefiere `KHR_texture_basisu` *antes* que WebP. KTX2 con
> Basis llega comprimido hasta la VRAM (se transcodifica a BC/ASTC/ETC2),
> así que ahí sí bajas memoria de vídeo 4–8×, no sólo descarga — que es
> justo lo que WebP **no** hace. Blender no exporta KTX2: su
> `export_image_format` sólo ofrece `AUTO`, `JPEG`, `WEBP` y `NONE`. Se
> hace después sobre el GLB, con `gltf-transform` o `gltfpack`.

#### Y en el FBX

El FBX embebe los bytes tal cual, sin recomprimir: el mismo asset pasa de
**163,6 KB a 113,0 KB** con WebP. Pero **ni Unreal ni Unity aceptan
`.webp` como textura de origen**, así que lo más probable no es un error
claro sino una textura que no carga. **Para FBX, quédate en PNG.**

Y un aviso que no tiene que ver con el formato: **el exportador FBX de
Blender se deja el mapa ORM por el camino**. Medido: el atlas sale con
tres mapas y al FBX sólo llegan dos. Sólo mapea las ranuras clásicas del
Principled (color base y normal), y el ORM, que entra por un nodo
*Separate Color*, desaparece. Si exportas a FBX, escribe las texturas en
una carpeta y engánchalas a mano en el motor, que además es como se
trabaja normalmente en un pipeline serio.

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
| Formato | PNG (lo entiende todo) o WebP (pesa mucho menos) |
| Calidad | Sólo el color base y la emisión; el normal y el ORM van siempre sin pérdida |

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
comprueba las 263 cosas que importan: que queda un solo material, que los
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

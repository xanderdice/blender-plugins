# Meldra

Add-on de Blender que suelda, cierra y valida una malla para que el **Decimate**
no abra agujeros y para que los **pesos automáticos** de esqueleto funcionen a
la primera.

Está pensado para lo que sale de los generadores 3D por IA y de los
importadores de `.glb` / `.obj`: mallas que *parecen* sólidas pero que por
dentro son miles de triángulos sueltos, porque cada esquina de cada cara tiene
su propio vértice sin soldar.

*Meldra* viene de **meld**, fundir. Es exactamente lo que hace.

## El problema, en un número

Sobre la misma esfera de 1283 triángulos, decimando al 30 %:

| | superficie conservada | agujeros al terminar |
|---|---|---|
| sin soldar | **34,1 %** | 1146 aristas de borde |
| soldada con Meldra | **99,7 %** | 0 |

Y con esqueleto, sobre la misma malla: sin reparar, los pesos automáticos
cubren el **0 %** de los vértices; reparada, el **100 %**.

Las dos tablas salen de `pruebas/prueba.py`, que se puede ejecutar.

## Instalación

Requiere **Blender 4.2 o superior**, incluido 5.x.

1. Genera el zip haciendo doble clic en `empaquetar.bat`, o desde la consola:

```bash
empaquetar.bat
```

2. En Blender: `Edit > Preferences > Add-ons`, botón `▾` arriba a la derecha,
   **Install from Disk…**, y elige `dist\meldra-2.0.0.zip`.
   También vale arrastrar el zip a la ventana de Blender.
3. El panel aparece en la **Vista 3D > barra lateral (tecla `N`) > pestaña
   "Meldra"**.

## Cómo usarlo

1. Selecciona la malla y pulsa **Analizar malla**.
2. Mira el informe. Todo lo que salga en rojo es un problema real.
3. Para ver *dónde* está, usa los botones de **Ver el problema**: te mete en
   modo edición con esos elementos seleccionados.
4. Pulsa **Reparar todo**.
5. Comprueba que abajo pone `Malla cerrada`.
6. Ahora sí, **Decimar**. Y después, **Esqueleto**.

### Informe

| Línea | Qué significa |
|---|---|
| Vértices duplicados | Vértices encima de otro sin soldar. **Esta es la causa de los agujeros al decimar.** |
| Trozos desconectados | Islas separadas. Más de 1 casi siempre es basura flotante. |
| Agujeros (aristas borde) | Aristas con una sola cara. Son los agujeros de verdad. |
| Aristas con >2 caras | Geometría imposible. Rompe booleanos, impresión y rig. |
| Vértices no-manifold | Dos superficies unidas solo por un punto. |
| De área cero | Caras degeneradas. Hacen fallar los pesos por calor. |
| Interiores | La segunda cáscara que traen muchos modelos generados. |
| Normales incoherentes | Caras vecinas con el giro contrario. |
| Euler V−E+F | 2 en una malla cerrada sin asas; 0 con un agujero pasante. |
| Volumen | Solo se calcula si está cerrada. Si sale positivo, las normales miran hacia fuera. |

### Reparar

Los pasos se ejecutan **en este orden**, que es el que importa:

1. Aplicar rotación y escala.
2. Quitar shape keys (reparar cambia la topología y las invalida; además
   bloquean el Decimate).
3. Limpiar normales personalizadas.
4. Borrar geometría suelta.
5. **Soldar vértices** — el paso que arregla el problema.
6. Disolver degenerados y borrar caras de área cero.
7. Borrar caras interiores.
8. Rellenar agujeros.
9. Borrar trozos sueltos pequeños (opcional, apagado por defecto).
10. Recalcular normales, y voltear la malla entera si el volumen sale negativo.

Entre medias vuelve a barrer vértices huérfanos tres veces, porque soldar y
disolver crean huérfanos nuevos.

**Tolerancia de soldadura.** Se calcula sobre la diagonal del modelo, así que
funciona igual con un modelo de 2 m o de 2 cm:

- *Precisa* (1e-5 de la diagonal): para mallas de IA y exportaciones glTF/OBJ,
  donde los duplicados están exactamente en la misma posición. **Es la que
  quieres casi siempre.**
- *Normal* (1e-4): escaneos y fotogrametría.
- *Agresiva* (1e-3): cierra a lo bruto; puede comerse detalle fino.
- *Manual*: distancia exacta en unidades de Blender.

### Esqueleto

El panel lista los requisitos que exige el reparto de pesos por calor
(*Bone Heat Weighting*) y da un veredicto. **Preparar para esqueleto** repara y
además fuerza la escala aplicada y coloca el origen si se lo pides.
**Emparentar con pesos automáticos** hace el `Ctrl+P > With Automatic Weights`
y, si falla, dice cuál de los requisitos es el probable culpable.

### Reconstruir

Último recurso cuando la malla no hay por dónde cogerla. El remesh por voxeles
**siempre** sale cerrado y manifold, pero se pierden UV y materiales.
QuadriFlow da topología en cuads y exige una malla ya manifold: repara antes.

## Idiomas

Meldra habla los **48 idiomas que Blender sabe mostrar**. Se traduce solo:
usa el idioma que tengas puesto en `Preferences > Interface > Translation`.

> Abjasio · Alemán · Árabe · Búlgaro · Catalán · Checo · Chino (simplificado y
> tradicional) · Coreano · Danés · Eslovaco · Esloveno · Español · Esperanto ·
> Euskera · Finés · Francés · Georgiano · Griego · Hebreo · Hindi · Húngaro ·
> Indonesio · Inglés británico · Italiano · Japonés · Kirguís · Lituano ·
> Malayalam · Neerlandés · Noruego (bokmål) · Persa · Polaco · Portugués
> (Brasil y Portugal) · Rumano · Ruso · Serbio (cirílico y latino) · Suajili ·
> Sueco · Tailandés · Tamil · Turco · Ucraniano · Urdu · Vietnamita

Son **193 cadenas en 48 idiomas: 9.077 traducciones**, y `pruebas/prueba.py`
comprueba que ningún idioma tiene claves de más ni de menos, y que los
marcadores de formato (`%d`, `%s`, `%.4f`) sobreviven a la traducción en el
mismo orden — un descuadre ahí reventaría el add-on en tiempo de ejecución.

Cada idioma vive en `meldra/idiomas/`, en un diccionario aislado: se puede
corregir uno sin tocar los demás. Se agradecen las correcciones de hablantes
nativos.

> Para algunos términos que Blender ya traduce por su cuenta (*Holes*, *Loose*,
> *N-gons*…) Blender usa su propio diccionario y no el nuestro. Es lo deseable:
> así el add-on habla igual que el resto del programa.

## Empaquetar y publicar

```bash
empaquetar.bat
```

Pasa las 80 comprobaciones, genera `dist\meldra-<versión>.zip`, valida el
manifiesto con el propio Blender y te dice dónde subirlo. Si no hay Blender
instalado se salta las pruebas y la validación, pero genera el zip igual.

Para subir versión: cambia `version` en `meldra/blender_manifest.toml` y vuelve
a lanzar el bat. El `id` no cambia, así que Blender reemplaza la instalación
anterior en vez de duplicarla.

También funciona sin Windows:

```bash
python empaquetar.py
```

## Pruebas

```bash
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --factory-startup --python pruebas/prueba.py
```

Fabrica una malla rota a propósito (todos los vértices desoldados, dos
agujeros, basura suelta, un trozo flotante, una cara de área cero y unas
cuantas caras invertidas) y comprueba **80 cosas**: el diagnóstico, la
reparación, que el decimate ya no rompe nada, la decimación por número de
triángulos, el rig con pesos automáticos, varias mallas a la vez, los botones
de selección, el remesh, los casos límite (malla vacía, plano, cubo sano, malla
del revés), la cobertura de los 48 idiomas, que la traducción funciona de
verdad en Blender, que el panel no referencia iconos ni propiedades que no
existan, y que el código distribuido no lleva comentarios ni docstrings.

Sale con código 1 si algo falla.

Herramientas de desarrollo, no se distribuyen:

```bash
blender --background --factory-startup --python pruebas/extraer.py   # lista las cadenas traducibles
blender --background --factory-startup --python pruebas/idiomas.py   # revisa solo los idiomas
```

## Rendimiento

Peor caso medido en Blender 5.1.2: una esfera de **983 040 vértices con todo
desoldado** (327 680 caras sueltas).

| Operación | Tiempo |
|---|---|
| Analizar | 2,1 s |
| Seleccionar duplicados | 0,9 s |
| Reparar todo | 2,5 s (983 040 → 163 842 vértices, cerrada) |
| Decimar a 20 000 triángulos | 1,2 s (sigue cerrada) |

## Aviso sobre las UV

Soldar vértices funde también las costuras de UV, así que las coordenadas de
textura se distorsionan en los bordes de isla. No hay forma de evitarlo: los
vértices duplicados y las costuras de UV son la misma cosa vista desde dos
lados. Si necesitas conservar la textura, hornéala del modelo original de alta
densidad al decimado (`Bake` con *Selected to Active*).

Para la próxima vez: al importar `.glb`/`.gltf`, marca **Merge Vertices** en la
sección *Geometry* del diálogo de importación y te ahorras todo esto.

## Estructura

```
meldra/
  blender_manifest.toml   manifiesto de extensión (Blender 4.2+)
  __init__.py             registro y alta de las traducciones
  nucleo.py               análisis y reparación, solo bmesh, sin bpy.ops
  props.py                ajustes del panel e informe
  ops.py                  operadores
  ui.py                   panel de la barra lateral
  version.py              lee la versión del manifiesto
  idiomas/                48 idiomas, agrupados por familia
pruebas/prueba.py         suite contra un Blender real
pruebas/extraer.py        lista canónica de cadenas traducibles
pruebas/idiomas.py        validador de traducciones
empaquetar.bat            genera y valida el zip distribuible
empaquetar.py             el motor del empaquetado, multiplataforma
```

`nucleo.py` no toca `bpy.ops` ni el estado del editor a propósito: así se puede
probar en segundo plano y no depende de en qué modo esté el objeto.

## Créditos

**xander.dice**

- Instagram: [@xander.dice](https://www.instagram.com/xander.dice)
- YouTube: [@xanderdice](https://www.youtube.com/@xanderdice)
- Facebook: [djxanderdice](https://www.facebook.com/djxanderdice)

## Licencia

GPL-3.0-or-later, como exige cualquier add-on que enlace con la API de Blender.

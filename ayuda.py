#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v119 — Ayuda en castellano llano, en cada sección.

Lo que pidió el usuario
-----------------------
«Quiero que en absolutamente cada sección haya algo que ayude a entender cómo
usar cada cosa, cómo leer las predicciones, que ayude a escoger y a validar.
Quizá el usuario no sabe qué es EV, tradúcelo a su idioma, quizá no sabe qué es
line shopping.»

Dos reglas al escribir esto
---------------------------
1. **Nada de jerga sin traducir.** Si aparece «EV», al lado va qué significa en
   dinero. Si aparece «line shopping», va «comprar al mejor precio».
2. **Ni una promesa que el proyecto no haya medido.** Es tentador escribir una
   ayuda que anime a apostar; aquí se dice lo contrario de lo que el usuario
   espera oír cuando eso es lo que dicen los datos: que el modelo no bate al
   mercado, que su EV es anti-indicador del cierre, y que lo único con retorno
   positivo comprobado es comprar al mejor precio.

Una ayuda que exagere el valor de la herramienta hace perder dinero a quien la
lee. Por eso los avisos van dentro de la propia explicación y no en una nota al
pie que nadie abre.
"""
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Glosario: término -> (traducción corta, explicación larga)
# ---------------------------------------------------------------------------
GLOSARIO = {
    'EV': (
        'Valor esperado: lo que ganarías o perderías de media por cada 100 $ '
        'si repitieras esa apuesta muchísimas veces.',
        'Se calcula multiplicando la cuota por la probabilidad y restando 1. '
        'Un EV de +5 % dice «de media ganarías 5 $ por cada 100 apostados» — '
        'pero sólo si la probabilidad del modelo es correcta.\n\n'
        '⚠️ **Aquí hay que ser honesto**: en este proyecto está medido que el '
        'EV que declara el modelo es un **anti-indicador** (correlación −0,054 '
        'con el precio de cierre). Es decir, las apuestas con más EV declarado '
        'tienden a cerrar PEOR. Úsalo como «esta casa paga más que las otras», '
        'no como «esto gana dinero».'),
    'line shopping': (
        'Comprar al mejor precio: la misma apuesta pagada más cara porque la '
        'buscas en varias casas en vez de en una.',
        'Si Pinnacle paga 2,00 y Playdoit 2,10 por lo mismo, apostar en '
        'Playdoit te da un 5 % más sin cambiar nada de la apuesta.\n\n'
        '✅ **Es lo único que este proyecto ha medido con ganancia positiva y '
        'robusta**: +11,49 % en el tramo de validación, y +1,37 % incluso sin '
        'usar el modelo para nada. Si sólo vas a hacer caso de una cosa de '
        'toda la aplicación, que sea ésta.'),
    'cuota justa': (
        'El precio que NO tendría ganancia para nadie: 1 dividido entre la '
        'probabilidad.',
        'Si algo tiene un 50 % de pasar, su cuota justa es 2,00. Las casas '
        'pagan menos que eso —ahí está su negocio—, así que una cuota justa '
        'nunca es un precio real que puedas tomar. Sirve para comparar: si la '
        'casa paga MÁS que la justa, el modelo cree que hay valor.'),
    'margen': (
        'Lo que se queda la casa: cuánto suman las probabilidades de todos los '
        'resultados por encima del 100 %.',
        'Un margen de 1,05 significa que la casa se queda con un 5 %. Cuanto '
        'más bajo, mejor para ti. Medido en este tablón: Pinnacle 1,0311, la '
        'media de las casas 1,0550, y el mejor precio combinando varias, '
        '1,0034 — de ahí que comparar casas sea lo que más rinde.'),
    'capa 1': (
        'Apuestas que pasan TODOS los filtros de calidad y tienen precio real '
        'de una casa.',
        'Se les exige probabilidad alta, EV positivo, cuota mínima y '
        'fiabilidad histórica de la competición. Que un día haya cero no es un '
        'fallo: es el sistema no forzando apuestas, que es exactamente cómo se '
        'evita perder dinero.'),
    'capa 2': (
        'Partidos probables pero que NO pasan los filtros, casi siempre porque '
        'la cuota es demasiado corta.',
        'Sirven de pata en una combinada, no como apuesta suelta: acertar el '
        '70 % a cuota 1,30 pierde dinero a la larga.'),
    'CLV': (
        'Si tu precio fue mejor que el de cierre. Es la mejor señal de que una '
        'apuesta estaba bien tomada.',
        'Si apostaste a 2,10 y el partido cerró a 1,95, le ganaste al mercado. '
        'Medido aquí: cuando se le gana al cierre el retorno es +0,79 %, y '
        'cuando no, −4,19 %. El problema es que no se puede saber por '
        'adelantado — ningún filtro lo ha conseguido predecir.'),
    'hándicap': (
        'Una ventaja o desventaja de goles que se aplica antes de contar el '
        'resultado.',
        '«Monterrey −1.5» gana si Monterrey vence por dos o más. «Juárez '
        '+1.5» gana si Juárez pierde por uno, empata o gana. Sirven para '
        'sacarle precio a un favorito claro o proteger a un no favorito.'),
    'BTTS': (
        'Ambos marcan: si los dos equipos anotan al menos un gol.',
        'No depende de quién gane, así que es útil cuando tienes clara la '
        'dinámica del partido pero no el ganador.'),
    'combinada': (
        'Varias apuestas en una: tienen que acertar TODAS para cobrar.',
        'La cuota se multiplica, pero la probabilidad también — y por eso las '
        'combinadas largas casi nunca entran. Con cuatro patas al 70 % cada '
        'una, la probabilidad de acertar las cuatro es del 24 %.'),
    'PFP': (
        'La probabilidad real de que acierten todas las patas de una '
        'combinada, ya ajustada porque unas dependen de otras.',
        'Multiplicar las probabilidades sin más exagera: si apuestas «gana el '
        'local» y «más de 2,5 goles», los dos suelen pasar juntos, y eso hay '
        'que tenerlo en cuenta.'),
    'Kelly': (
        'Una fórmula para decidir CUÁNTO apostar según la ventaja que creas '
        'tener.',
        'Aquí se usa una fracción (¼ de Kelly) porque el Kelly completo asume '
        'que tus probabilidades son exactas, y nunca lo son. Es una sugerencia '
        'de tamaño, no una orden.'),
    'sharp': (
        'Una casa «lista»: la que mejor afina los precios y a la que el resto '
        'del mercado sigue.',
        'Pinnacle es la referencia sharp de este proyecto. Si tu casa te paga '
        'más que ella por lo mismo, ahí suele estar el valor.'),
    'devig': (
        'Quitarle a una cuota el margen de la casa para estimar la '
        'probabilidad real.',
        'Es lo que permite comparar precios de casas distintas en igualdad de '
        'condiciones.'),
    'ELO': (
        'Una puntuación de fuerza que sube al ganar y baja al perder, según '
        'contra quién.',
        'Ganarle al primero suma mucho más que ganarle al último. Es la línea '
        'base contra la que se mide si un modelo aporta algo: en varios '
        'deportes de esta aplicación, el ELO por sí solo ya acierta tanto como '
        'el modelo completo.'),
    'xG': (
        'Goles esperados: cuántos goles «merecía» un equipo por la calidad de '
        'sus ocasiones.',
        'Un equipo que pierde 0-1 con 2,5 xG jugó mejor de lo que dice el '
        'marcador, y eso suele corregirse en los partidos siguientes.'),
    'FIP': (
        'Una nota del lanzador que sólo cuenta lo que depende de él: ponches, '
        'bases por bolas y jonrones.',
        'No le castiga por una mala defensa detrás. Más bajo es mejor; por '
        'debajo de 3,50 es un buen abridor.'),
    'run line': (
        'El hándicap del béisbol, casi siempre de 1,5 carreras.',
        '«Favorito −1.5» exige ganar por dos o más carreras; paga bastante más '
        'que el ganador a secas.'),
}

# ---------------------------------------------------------------------------
# Guías por sección: cómo leer esto y qué hacer con ello
# ---------------------------------------------------------------------------
GUIAS = {
    'apuestas_dia': {
        'titulo': 'Cómo leer esta pantalla',
        'pasos': [
            '**Empieza por arriba.** Las cuatro cifras dicen si hoy merece la '
            'pena: cuántos partidos se han evaluado, cuántos tienen precio y '
            'cuántos pasan los filtros.',
            '**Cero apuestas de élite es una respuesta, no un error.** '
            'Significa que las casas y el modelo coinciden. Forzar una apuesta '
            'ahí es exactamente como se pierde dinero.',
            '**Mira la casa, no sólo el EV.** Un mismo resultado puede pagarse '
            'un 5 % más en otra casa, y eso es lo único que este proyecto ha '
            'medido con ganancia real.',
            '**Pulsa «Ver el partido»** para abrir su competición con el '
            'historial, la forma y todos los mercados, y decidir con contexto.',
        ],
        'terminos': ['capa 1', 'capa 2', 'EV', 'line shopping'],
    },
    'liga': {
        'titulo': 'Cómo usar la vista de una competición',
        'pasos': [
            '**Elige el partido** en «Próximos partidos»: se cargan solos sus '
            'equipos y sus datos.',
            '**Contrasta el pronóstico con el contexto.** El historial, la '
            'forma y el desgaste están abajo; el modelo ya los tiene en '
            'cuenta, así que sirven para juzgar su pronóstico, no para '
            'sumarle nada.',
            '**En la tabla de mercados, ordena por «Ventaja de precio».** Es '
            'la diferencia entre lo que paga la mejor casa y la peor. Ordenar '
            'por EV pone arriba los errores del modelo.',
            '**Desconfía de un EV enorme.** Si sale +40 % con una sola casa, '
            'casi siempre es el modelo equivocándose, no una oportunidad. Van '
            'marcados con ⚠️.',
        ],
        'terminos': ['cuota justa', 'EV', 'hándicap', 'BTTS', 'margen'],
    },
    'combinadas': {
        'titulo': 'Cómo elegir una combinada',
        'pasos': [
            '**Fíjate primero en la probabilidad de acertar todo**, no en la '
            'cuota. Una cuota de 8,00 con un 12 % de probabilidad es peor '
            'negocio que una de 2,00 al 55 %.',
            '**Prefiere las que tienen todas las patas con precio real.** Si '
            'alguna va con cuota justa, la cuota combinada que ves no es la '
            'que te van a pagar.',
            '**Mira cuántas casas se han comparado en cada pata.** Con dos o '
            'más, el precio está contrastado; con una sola, no hay con qué '
            'compararlo.',
            '**Cuantas más patas, menos probable.** El sistema no propone '
            'combinadas de siete patas por una razón.',
        ],
        'terminos': ['combinada', 'PFP', 'EV', 'line shopping'],
    },
    'mlb': {
        'titulo': 'Cómo leer el béisbol',
        'pasos': [
            '**El abridor manda.** Es el factor que más mueve un partido de '
            'béisbol, y por eso la pantalla empieza por él.',
            '**El parque importa casi tanto.** Un mismo partido en un estadio '
            'de bateadores tiene más carreras que en uno de lanzadores.',
            '**La probabilidad que ves está comprobada.** Se ha validado '
            'simulando 23.466 partidos pasados: cuando dice 62 %, gana el '
            '62 % (error medio de medio punto).',
            '**Pero el modelo apenas mejora al ELO** en este deporte. Tómalo '
            'como una referencia bien calibrada, no como una ventaja sobre el '
            'mercado.',
        ],
        'terminos': ['FIP', 'run line', 'ELO', 'EV'],
    },
    'tenis': {
        'titulo': 'Cómo leer el tenis',
        'pasos': [
            '**La superficie lo cambia todo.** Mira el ELO de superficie, no '
            'el general: un especialista en tierra y uno en pista rápida no se '
            'ordenan igual según dónde jueguen.',
            '**Vigila la carga de partidos.** Quien lleva cuatro partidos en '
            'una semana llega distinto, y eso pesa en los sets largos.',
            '**El mercado de tenis es muy eficiente.** Aquí la herramienta '
            'sirve sobre todo para analizar y armar combinadas, no para '
            'encontrar precios equivocados.',
        ],
        'terminos': ['ELO', 'cuota justa', 'combinada'],
    },
    'selecciones': {
        'titulo': 'Cómo leer los partidos internacionales',
        'pasos': [
            '**Comprueba la categoría.** No es lo mismo la absoluta que un '
            'sub-20 o un femenino: son plantillas distintas y el histórico de '
            'cada una también.',
            '**Los amistosos valen menos de lo que parecen.** Se hacen cambios '
            'masivos y el resultado dice poco del nivel real.',
            '**Las casas abren línea cerca de la fecha FIFA.** Fuera de esas '
            'ventanas es normal que no haya precio para casi nada.',
        ],
        'terminos': ['ELO', 'cuota justa', 'EV'],
    },
}


def render(st, seccion: str, expandido: bool = False) -> None:
    """
    Pinta la ayuda de una sección. Nunca lanza: si algo falla, la pantalla
    sigue exactamente igual, sólo sin la ayuda.
    """
    try:
        g = GUIAS.get(seccion)
        if not g:
            return
        with st.expander(f"❓ {g['titulo']}", expanded=expandido):
            for paso in g['pasos']:
                st.markdown(f"- {paso}")
            terminos = [t for t in g.get('terminos', []) if t in GLOSARIO]
            if terminos:
                st.markdown("**Palabras que aparecen en pantalla:**")
                for t in terminos:
                    corta, larga = GLOSARIO[t]
                    with st.expander(f"¿Qué es «{t}»?"):
                        st.markdown(f"**{corta}**")
                        st.markdown(larga)
    except Exception as e:
        logger.debug(f'[ayuda] {seccion}: {type(e).__name__}: {e}')


def glosario_completo(st) -> None:
    """El glosario entero, para la barra lateral."""
    try:
        with st.expander("📖 Diccionario de apuestas"):
            st.caption("Todos los términos que usa la aplicación, en "
                       "castellano llano.")
            for termino in sorted(GLOSARIO):
                corta, larga = GLOSARIO[termino]
                with st.expander(termino):
                    st.markdown(f"**{corta}**")
                    st.markdown(larga)
    except Exception as e:
        logger.debug(f'[ayuda] glosario: {type(e).__name__}: {e}')

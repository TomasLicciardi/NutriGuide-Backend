# tests/test_parser.py
"""
Tests del parser v3 sobre los textos reales de las etiquetas del Dataset/.

Cada test case representa una foto (texto extraído manualmente). Validamos:
  - Cantidad correcta de ingredientes parseados
  - Detección correcta de Ley 25.630 (bloque unificado)
  - Detección correcta de aromatizantes y separación del target_sensory
  - Extracción correcta de códigos INS
  - Herencia de función (un prefijo aplica a varios ingredientes)
  - Parser de declaración legal (CONTIENE / PUEDE CONTENER / claims positivos)

Ejecutar:
    python -m pytest tests/test_parser.py -v -s
    python tests/test_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.parser import parse_ingredient_list, parse_allergen_declaration
from app.services.ingredient_facts import FlavoringType


# ═══════════════════════════════════════════════════════════════════════════
# Casos de prueba — todas las fotos textuales del usuario
# ═══════════════════════════════════════════════════════════════════════════

CASES = [
    # ── Batch 1: Dataset/foto1-24 ────────────────────────────────────────
    {
        "id": "foto1_avena",
        "ingredients": "Avena arrollada. En Bolivia: Hojuelas de avena.",
        "allergens": "CONTIENE: GLUTEN. CONTIENE AVENA. PUEDE CONTENER: TRIGO, SOJA, CEBADA, CENTENO Y MANÍ.",
    },
    {
        "id": "foto2_cereales_maiz",
        "ingredients": "Maíz, azúcar, sal, extracto de malta, antioxidante (lecitina de soja).",
        "allergens": "CONTIENE SULFITOS Y DERIVADOS DE SOJA Y CEBADA. PUEDE CONTENER AVENA, ALMENDRA Y DERIVADOS DE TRIGO Y CENTENO.",
    },
    {
        "id": "foto3_galletas_dulces",
        "ingredients": (
            "Azúcar, harina de trigo enriquecida (Ley 25.630), oleomargarina, "
            "almidón de maíz, aceite de girasol, sal; "
            "EMU: lecitina de soja (INS 322); RAI: bicarbonato de sodio (INS 500ii); "
            "ARO: artificial sabor a vainilla; ACI: ácido cítrico (INS 330)."
        ),
        "allergens": "CONTIENE DERIVADO DE TRIGO Y DE SOJA. PUEDE CONTENER LECHE, MANÍ Y HUEVO.",
    },
    {
        "id": "foto4_snacks_complejo",
        "ingredients": (
            "Harina de maíz, aceite vegetal de palma y canola (TBHQ), "
            "sazonador (sal, maltodextrina de maíz, ácido cítrico, azúcar, glutamato monosódico, "
            "aceite de soya, cebolla en polvo, bicarbonato de sodio, azul brillante FCF, "
            "saborizante natural, idéntico al natural y artificial, hidrolizado de proteína de maíz, "
            "extracto de levadura, inosinato disódico, guanilato disódico)."
        ),
        "allergens": "Elaborado en líneas que también procesan gluten, huevo, soya, leche, maní.",
    },
    {
        "id": "foto5_ketchup",
        "ingredients": (
            "Agua; Concentrado doble de tomate; Azúcar; Vinagre; Sal; Cebolla; Ajo; "
            "Acidulante: Ácido láctico; Resaltador de sabor: Glutamato de sodio; "
            "Estabilizante: Goma xántica; Colorante: Caramelo IV; "
            "Aromatizante / Saborizante; Conservante: Sorbato de potasio."
        ),
        "allergens": None,
    },
    {
        "id": "foto6_harina_enriquecida",
        "ingredients": (
            "Harina de trigo enriquecida ley 25.630 (*), fumarato ferroso, óxido de zinc, "
            "vitamina B2, vitamina B6, vitamina B1, vitamina A, vitamina B9, vitamina D, "
            "vitamina B12, colorante: cúrcuma."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
    },
    {
        "id": "foto7_almidon",
        "ingredients": "Almidón de maíz.",
        "allergens": "CONTIENE SULFITOS.",
    },
    {
        "id": "foto8_harina_enriquecida_dup",
        "ingredients": (
            "Harina de trigo enriquecida ley 25.630 (*), fumarato ferroso, óxido de zinc, "
            "vitamina B2, vitamina B6, vitamina B1, vitamina A, vitamina B9, vitamina D, "
            "vitamina B12, colorante: cúrcuma."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
    },
    {
        "id": "foto9_harina_pasta",
        "ingredients": (
            "Harina de trigo enriquecida según Ley 25.630 "
            "(Sulfato Ferroso: 30 mg/kg – como Hierro-, Niacina: 13 mg/kg, "
            "Vitamina B1: 6.3 mg/kg, Ácido fólico: 2.2 mg/kg, Vitamina B2: 1.3 mg/kg)."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
    },
    {
        "id": "foto10_mayonesa",
        "ingredients": (
            "Agua, aceite de girasol, azúcar, extracto de tomate, almidón modificado, sal, "
            "vinagre de alcohol, huevo líquido, jugo concentrado de limón, "
            "estabilizante: goma xántica, acidulante: ácido fosfórico, "
            "conservador: ácido sórbico, aromatizantes: natural e idéntico al natural, "
            "secuestrante: EDTA disódico cálcico y antioxidantes: BHA y BHT."
        ),
        "allergens": "CONTIENE HUEVO.",
    },
    {
        "id": "foto11_salsa_tomate",
        "ingredients": (
            "Agua, concentrado doble de tomate, azúcar, vinagre de alcohol, maltodextrina, sal, "
            "cebolla en polvo, ajo en polvo, especias, "
            "estabilizante: goma xántica, acidulante: ácido cítrico, "
            "conservador: sorbato de potasio, aromatizantes naturales e idénticos al natural."
        ),
        "allergens": None,
    },
    {
        "id": "foto12_mostaza",
        "ingredients": (
            "agua, vinagre de alcohol, vinagre de vino, almidón modificado, "
            "especia mostaza blanca, cúrcuma, canela, nuez moscada, semilla de apio, ají molido, "
            "comino, clavo de olor, pimienta negra, tomillo, orégano, jengibre, laurel, "
            "azúcar, sal, aceite de girasol, cebolla, ajo, "
            "estabilizante: goma xántica, conservador: ácido sórbico, "
            "colorantes: caramelo IV y clorofila, aromatizante idéntico al natural, "
            "secuestrante: EDTA disódico cálcico y antioxidantes: BHA, BHT."
        ),
        "allergens": "PUEDE CONTENER TRIGO, AVENA, CEBADA Y CENTENO.",
    },
    {
        "id": "foto13_harina_mejoradores",
        "ingredients": (
            "Harina 0000 enriquecida Ley 25.630*, mejoradores de harina (INS 341iii, INS 928)."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER DERIVADOS DE SOJA.",
    },
    {
        "id": "foto14_chocolatada",
        "ingredients": (
            "Azúcar, Cacao en polvo, Suero de leche, "
            "Vitaminas y Minerales (Vitaminas C, D y B1, Pirofosfato férrico, Sulfato de zinc), "
            "Sal, Canela en polvo, Emulsionante (Lecitina de soja), Aromatizante natural (Vainilla)."
        ),
        "allergens": "CONTIENE DERIVADOS DE LECHE Y DE SOJA.",
    },
    {
        "id": "foto15_sal_yodada",
        "ingredients": (
            "sal (cloruro de sodio) y yodato de potasio. "
            "Antiaglutinantes: INS 551 y/o INS 536."
        ),
        "allergens": "Libre de gluten - Sin T.A.C.C.",
    },
    {
        "id": "foto16_galletitas_complejo",
        "ingredients": (
            "Harina de trigo 000 enriquecida según ley 25630*, "
            "Aceite de girasol alto oleico, Vinagre de alcohol, Sal, Cloruro de potasio. "
            "Humectante: INS 422. Emulsionantes: INS 471, INS 412. "
            "Conservante: INS 282. Acidulante: INS 330. Mejorador de harina: INS 920."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO, LECHE, DERIVADOS DE SOJA, DE AVENA Y DE CEBADA.",
    },
    {
        "id": "foto17_caldo",
        "ingredients": (
            "Sal, grasa vegetal, almidón de maíz no modificado, azúcar, "
            "aceite de palma (con antioxidante BHA/BHT), pimienta roja, perejil, laurel en polvo, "
            "ajo en polvo, carne bovina deshidratada, "
            "resaltadores de sabor (glutamato monosódico, inosinato de sodio), "
            "aromatizantes, colorantes (caramelo, rocú) y acidulante (ácido cítrico)."
        ),
        "allergens": (
            "PARA ARGENTINA Y PARAGUAY: CONTIENE DERIVADOS DE SOJA. PUEDE CONTENER CEBADA. "
            "PARA URUGUAY: CONTIENE DERIVADOS DE SOJA. PUEDE CONTENER APIO Y CEBADA."
        ),
    },
    {
        "id": "foto18_sopa",
        "ingredients": (
            "almidón de papa, vegetales (zapallo, cebolla, perejil), azúcar, maltodextrina, "
            "jarabe de glucosa, sal, aceites vegetales, romero, caseinato de sodio, pimienta negra, "
            "exaltador de sabor: glutamato monosódico, inosinato disódico, guanilato disódico, "
            "espesante: goma xántica, aromatizantes naturales, colorante: annatto."
        ),
        "allergens": "CONTIENE DERIVADO DE LECHE. PUEDE CONTENER PESCADO Y DERIVADOS DE SOJA Y DE TRIGO.",
    },
    {
        "id": "foto19_tomate_pelado",
        "ingredients": "Tomate pelado; jugo de tomates; regulador de acidez: Ácido Cítrico.",
        "allergens": None,
    },
    {
        "id": "foto20_tomate_simple",
        "ingredients": "tomate; regulador de acidez: Ácido Cítrico.",
        "allergens": None,
    },
    {
        "id": "foto21_atun",
        "ingredients": "Atún, Agua y Sal.",
        "allergens": "CONTIENE PESCADO.",
    },
    {
        "id": "foto22_fideos_huevo",
        "ingredients": (
            "Harina de trigo tipo 000 enriquecida Ley Nº 25.630 "
            "(sulfato ferroso: 30 mg/kg –como hierro–, niacina: 13 mg/kg, "
            "vitamina B1: 6.3 mg/kg, ácido fólico: 2.2 mg/kg, vitamina B2: 1.3 mg/kg), huevo."
        ),
        "allergens": "CONTIENE HUEVO Y DERIVADOS DE TRIGO. PUEDE CONTENER SOJA.",
    },
    {
        "id": "foto23_harina",
        "ingredients": (
            "Harina de trigo enriquecida según Ley 25.630 "
            "(Sulfato Ferroso: 30 mg/kg – como Hierro-, Niacina: 13 mg/kg, "
            "Vitamina B1: 6.3 mg/kg, Ácido fólico: 2.2 mg/kg, Vitamina B2: 1.3 mg/kg)."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
    },
    {
        "id": "foto24_pasta_semola",
        "ingredients": (
            "Harina de trigo enriquecida según Ley 25.630 * "
            "(sulfato ferroso, niacinamida, riboflavina, tiamina y ácido fólico), "
            "Sémola de Trigo Candeal y agua."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO.",
    },

    # ── Batch 2: Foto 27-74 ──────────────────────────────────────────────
    {
        "id": "foto27_galletas_dulces_complejo",
        "ingredients": (
            "Harina de trigo enriquecida Ley Nº 25.630 "
            "(hierro: 30 mg/kg, ácido fólico: 2,2 mg/kg, tiamina (B1): 6,3 mg/kg, "
            "riboflavina (B2): 1,3 mg/kg, niacina: 13,0 mg/kg), "
            "azúcar, grasa bovina refinada, jarabe de maíz de alta fructosa (JMAF), "
            "cacao alcalinizado, sal, "
            "leudantes químicos: bicarbonato de sodio (INS 500ii), bicarbonato de amonio (INS 503ii), "
            "emulsionante: lecitina de soja (INS 322), "
            "aromatizante artificial a vainilla, "
            "colorante: caramelo IV (INS 150d)."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO Y DE SOJA. PUEDE CONTENER LECHE, MANÍ Y AVENA.",
    },
    {
        "id": "foto28_jugo_naranja",
        "ingredients": (
            "Agua, jugo concentrado de naranja, azúcar, "
            "acidulante: ácido cítrico (INS 330), "
            "conservantes: benzoato de sodio (INS 211), sorbato de potasio (INS 202), "
            "edulcorantes no nutritivos: sucralosa (INS 955) (15 mg/100 ml), "
            "acesulfame K (INS 950) (8 mg/100 ml), "
            "aromatizante idéntico al natural de naranja, "
            "colorantes: amarillo ocaso FCF (INS 110), tartrazina (INS 102)."
        ),
        "allergens": "CONTIENE TARTRAZINA.",
    },
    {
        "id": "foto29_chocolatada_leche",
        "ingredients": (
            "Leche entera, suero de queso en polvo, azúcar, cacao en polvo, "
            "almidón modificado de maíz, "
            "espesante: carragenina (INS 407), estabilizante: goma guar (INS 412), "
            "aromatizante artificial a chocolate."
        ),
        "allergens": "CONTIENE LECHE Y DERIVADOS DE LECHE. PUEDE CONTENER SOJA.",
    },
    {
        "id": "foto30_palitos_queso",
        "ingredients": (
            "Harina de maíz, aceite de girasol, sal, suero de queso en polvo, maltodextrina, "
            "resaltador de sabor: glutamato monosódico (INS 621), inosinato disódico (INS 631), "
            "aromatizante idéntico al natural sabor queso, "
            "colorante: annatto (INS 160b), "
            "antiaglutinante: dióxido de silicio (INS 551)."
        ),
        "allergens": "CONTIENE DERIVADOS DE LECHE. PUEDE CONTENER DERIVADOS DE TRIGO Y SOJA.",
    },
    {
        "id": "foto31_pan_levadura",
        "ingredients": (
            "Harina de trigo enriquecida según Ley 25.630 "
            "(Sulfato Ferroso: 30 mg/kg, Niacina: 13 mg/kg, Vitamina B1: 6.3 mg/kg, "
            "Ácido fólico: 2.2 mg/kg, Vitamina B2: 1.3 mg/kg), "
            "agua, levadura, azúcar, sal, aceite de girasol alto oleico, "
            "conservante: propionato de calcio (INS 282), "
            "mejorador de la harina: ácido ascórbico (INS 300), "
            "emulsionante: estearoil lactilato de sodio (INS 481i)."
        ),
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER AVENA, CEBADA Y CENTENO.",
    },
    {
        "id": "foto32_mermelada_frutilla",
        "ingredients": (
            "Frutilla, agua, jarabe de glucosa, "
            "espesantes: pectina (INS 440), goma garrofín (INS 410), "
            "acidulante: ácido cítrico (INS 330), "
            "conservante: sorbato de potasio (INS 202), "
            "edulcorantes no nutritivos: ciclamato de sodio (INS 952), "
            "glicósidos de esteviol (INS 960), "
            "colorante: carmín (INS 120), "
            "aromatizante idéntico al natural a frutilla."
        ),
        "allergens": "PUEDE CONTENER DERIVADOS DE LECHE.",
    },
    {
        "id": "foto41_gomitas",
        "ingredients": (
            "Jarabe de glucosa, azúcar, agua, gelatina, "
            "acidulantes: ácido cítrico (INS 330), ácido láctico (INS 270), "
            "aromatizantes artificiales (frutilla, limón, naranja, manzana), "
            "aceite vegetal (palma), "
            "agente de recubrimiento: cera de abejas (INS 901), cera de carnauba (INS 903), "
            "colorantes: rojo allura AC (INS 129), amarillo ocaso (INS 110), "
            "tartrazina (INS 102), azul brillante FCF (INS 133)."
        ),
        "allergens": "CONTIENE TARTRAZINA. PUEDE CONTENER DERIVADOS DE SOJA Y LECHE.",
    },
    {
        "id": "foto50_mix_frutos_secos",
        "ingredients": (
            "Almendras tostadas, castañas de cajú, pasas de uva rubias, nueces peladas, "
            "semillas de zapallo, semillas de girasol, aceite de canola."
        ),
        "allergens": "CONTIENE ALMENDRAS, CASTAÑAS DE CAJÚ Y NUECES. PUEDE CONTENER MANÍ Y SOJA.",
    },
    {
        "id": "foto56_compota_ciruela",
        "ingredients": (
            "Agua, ciruelas, "
            "edulcorantes no nutritivos: sorbitol (INS 420), sucralosa (INS 955), "
            "gelificante: pectina (INS 440), acidulante: ácido cítrico (INS 330), "
            "conservante: sorbato de potasio (INS 202), "
            "endurecedor: lactato de calcio (INS 327), "
            "colorante artificial: amaranto (INS 123)."
        ),
        "allergens": None,
    },
    {
        "id": "foto57_salsa_soja",
        "ingredients": "Agua, porotos de soja, trigo, sal, alcohol etílico (como conservante).",
        "allergens": "CONTIENE SOJA Y DERIVADOS DE TRIGO.",
    },
    {
        "id": "foto58_arroz_parboil",
        "ingredients": (
            "Arroz parboil, vegetales deshidratados (zanahoria, arvejas, cebolla, morrón rojo), "
            "sal, extracto de levadura, aceite de maíz, "
            "especias (cúrcuma, pimentón dulce, comino), "
            "antiaglutinante: dióxido de silicio (INS 551)."
        ),
        "allergens": None,
    },
    {
        "id": "foto59_arroz_integral_choco",
        "ingredients": (
            "Arroz integral, baño de repostería semiamargo "
            "(azúcar, masa de cacao, manteca de cacao, "
            "emulsionantes: lecitina de girasol (INS 322), "
            "poliglicerol polirricinoleato (INS 476), "
            "aromatizante natural a vainilla)."
        ),
        "allergens": "PUEDE CONTENER LECHE Y DERIVADOS DE SOJA.",
    },
    {
        "id": "foto60_jugo_limon_sulfitos",
        "ingredients": (
            "Jugo de limón, aceite esencial de limón, "
            "conservante: metabisulfito de sodio (INS 223)."
        ),
        "allergens": "CONTIENE SULFITOS.",
    },
    {
        "id": "foto61_te_negro",
        "ingredients": (
            "Té negro (Camellia sinensis), trozos de manzana deshidratada, "
            "canela en rama triturada, clavo de olor, "
            "aromatizante natural a manzana y canela."
        ),
        "allergens": None,
    },
    {
        "id": "foto62_queso_fresco",
        "ingredients": (
            "Leche cruda de vaca, sal, cuajo, fermentos lácticos, "
            "antiaglutinante: celulosa microcristalina (INS 460i), "
            "conservante: ácido sórbico (INS 200)."
        ),
        "allergens": "CONTIENE LECHE Y DERIVADOS DE LECHE.",
    },
    {
        "id": "foto63_salsa_jalapeno",
        "ingredients": (
            "Agua, ají jalapeño rojo, vinagre de alcohol, sal, "
            "espesante: goma xántica (INS 415), acidulante: ácido acético (INS 260), "
            "conservante: benzoato de sodio (INS 211), "
            "colorante: extracto de pimentón (INS 160c)."
        ),
        "allergens": None,
    },
    {
        "id": "foto64_dulce_de_leche_artificial",
        "ingredients": (
            "Azúcar, almidón de maíz, carragenina (INS 407), "
            "colorante: caramelo IV (INS 150d), sal, "
            "aromatizante artificial a dulce de leche, "
            "edulcorantes no nutritivos: aspartamo (INS 951), acesulfame K (INS 950), "
            "colorantes artificiales: tartrazina (INS 102), rojo allura AC (INS 129)."
        ),
        "allergens": (
            "CONTIENE TARTRAZINA. FENILCETONÚRICOS: CONTIENE FENILALANINA. "
            "PUEDE CONTENER DERIVADOS DE TRIGO Y SOJA."
        ),
    },
    {
        "id": "foto65_galletitas_grasa_bovina",
        "ingredients": (
            "Harina de trigo enriquecida Ley 25.630, grasa bovina refinada, sal, levadura, "
            "extracto de malta, "
            "emulsionante: lecitina de soja (INS 322), "
            "leudante químico: bicarbonato de sodio (INS 500ii)."
        ),
        "allergens": None,
    },
    {
        "id": "foto66_jugo_polvo_naranja",
        "ingredients": (
            "Maltodextrina, jugo de naranja deshidratado, "
            "acidulante: ácido cítrico (INS 330), "
            "edulcorantes no nutritivos: aspartamo (INS 951), acesulfame K (INS 950), "
            "aromatizante idéntico al natural a naranja, "
            "antiaglutinante: dióxido de silicio (INS 551), "
            "colorantes: dióxido de titanio (INS 171), amarillo ocaso FCF (INS 110), "
            "tartrazina (INS 102)."
        ),
        "allergens": None,
    },
    {
        "id": "foto67_mayonesa_humo",
        "ingredients": (
            "Agua, aceite de girasol, puré de tomate, azúcar, yema de huevo pasteurizada, "
            "vinagre de alcohol, sal, almidón modificado, "
            "estabilizante: goma xántica (INS 415), "
            "conservante: sorbato de potasio (INS 202), "
            "aromatizante natural a humo, "
            "antioxidante: BHT (INS 321)."
        ),
        "allergens": None,
    },
    {
        "id": "foto68_postre_chocolate",
        "ingredients": (
            "Leche entera, azúcar, crema de leche, almidón de maíz, cacao alcalinizado en polvo, "
            "espesantes: carragenina (INS 407), goma garrofín (INS 410), "
            "aromatizante artificial a chocolate y vainilla, "
            "colorante: caramelo IV (INS 150d)."
        ),
        "allergens": None,
    },
    {
        "id": "foto69_gomitas_cereza",
        "ingredients": (
            "Jarabe de glucosa, azúcar, agua, gelatina, "
            "acidulante: ácido láctico (INS 270), "
            "aromatizante idéntico al natural a cereza, "
            "agente de recubrimiento: cera de carnauba (INS 903), "
            "colorante artificial: rojo allura AC (INS 129)."
        ),
        "allergens": None,
    },
    {
        "id": "foto70_pan_simple",
        "ingredients": (
            "Harina de trigo enriquecida según Ley 25.630, agua, sal, levadura, "
            "mejorador de la harina: ácido ascórbico (INS 300), "
            "conservante: propionato de calcio (INS 282)."
        ),
        "allergens": None,
    },
    {
        "id": "foto71_papas_crema_cebolla",
        "ingredients": (
            "Papas, aceite vegetal de palma, sal, suero de queso en polvo, cebolla en polvo, "
            "resaltadores de sabor: glutamato monosódico (INS 621), guanilato disódico (INS 627), "
            "inosinato disódico (INS 631), "
            "aromatizante idéntico al natural a crema y cebolla, "
            "antiaglutinante: fosfato tricálcico (INS 341iii)."
        ),
        "allergens": None,
    },
    {
        "id": "foto72_compota_durazno",
        "ingredients": (
            "Agua, duraznos, "
            "edulcorantes: sorbitol (INS 420), sucralosa (INS 955), "
            "gelificante: pectina (INS 440), acidulante: ácido cítrico (INS 330), "
            "conservante: sorbato de potasio (INS 202), "
            "endurecedor: cloruro de calcio (INS 509), "
            "colorante: annatto (INS 160b)."
        ),
        "allergens": None,
    },
    {
        "id": "foto73_chacinado",
        "ingredients": (
            "Carne de cerdo, agua, carne bovina, almidón de mandioca, sal, proteína de soja, "
            "dextrosa, especias, "
            "estabilizante: polifosfatos (INS 452), "
            "antioxidante: ácido ascórbico (INS 300), "
            "conservante: nitrito de sodio (INS 250), "
            "colorante natural: carmín (INS 120), "
            "aromatizante a humo."
        ),
        "allergens": None,
    },
    {
        "id": "foto74_cereales_miel",
        "ingredients": (
            "Avena arrollada, jarabe de maíz de alta fructosa (JMAF), crispines de arroz, "
            "copos de maíz, azúcar, aceite de girasol, miel, "
            "emulsionante: lecitina de soja (INS 322), aromatizante artificial a miel."
        ),
        "allergens": None,
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Pretty printing (modo script)
# ═══════════════════════════════════════════════════════════════════════════


def _print_parsed(parsed_list, declaration):
    print(f"  → {len(parsed_list)} tokens parseados")
    for i, p in enumerate(parsed_list, 1):
        flags = []
        if p.is_ley_25630_block:
            flags.append("LEY_25630")
        if p.is_flavoring:
            flags.append(f"FLAVORING({p.flavoring_type.value if p.flavoring_type else '?'}, target={p.target_sensory or '∅'})")
        if p.codex_ins_code:
            flags.append(f"INS={p.codex_ins_code}{p.codex_ins_subcode or ''}")
        if p.function_tag:
            flags.append(f"fn={p.function_tag}")
        if p.sub_ingredients:
            flags.append(f"sub={len(p.sub_ingredients)}")
        flag_str = " ".join(flags) if flags else "(simple)"
        print(f"    [{i}] '{p.name}' {flag_str}")
        for j, sub in enumerate(p.sub_ingredients, 1):
            sub_flags = []
            if sub.codex_ins_code:
                sub_flags.append(f"INS={sub.codex_ins_code}")
            if sub.function_tag:
                sub_flags.append(f"fn={sub.function_tag}")
            print(f"        └─[{j}] '{sub.name}' {' '.join(sub_flags)}")

    if declaration:
        print(f"  → Declaración legal:")
        print(f"    contains:        {sorted(declaration.contains) if declaration.contains else '∅'}")
        print(f"    may_contain:     {sorted(declaration.may_contain) if declaration.may_contain else '∅'}")
        print(f"    positive_claims: {sorted(declaration.positive_claims) if declaration.positive_claims else '∅'}")


def run_all():
    print("=" * 80)
    print("PARSER V3 — TEST SUITE COMPLETO")
    print("=" * 80)
    for case in CASES:
        print(f"\n[{case['id']}]")
        print(f"  Input ingredientes: {case['ingredients'][:90]}...")
        print(f"  Input alérgenos:    {case['allergens'] or '(sin)'}")
        try:
            parsed = parse_ingredient_list(case["ingredients"])
            declaration = parse_allergen_declaration(case["allergens"] or "")
            _print_parsed(parsed, declaration)
        except Exception as e:
            print(f"  ✗ EXCEPCIÓN: {type(e).__name__}: {e}")
    print("\n" + "=" * 80)


# ═══════════════════════════════════════════════════════════════════════════
# Tests pytest — assertions específicas sobre comportamiento crítico
# ═══════════════════════════════════════════════════════════════════════════


def _by_id(case_id):
    """Helper para encontrar un case por id."""
    for c in CASES:
        if c["id"] == case_id:
            return c
    raise KeyError(case_id)


# ── Bloque Ley 25.630 ──────────────────────────────────────────────────


def test_ley_25630_unification_basic():
    text = "Harina de trigo enriquecida Ley Nº 25.630 (hierro, ácido fólico), azúcar."
    parsed = parse_ingredient_list(text)
    ley_blocks = [p for p in parsed if p.is_ley_25630_block]
    assert len(ley_blocks) == 1


def test_ley_25630_with_paren_immediately():
    """foto3: 'harina de trigo enriquecida (Ley 25.630)' — Ley dentro de paréntesis."""
    text = "harina de trigo enriquecida (Ley 25.630), azúcar."
    parsed = parse_ingredient_list(text)
    ley_blocks = [p for p in parsed if p.is_ley_25630_block]
    assert len(ley_blocks) == 1, f"Esperaba 1 bloque, obtuve {len(ley_blocks)}"


def test_ley_25630_variations():
    """Variantes: 'harina 0000', 'según ley', 'Ley 25630' sin punto."""
    variants = [
        "Harina 0000 enriquecida Ley 25.630, sal.",
        "harina de trigo enriquecida según Ley 25.630, sal.",
        "Harina de trigo 000 enriquecida según ley 25630, sal.",
    ]
    for text in variants:
        parsed = parse_ingredient_list(text)
        ley_blocks = [p for p in parsed if p.is_ley_25630_block]
        assert len(ley_blocks) == 1, f"Falló para: {text!r}"


# ── Aromatizantes / saborizantes ──────────────────────────────────────


def test_flavoring_artificial_with_target():
    text = "azúcar, aromatizante artificial a vainilla, sal."
    parsed = parse_ingredient_list(text)
    flav = [p for p in parsed if p.is_flavoring]
    assert len(flav) == 1
    assert flav[0].flavoring_type == FlavoringType.ARTIFICIAL
    assert flav[0].target_sensory == "vainilla"


def test_flavoring_does_not_capture_real_miel():
    """foto74: 'miel' (real) y 'aromatizante artificial a miel' deben ser distintos."""
    text = "miel, emulsionante: lecitina de soja, aromatizante artificial a miel."
    parsed = parse_ingredient_list(text)
    assert any(p.name == "miel" and not p.is_flavoring for p in parsed)
    assert any(p.is_flavoring and p.target_sensory == "miel" for p in parsed)


def test_flavoring_dulce_de_leche_artificial():
    """foto64: 'aromatizante artificial a dulce de leche' — no debe extraer 'leche'."""
    text = "azúcar, aromatizante artificial a dulce de leche, sal."
    parsed = parse_ingredient_list(text)
    flav = [p for p in parsed if p.is_flavoring]
    assert len(flav) == 1
    assert flav[0].target_sensory == "dulce de leche"
    assert flav[0].flavoring_type == FlavoringType.ARTIFICIAL


def test_flavoring_compound_target_crema_cebolla():
    """foto71: target sensorial compuesto 'crema y cebolla' debe preservarse."""
    text = "papas, aromatizante idéntico al natural a crema y cebolla, sal."
    parsed = parse_ingredient_list(text)
    flav = [p for p in parsed if p.is_flavoring]
    assert len(flav) == 1
    assert "crema" in flav[0].target_sensory
    assert "cebolla" in flav[0].target_sensory


def test_flavoring_natural_qualifier():
    text = "agua, aromatizante natural a humo, sal."
    parsed = parse_ingredient_list(text)
    flav = [p for p in parsed if p.is_flavoring]
    assert len(flav) == 1
    assert flav[0].flavoring_type == FlavoringType.NATURAL


def test_flavoring_identical_to_natural():
    text = "azúcar, aromatizante idéntico al natural a frutilla, agua."
    parsed = parse_ingredient_list(text)
    flav = [p for p in parsed if p.is_flavoring]
    assert len(flav) == 1
    assert flav[0].flavoring_type == FlavoringType.IDENTICAL_TO_NATURAL


# ── Códigos INS ────────────────────────────────────────────────────────


def test_flavoring_comma_qualifier_continuation():
    text = "sal, saborizante natural, id\u00e9ntico al natural y artificial, extracto de levadura."
    parsed = parse_ingredient_list(text)
    flav = [p for p in parsed if p.is_flavoring]
    assert len(flav) == 1
    assert "id\u00e9ntico al natural" in flav[0].name
    assert any(p.name == "extracto de levadura" for p in parsed)


def test_ins_extraction_with_subcode():
    text = "lecitina de soja (INS 322), bicarbonato de sodio (INS 500ii)."
    parsed = parse_ingredient_list(text)
    assert len(parsed) == 2
    assert parsed[0].codex_ins_code == 322
    assert parsed[1].codex_ins_code == 500
    assert parsed[1].codex_ins_subcode == "ii"


def test_ins_with_complex_subcode():
    """foto13: INS 341iii con sufijo trailing 'iii'."""
    text = "fosfato tricálcico (INS 341iii), peróxido de calcio (INS 928)."
    parsed = parse_ingredient_list(text)
    assert parsed[0].codex_ins_code == 341
    assert parsed[0].codex_ins_subcode == "iii"
    assert parsed[1].codex_ins_code == 928


def test_standalone_ins_preserves_display_name():
    text = "sal, INS 551, INS 341iii."
    parsed = parse_ingredient_list(text)
    assert parsed[1].name == "ins 551"
    assert parsed[1].codex_ins_code == 551
    assert parsed[2].name == "ins 341iii"
    assert parsed[2].codex_ins_code == 341
    assert parsed[2].codex_ins_subcode == "iii"


# ── Herencia de función ───────────────────────────────────────────────


def test_function_inheritance_with_ins():
    """'leudantes químicos: X (INS 500ii), Y (INS 503ii)' → ambos heredan."""
    text = "leudantes químicos: bicarbonato de sodio (INS 500ii), bicarbonato de amonio (INS 503ii), emulsionante: lecitina de soja (INS 322)."
    parsed = parse_ingredient_list(text)
    bicarbs = [p for p in parsed if "bicarbonato" in p.name]
    assert len(bicarbs) == 2
    assert all(p.function_tag == "leudante" for p in bicarbs)
    lecit = [p for p in parsed if "lecitina" in p.name]
    assert len(lecit) == 1
    assert lecit[0].function_tag == "emulsionante"


def test_function_inheritance_breaks_on_simple_ingredient():
    """foto64: 'caramelo (INS 150d), sal, ...' — sal NO debe heredar 'colorante'."""
    text = "colorante: caramelo IV (INS 150d), sal, aromatizante artificial a vainilla."
    parsed = parse_ingredient_list(text)
    sal = [p for p in parsed if p.name == "sal"]
    assert len(sal) == 1
    assert sal[0].function_tag != "colorante", f"sal no debería heredar colorante, función: {sal[0].function_tag}"


def test_function_plurals():
    """Plurales: colorantes, edulcorantes, conservantes deben matchear."""
    cases = [
        ("colorantes artificiales: tartrazina (INS 102).", "tartrazina", "colorante"),
        ("edulcorantes no nutritivos: aspartamo (INS 951).", "aspartamo", "edulcorante"),
        ("conservantes: benzoato de sodio (INS 211).", "benzoato de sodio", "conservante"),
    ]
    for text, name, expected_fn in cases:
        parsed = parse_ingredient_list(text)
        match = next((p for p in parsed if name in p.name), None)
        assert match is not None, f"No encontré '{name}' en: {text}"
        assert match.function_tag == expected_fn, f"Esperaba {expected_fn}, obtuve {match.function_tag}"


def test_argentine_abbreviations():
    text = "EMU: lecitina de soja, ACI: ácido cítrico, RAI: bicarbonato."
    parsed = parse_ingredient_list(text)
    fn = {p.name: p.function_tag for p in parsed}
    assert fn.get("lecitina de soja") == "emulsionante"
    assert fn.get("ácido cítrico") == "acidulante"
    assert fn.get("bicarbonato") == "leudante"


# ── Sub-ingredientes ──────────────────────────────────────────────────


def test_sub_ingredients_parsing():
    text = "sazonador (sal, maltodextrina, glutamato monosódico), aceite de girasol."
    parsed = parse_ingredient_list(text)
    sazo = [p for p in parsed if "sazonador" in p.name]
    assert len(sazo) == 1
    assert len(sazo[0].sub_ingredients) >= 2


# ── Declaración legal ────────────────────────────────────────────────


def test_allergen_contains_basic():
    decl = parse_allergen_declaration("CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER SOJA.")
    assert "wheat" in decl.contains
    assert "gluten" in decl.contains
    assert "soy" in decl.may_contain


def test_allergen_implicit_dairy():
    """LECHE en CONTIENE debe expandirse a milk + lactose + dairy."""
    decl = parse_allergen_declaration("CONTIENE LECHE Y DERIVADOS DE LECHE.")
    assert "milk" in decl.contains
    assert "lactose" in decl.contains
    assert "dairy" in decl.contains


def test_allergen_multiple_blocks():
    """foto1: dos CONTIENE separados deben acumularse."""
    text = "CONTIENE: GLUTEN. CONTIENE AVENA. PUEDE CONTENER: TRIGO, SOJA, CEBADA."
    decl = parse_allergen_declaration(text)
    assert "gluten" in decl.contains
    assert "oats" in decl.contains
    assert "wheat" in decl.may_contain
    assert "soy" in decl.may_contain
    assert "barley" in decl.may_contain


def test_allergen_shared_line_cross_contact():
    text = "Elaborado en l\u00edneas que tambi\u00e9n procesan gluten, huevo, soya, leche, man\u00ed."
    decl = parse_allergen_declaration(text)
    assert "gluten" in decl.may_contain
    assert "egg" in decl.may_contain
    assert "soy" in decl.may_contain
    assert "milk" in decl.may_contain
    assert "peanut" in decl.may_contain


def test_allergen_positive_sin_tacc():
    decl = parse_allergen_declaration("Libre de gluten - Sin T.A.C.C.")
    assert "sin_tacc" in decl.positive_claims


def test_allergen_nuts_full_list():
    """foto50: 'CONTIENE ALMENDRAS, CASTAÑAS DE CAJÚ Y NUECES'."""
    decl = parse_allergen_declaration("CONTIENE ALMENDRAS, CASTAÑAS DE CAJÚ Y NUECES. PUEDE CONTENER MANÍ Y SOJA.")
    assert "tree-nut" in decl.contains
    assert "peanut" in decl.may_contain


def test_allergen_sulfites():
    """foto60: CONTIENE SULFITOS."""
    decl = parse_allergen_declaration("CONTIENE SULFITOS.")
    assert "sulfites" in decl.contains


def test_allergen_pescado():
    """foto21: CONTIENE PESCADO."""
    decl = parse_allergen_declaration("CONTIENE PESCADO.")
    assert "fish" in decl.contains


# ── Casos completos por foto (integración parser + declaración) ───────


def test_case_foto22_no_oversplit():
    """La harina enriquecida NO debe contar como múltiples ingredientes (un solo bloque)."""
    case = _by_id("foto22_fideos_huevo")
    parsed = parse_ingredient_list(case["ingredients"])
    # Esperamos exactamente 2 tokens: bloque ley 25.630 + huevo
    assert len(parsed) == 2
    assert parsed[0].is_ley_25630_block
    assert parsed[1].name == "huevo"


def test_case_foto57_salsa_soja_simple():
    """foto57: 5 ingredientes simples, sin paréntesis externos."""
    case = _by_id("foto57_salsa_soja")
    parsed = parse_ingredient_list(case["ingredients"])
    names = [p.name for p in parsed]
    assert "agua" in names
    assert "porotos de soja" in names
    assert "trigo" in names
    assert "sal" in names


def test_dose_paren_does_not_pollute_name():
    """foto28: 'sucralosa (INS 955) (15 mg/100 ml)' — la dosis no debe quedar en el nombre."""
    text = "edulcorantes no nutritivos: sucralosa (INS 955) (15 mg/100 ml), acesulfame K (INS 950) (8 mg/100 ml)."
    parsed = parse_ingredient_list(text)
    sucralosa = next((p for p in parsed if "sucralosa" in p.name), None)
    assert sucralosa is not None
    assert sucralosa.name == "sucralosa", f"name esperado 'sucralosa', obtuve {sucralosa.name!r}"
    assert sucralosa.codex_ins_code == 955
    assert sucralosa.function_tag == "edulcorante"
    assert not sucralosa.sub_ingredients, "la dosis no debe convertirse en sub-ingrediente"

    aces = next((p for p in parsed if "acesulfame" in p.name), None)
    assert aces is not None
    assert aces.name == "acesulfame k"
    assert aces.codex_ins_code == 950


def test_flavoring_paren_targets_list():
    """foto41: 'aromatizantes artificiales (frutilla, limón, naranja, manzana)' debe extraer qualifier y targets."""
    text = "azúcar, aromatizantes artificiales (frutilla, limón, naranja, manzana), agua."
    parsed = parse_ingredient_list(text)
    flav = [p for p in parsed if p.is_flavoring]
    assert len(flav) == 1
    assert flav[0].flavoring_type == FlavoringType.ARTIFICIAL
    target = flav[0].target_sensory or ""
    for fruit in ("frutilla", "limón", "naranja", "manzana"):
        assert fruit in target, f"target sensorial debería contener {fruit!r}, obtuve {target!r}"


def test_paren_function_block_split_into_separate_tokens():
    """foto17: 'colorantes (caramelo, rocú) y acidulante (ácido cítrico)' se separa en tokens taggeados."""
    text = "sal, colorantes (caramelo, rocú) y acidulante (ácido cítrico), agua."
    parsed = parse_ingredient_list(text)
    by_name = {p.name: p for p in parsed}
    assert "caramelo" in by_name and by_name["caramelo"].function_tag == "colorante"
    assert "rocú" in by_name and by_name["rocú"].function_tag == "colorante"
    assert "ácido cítrico" in by_name and by_name["ácido cítrico"].function_tag == "acidulante"
    # No debe quedar el bloque sin separar
    assert not any("y acidulante" in p.name for p in parsed)


def test_paren_function_block_single_no_y():
    """Bloque función-paréntesis solo (sin 'y'): 'antioxidante (lecitina de soja)' canoniza a colon-form."""
    text = "maíz, azúcar, antioxidante (lecitina de soja)."
    parsed = parse_ingredient_list(text)
    lecit = next((p for p in parsed if "lecitina" in p.name), None)
    assert lecit is not None
    assert lecit.function_tag == "antioxidante"


def test_y_split_does_not_break_real_conjunctions():
    """'palma y canola' y 'crema y cebolla' NO deben dividirse (no son función + función)."""
    parsed = parse_ingredient_list("aceite vegetal de palma y canola, sal.")
    # Esperamos 2 tokens: el aceite (sin partir) y sal.
    assert any(p.name == "aceite vegetal de palma y canola" for p in parsed), \
        f"no se preservó 'palma y canola': {[p.name for p in parsed]}"

    parsed2 = parse_ingredient_list("aromatizante a crema y cebolla, sal.")
    flav = [p for p in parsed2 if p.is_flavoring]
    assert len(flav) == 1 and "crema" in (flav[0].target_sensory or "") and "cebolla" in (flav[0].target_sensory or "")


def test_case_foto60_sulfitos_full():
    """foto60: ingredientes simples + INS + declaración legal."""
    case = _by_id("foto60_jugo_limon_sulfitos")
    parsed = parse_ingredient_list(case["ingredients"])
    decl = parse_allergen_declaration(case["allergens"])
    metabis = [p for p in parsed if "metabisulfito" in p.name]
    assert len(metabis) == 1
    assert metabis[0].codex_ins_code == 223
    assert "sulfites" in decl.contains


# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    run_all()

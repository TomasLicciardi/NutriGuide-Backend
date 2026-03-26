# tests/test_classification.py
"""
Suite de tests con 42 ejemplos reales de etiquetas argentinas.

Cada test case define:
  - ingredients: lista de ingredientes tal como los extraería el OCR
  - allergens: texto de alérgenos tal como aparece en la etiqueta
  - expected: resultado esperado para cada restricción (True=apto, False=no apto)

Ejecutar: python -m pytest tests/test_classification.py -v
O sin pytest: python tests/test_classification.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.allergen_parser import parse_allergen_text
from app.services.deterministic_classifier import classifier

# ═══════════════════════════════════════════════════════════════════════════════
# Datos de test: 24 etiquetas reales argentinas
# ═══════════════════════════════════════════════════════════════════════════════

TEST_CASES = [
    {
        "id": "foto_01",
        "desc": "Avena arrollada",
        "ingredients": ["avena arrollada"],
        "allergens": "CONTIENE: GLUTEN. CONTIENE AVENA. PUEDE CONTENER: TRIGO, SOJA, CEBADA, CENTENO Y MANÍ.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": False,
        },
    },
    {
        "id": "foto_02",
        "desc": "Cereales (maíz, extracto de malta, lecitina de soja)",
        "ingredients": ["maíz", "azúcar", "sal", "extracto de malta", "lecitina de soja"],
        "allergens": "CONTIENE SULFITOS Y DERIVADOS DE SOJA Y CEBADA. PUEDE CONTENER AVENA, ALMENDRA Y DERIVADOS DE TRIGO Y CENTENO.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": False,
        },
    },
    {
        "id": "foto_03",
        "desc": "Galletitas (harina de trigo, oleomargarina)",
        "ingredients": [
            "azúcar", "harina de trigo enriquecida", "oleomargarina",
            "almidón de maíz", "aceite de girasol", "sal",
            "lecitina de soja", "bicarbonato de sodio",
            "sabor a vainilla", "ácido cítrico",
        ],
        "allergens": "CONTIENE DERIVADO DE TRIGO Y DE SOJA. PUEDE CONTENER LECHE, MANÍ Y HUEVO.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": False,
        },
    },
    {
        "id": "foto_04",
        "desc": "Snack (harina de maíz, sazonador)",
        "ingredients": [
            "harina de maíz", "aceite vegetal de palma y canola", "TBHQ",
            "sal", "maltodextrina de maíz", "ácido cítrico", "azúcar",
            "glutamato monosódico", "aceite de soya", "cebolla en polvo",
            "bicarbonato de sodio", "azul brillante FCF",
            "saborizante natural", "hidrolizado de proteína de maíz",
            "extracto de levadura", "inosinato disódico", "guanilato disódico",
        ],
        "allergens": "Elaborado en líneas que también procesan gluten, huevo, soya, leche, maní.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": False,
        },
    },
    {
        "id": "foto_05",
        "desc": "Ketchup/salsa de tomate",
        "ingredients": [
            "agua", "concentrado doble de tomate", "azúcar", "vinagre",
            "sal", "cebolla", "ajo", "ácido láctico",
            "glutamato de sodio", "goma xántica", "caramelo IV",
            "aromatizante", "sorbato de potasio",
        ],
        "allergens": "",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_06",
        "desc": "Harina de trigo enriquecida con vitaminas y cúrcuma",
        "ingredients": [
            "harina de trigo enriquecida ley 25.630",
            "fumarato ferroso", "óxido de zinc",
            "vitamina B2", "vitamina B6", "vitamina B1",
            "vitamina A", "vitamina B9", "vitamina D", "vitamina B12",
            "cúrcuma",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_07",
        "desc": "Almidón de maíz",
        "ingredients": ["almidón de maíz"],
        "allergens": "CONTIENE SULFITOS.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_08",
        "desc": "Harina enriquecida (idéntica a foto 6)",
        "ingredients": [
            "harina de trigo enriquecida ley 25.630",
            "fumarato ferroso", "óxido de zinc",
            "vitamina B2", "vitamina B6", "vitamina B1",
            "vitamina A", "vitamina B9", "vitamina D", "vitamina B12",
            "cúrcuma",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_09",
        "desc": "Harina de trigo enriquecida Ley 25.630 (con detalle de mg/kg)",
        "ingredients": ["harina de trigo enriquecida según Ley 25.630"],
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_10",
        "desc": "Mayonesa/aderezo (con huevo líquido)",
        "ingredients": [
            "agua", "aceite de girasol", "azúcar", "extracto de tomate",
            "almidón modificado", "sal", "vinagre de alcohol",
            "huevo líquido", "jugo concentrado de limón",
            "goma xántica", "ácido fosfórico", "ácido sórbico",
            "aromatizantes", "EDTA disódico cálcico", "BHA", "BHT",
        ],
        "allergens": "CONTIENE HUEVO.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_11",
        "desc": "Salsa de tomate (con maltodextrina)",
        "ingredients": [
            "agua", "concentrado doble de tomate", "azúcar",
            "vinagre de alcohol", "maltodextrina", "sal",
            "cebolla en polvo", "ajo en polvo", "especias",
            "goma xántica", "ácido cítrico", "sorbato de potasio",
            "aromatizantes",
        ],
        "allergens": "",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_12",
        "desc": "Aderezo/mostaza (con nuez moscada)",
        "ingredients": [
            "agua", "vinagre de alcohol", "vinagre de vino",
            "almidón modificado", "mostaza blanca", "cúrcuma",
            "canela", "nuez moscada", "semilla de apio",
            "ají molido", "comino", "clavo de olor", "pimienta negra",
            "tomillo", "orégano", "jengibre", "laurel",
            "azúcar", "sal", "aceite de girasol", "cebolla", "ajo",
            "goma xántica", "ácido sórbico", "caramelo IV",
            "clorofila", "aromatizante", "EDTA disódico cálcico",
            "BHA", "BHT",
        ],
        "allergens": "PUEDE CONTENER TRIGO, AVENA, CEBADA Y CENTENO.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_13",
        "desc": "Harina 0000 con mejoradores",
        "ingredients": [
            "harina 0000 enriquecida Ley 25.630",
            "INS 341iii", "INS 928",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER DERIVADOS DE SOJA.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_14",
        "desc": "Cacao en polvo (suero de leche, lecitina de soja)",
        "ingredients": [
            "azúcar", "cacao en polvo", "suero de leche",
            "vitaminas y minerales", "sal", "canela en polvo",
            "lecitina de soja", "vainilla",
        ],
        "allergens": "CONTIENE DERIVADOS DE LECHE Y DE SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_15",
        "desc": "Sal con yodo (Sin TACC)",
        "ingredients": [
            "sal", "cloruro de sodio", "yodato de potasio",
            "INS 551", "INS 536",
        ],
        "allergens": "Libre de gluten - Sin T.A.C.C.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_16",
        "desc": "Tapas para empanadas (harina de trigo, códigos INS)",
        "ingredients": [
            "harina de trigo 000 enriquecida según ley 25630",
            "aceite de girasol alto oleico", "vinagre de alcohol",
            "sal", "cloruro de potasio",
            "INS 422", "INS 471", "INS 412", "INS 282", "INS 330", "INS 920",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO, LECHE, DERIVADOS DE SOJA, DE AVENA Y DE CEBADA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_17",
        "desc": "Caldo (con carne bovina deshidratada)",
        "ingredients": [
            "sal", "grasa vegetal", "almidón de maíz no modificado",
            "azúcar", "aceite de palma", "BHA", "BHT",
            "pimienta roja", "perejil", "laurel en polvo", "ajo en polvo",
            "carne bovina deshidratada",
            "glutamato monosódico", "inosinato de sodio",
            "aromatizantes", "caramelo", "rocú", "ácido cítrico",
        ],
        "allergens": "CONTIENE DERIVADOS DE SOJA. PUEDE CONTENER CEBADA.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_18",
        "desc": "Sopa instantánea (caseinato de sodio)",
        "ingredients": [
            "almidón de papa", "zapallo", "cebolla", "perejil",
            "azúcar", "maltodextrina", "jarabe de glucosa", "sal",
            "aceites vegetales", "romero", "caseinato de sodio",
            "pimienta negra", "glutamato monosódico",
            "inosinato disódico", "guanilato disódico",
            "goma xántica", "aromatizantes naturales", "annatto",
        ],
        "allergens": "CONTIENE DERIVADO DE LECHE. PUEDE CONTENER PESCADO Y DERIVADOS DE SOJA Y DE TRIGO.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_19",
        "desc": "Tomate pelado en lata",
        "ingredients": ["tomate pelado", "jugo de tomates", "ácido cítrico"],
        "allergens": "",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_20",
        "desc": "Puré de tomate",
        "ingredients": ["tomate", "ácido cítrico"],
        "allergens": "",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_21",
        "desc": "Atún en lata",
        "ingredients": ["atún", "agua", "sal"],
        "allergens": "CONTIENE PESCADO.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_22",
        "desc": "Fideos al huevo",
        "ingredients": [
            "harina de trigo tipo 000 enriquecida Ley 25.630",
            "huevo",
        ],
        "allergens": "CONTIENE HUEVO Y DERIVADOS DE TRIGO. PUEDE CONTENER SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_23",
        "desc": "Harina enriquecida (igual a foto 9)",
        "ingredients": ["harina de trigo enriquecida según Ley 25.630"],
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_24",
        "desc": "Fideos de sémola",
        "ingredients": [
            "harina de trigo enriquecida según Ley 25.630",
            "sémola de trigo candeal", "agua",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },

    # ══════════════════════════════════════════════════════════════════════
    # Fotos 27-34: Segunda tanda de etiquetas reales
    # ══════════════════════════════════════════════════════════════════════

    {
        "id": "foto_27",
        "desc": "Galletitas dulces (grasa bovina, JMAF, cacao, INS varios)",
        "ingredients": [
            "harina de trigo enriquecida", "azúcar", "grasa bovina refinada",
            "jarabe de maíz de alta fructosa", "cacao alcalinizado", "sal",
            "bicarbonato de sodio (INS 500ii)", "bicarbonato de amonio (INS 503ii)",
            "lecitina de soja (INS 322)", "aromatizante artificial a vainilla",
            "caramelo IV (INS 150d)",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO Y DE SOJA. PUEDE CONTENER LECHE, MANÍ Y AVENA.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": False,
        },
    },
    {
        "id": "foto_28",
        "desc": "Jugo de naranja (colorantes sintéticos, edulcorantes)",
        "ingredients": [
            "agua", "jugo concentrado de naranja", "azúcar",
            "ácido cítrico (INS 330)", "benzoato de sodio (INS 211)",
            "sorbato de potasio (INS 202)", "sucralosa (INS 955)",
            "acesulfame K (INS 950)",
            "aromatizante idéntico al natural de naranja",
            "amarillo ocaso FCF (INS 110)", "tartrazina (INS 102)",
        ],
        "allergens": "CONTIENE TARTRAZINA.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_29",
        "desc": "Postre de chocolate (leche, suero de queso, carragenina)",
        "ingredients": [
            "leche entera", "suero de queso en polvo", "azúcar",
            "cacao en polvo", "almidón modificado de maíz",
            "carragenina (INS 407)", "goma guar (INS 412)",
            "aromatizante artificial a chocolate",
        ],
        "allergens": "CONTIENE LECHE Y DERIVADOS DE LECHE. PUEDE CONTENER SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_30",
        "desc": "Snack de maíz sabor queso (suero, glutamato, annatto)",
        "ingredients": [
            "harina de maíz", "aceite de girasol", "sal",
            "suero de queso en polvo", "maltodextrina",
            "glutamato monosódico (INS 621)", "inosinato disódico (INS 631)",
            "aromatizante idéntico al natural sabor queso",
            "annatto (INS 160b)", "dióxido de silicio (INS 551)",
        ],
        "allergens": "CONTIENE DERIVADOS DE LECHE. PUEDE CONTENER DERIVADOS DE TRIGO Y SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_31",
        "desc": "Pan lactal (harina de trigo, propionato, ácido ascórbico)",
        "ingredients": [
            "harina de trigo enriquecida según Ley 25.630",
            "agua", "levadura", "azúcar", "sal",
            "aceite de girasol alto oleico",
            "propionato de calcio (INS 282)",
            "ácido ascórbico (INS 300)",
            "estearoil lactilato de sodio (INS 481i)",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER AVENA, CEBADA Y CENTENO.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_32",
        "desc": "Mermelada de frutilla (carmín INS 120, edulcorantes, pectina)",
        "ingredients": [
            "frutilla", "agua", "jarabe de glucosa",
            "pectina (INS 440)", "goma garrofín (INS 410)",
            "ácido cítrico (INS 330)", "sorbato de potasio (INS 202)",
            "ciclamato de sodio (INS 952)", "glicósidos de esteviol (INS 960)",
            "carmín (INS 120)",
            "aromatizante idéntico al natural a frutilla",
        ],
        "allergens": "PUEDE CONTENER DERIVADOS DE LECHE.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_33",
        "desc": "Salchicha (carne bovina y aviar, primer jugo, carmín)",
        "ingredients": [
            "carne bovina", "carne aviar", "agua", "primer jugo bovino",
            "almidón de maíz", "sal", "proteína de soja", "especias",
            "polifosfatos (INS 452)", "eritorbato de sodio (INS 316)",
            "nitrito de sodio (INS 250)", "nitrato de sodio (INS 251)",
            "carmín (INS 120)", "aromatizante humo",
        ],
        "allergens": "CONTIENE DERIVADOS DE SOJA.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_34",
        "desc": "Chipá / pan de queso (fécula de mandioca, queso, huevo, SIN TACC)",
        "ingredients": [
            "fécula de mandioca", "agua", "queso sardo",
            "queso mar del plata", "grasa bovina refinada",
            "huevo entero pasteurizado", "leche entera en polvo",
            "sal", "pirofosfato ácido de sodio", "bicarbonato de sodio",
        ],
        "allergens": "CONTIENE HUEVO Y DERIVADOS DE LECHE. LIBRE DE GLUTEN - SIN T.A.C.C.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": True,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },

    # ══════════════════════════════════════════════════════════════════════
    # Fotos 35-44: Tercera tanda de etiquetas reales
    # ══════════════════════════════════════════════════════════════════════

    {
        "id": "foto_35",
        "desc": "Crackers/galletitas (extracto de malta, lecitina de soja)",
        "ingredients": [
            "harina de trigo enriquecida Ley 25.630",
            "aceite de girasol de alto oleico", "sal",
            "extracto de malta", "levadura",
            "bicarbonato de sodio (INS 500ii)",
            "lecitina de soja (INS 322)",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO, CEBADA Y SOJA. PUEDE CONTENER AVENA Y CENTENO.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_36",
        "desc": "Jugo en polvo (aspartamo, dióxido de titanio, colorantes)",
        "ingredients": [
            "azúcar", "maltodextrina", "jugo de manzana deshidratado",
            "ácido cítrico (INS 330)", "aspartamo (INS 951)",
            "acesulfame K (INS 950)", "fosfato tricálcico (INS 341iii)",
            "aromatizante idéntico al natural a manzana",
            "dióxido de titanio (INS 171)", "tartrazina (INS 102)",
            "azul brillante FCF (INS 133)",
        ],
        "allergens": "CONTIENE TARTRAZINA. FENILCETONÚRICOS: CONTIENE FENILALANINA.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_37",
        "desc": "Mayonesa/aderezo (yema de huevo, BHA, BHT, EDTA)",
        "ingredients": [
            "agua", "aceite de girasol", "vinagre de alcohol",
            "almidón modificado de maíz", "azúcar",
            "yema de huevo pasteurizada", "sal",
            "jugo concentrado de limón",
            "goma xántica (INS 415)", "ácido sórbico (INS 200)",
            "aromatizante natural a mostaza",
            "EDTA disódico cálcico (INS 385)",
            "BHA (INS 320)", "BHT (INS 321)",
        ],
        "allergens": "CONTIENE HUEVO. PUEDE CONTENER SOJA Y DERIVADOS DE TRIGO.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_38",
        "desc": "Yogur con durazno (leche, cultivos lácticos, gelatina)",
        "ingredients": [
            "leche entera pasteurizada", "azúcar",
            "pulpa de durazno", "almidón modificado",
            "aromatizante natural a durazno",
            "sorbato de potasio", "annatto",
            "leche en polvo descremada",
            "cultivos lácticos", "gelatina",
        ],
        "allergens": "CONTIENE LECHE.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": True,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_39",
        "desc": "Pan dulce (huevo, pasas, fruta escurrida, tartrazina)",
        "ingredients": [
            "harina de trigo 0000 enriquecida según Ley 25.630",
            "azúcar", "agua", "aceite de palma",
            "huevo líquido pasteurizado", "pasas de uva",
            "fruta escurrida", "levadura", "jarabe de glucosa", "sal",
            "mono y diglicéridos de ácidos grasos (INS 471)",
            "estearoil lactilato de sodio (INS 481i)",
            "propionato de calcio (INS 282)",
            "aromatizantes artificiales a pan dulce y vainilla",
            "tartrazina (INS 102)",
        ],
        "allergens": "CONTIENE HUEVO, DERIVADOS DE TRIGO Y TARTRAZINA. PUEDE CONTENER ALMENDRAS, MANÍ Y NUECES.",
        "expected": {
            "vegano": False,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": False,
        },
    },
    {
        "id": "foto_40",
        "desc": "Salsa de soja (poroto de soja, trigo, ácido láctico)",
        "ingredients": [
            "agua", "poroto de soja", "trigo", "sal",
            "caramelo III (INS 150c)",
            "glutamato monosódico (INS 621)",
            "sorbato de potasio (INS 202)",
            "ácido láctico (INS 270)",
        ],
        "allergens": "CONTIENE SOJA Y TRIGO.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_41",
        "desc": "Gomitas (gelatina, cera de abejas INS 901, colorantes)",
        "ingredients": [
            "jarabe de glucosa", "azúcar", "agua", "gelatina",
            "ácido cítrico (INS 330)", "ácido láctico (INS 270)",
            "aromatizantes artificiales",
            "aceite vegetal",
            "cera de abejas (INS 901)", "cera de carnauba (INS 903)",
            "rojo allura AC (INS 129)", "amarillo ocaso (INS 110)",
            "tartrazina (INS 102)", "azul brillante FCF (INS 133)",
        ],
        "allergens": "CONTIENE TARTRAZINA. PUEDE CONTENER DERIVADOS DE SOJA Y LECHE.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": True,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_42",
        "desc": "Cereales fortificados (extracto de malta, vitaminas, lecitina de soja)",
        "ingredients": [
            "harina de maíz", "azúcar", "extracto de malta", "sal",
            "vitaminas y minerales", "vitamina C", "niacina",
            "hierro", "zinc", "vitamina B6", "vitamina B2",
            "vitamina B1", "ácido fólico", "vitamina B12",
            "lecitina de soja (INS 322)",
        ],
        "allergens": "CONTIENE DERIVADOS DE CEBADA Y DE SOJA. PUEDE CONTENER AVENA, TRIGO Y CENTENO.",
        "expected": {
            "vegano": True,
            "vegetariano": True,
            "sin_gluten": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
        },
    },
    {
        "id": "foto_43",
        "desc": "Alfajor (dulce de leche, grasa bovina, baño de repostería)",
        "ingredients": [
            "dulce de leche", "leche entera", "azúcar",
            "jarabe de glucosa", "bicarbonato de sodio",
            "sorbato de potasio",
            "aceite vegetal fraccionado",
            "leche descremada en polvo", "suero de queso en polvo",
            "lecitina de soja", "aromatizante artificial a vainilla",
            "harina de trigo enriquecida Ley 25.630",
            "grasa bovina", "cacao en polvo", "sal",
            "bicarbonato de amonio", "propionato de calcio",
        ],
        "allergens": "CONTIENE LECHE Y DERIVADOS DE TRIGO Y SOJA. PUEDE CONTENER MANÍ.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": False,
        },
    },
    {
        "id": "foto_44",
        "desc": "Sopa instantánea sabor pollo (carne de pollo, cúrcuma, caramelo)",
        "ingredients": [
            "fideos", "harina de trigo enriquecida ley 25.630",
            "agua", "cúrcuma", "sal", "almidón de maíz", "azúcar",
            "aceite vegetal de palma",
            "glutamato monosódico (INS 621)",
            "inosinato disódico (INS 631)",
            "carne de pollo deshidratada",
            "perejil", "cebolla", "apio",
            "aromatizante idéntico al natural a pollo",
            "caramelo IV (INS 150d)",
        ],
        "allergens": "CONTIENE DERIVADOS DE TRIGO Y APIO. PUEDE CONTENER HUEVO, SOJA Y DERIVADOS DE LECHE.",
        "expected": {
            "vegano": False,
            "vegetariano": False,
            "sin_gluten": False,
            "sin_lactosa": False,
            "sin_frutos_secos": True,
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Runner de tests
# ═══════════════════════════════════════════════════════════════════════════════

def run_single_test(case: dict) -> dict:
    """Ejecuta un test case y retorna el resultado."""
    allergen_result = parse_allergen_text(case["allergens"])
    classification = classifier.classify_product(case["ingredients"], allergen_result)

    results = {}
    errors = []

    for restriction in case["expected"]:
        actual = classification.restrictions[restriction]["apto"]
        expected = case["expected"][restriction]
        results[restriction] = {"expected": expected, "actual": actual, "ok": actual == expected}

        if actual != expected:
            motivo = classification.restrictions[restriction].get("motivo", "N/A")
            errors.append(
                f"  {restriction}: esperado={'APTO' if expected else 'NO APTO'}, "
                f"obtenido={'APTO' if actual else 'NO APTO'} (motivo: {motivo})"
            )

    return {
        "id": case["id"],
        "desc": case["desc"],
        "passed": len(errors) == 0,
        "results": results,
        "errors": errors,
        "classification": classification,
    }


def run_all_tests():
    """Ejecuta todos los test cases e imprime resultados."""
    print(f"\n{'=' * 70}")
    print(f" NutriGuide — Test Suite de Clasificacion ({len(TEST_CASES)} etiquetas)")
    print(f"{'=' * 70}\n")

    passed = 0
    failed = 0
    total_restrictions = 0
    correct_restrictions = 0

    for case in TEST_CASES:
        result = run_single_test(case)
        status = "PASS" if result["passed"] else "FAIL"
        icon = "[OK]" if result["passed"] else "[!!]"

        print(f"{icon} {result['id']}: {result['desc']} — {status}")

        if result["passed"]:
            passed += 1
        else:
            failed += 1
            for error in result["errors"]:
                print(error)

        for r_data in result["results"].values():
            total_restrictions += 1
            if r_data["ok"]:
                correct_restrictions += 1

    print(f"\n{'=' * 70}")
    print(f" RESULTADOS: {passed}/{len(TEST_CASES)} tests pasaron")
    print(f" PRECISION: {correct_restrictions}/{total_restrictions} restricciones correctas "
          f"({100 * correct_restrictions / total_restrictions:.1f}%)")

    if failed > 0:
        print(f" FALLARON: {failed} tests")
    else:
        print(f" TODOS LOS TESTS PASARON")
    print(f"{'=' * 70}\n")

    return failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest compatibility
# ═══════════════════════════════════════════════════════════════════════════════

try:
    import pytest

    @pytest.mark.parametrize("case", TEST_CASES, ids=[c["id"] for c in TEST_CASES])
    def test_classification(case):
        result = run_single_test(case)
        if not result["passed"]:
            error_msg = f"{case['id']} ({case['desc']}):\n" + "\n".join(result["errors"])
            pytest.fail(error_msg)

except ImportError:
    pass


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

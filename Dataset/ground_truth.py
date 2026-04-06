"""
Ground Truth — Dataset de validación NutriGuide.

44 productos argentinos reales con ingredientes transcritos manualmente,
texto de alérgenos, y clasificación correcta para las 4 restricciones.

Clasificación manual siguiendo la política del sistema:
  - CONTIENE X → NO APTO (confirmado)
  - PUEDE CONTENER X → NO APTO (contaminación cruzada, precaución médica)
  - Ingrediente que contiene X → NO APTO (por composición)
  - Sin evidencia de X → APTO

Fotos 25 y 26 marcadas como "mala_calidad" = el sistema debería rechazarlas.
"""

GROUND_TRUTH = {
    # ══════════════════════════════════════════════════════════════════
    # FOTOS EN EL DATASET (1-26)
    # ══════════════════════════════════════════════════════════════════

    "foto1": {
        "nombre": "Avena arrollada",
        "archivo": "foto1.jpeg",
        "ingredientes": ["avena arrollada"],
        "alergenos": "CONTIENE: GLUTEN. CONTIENE AVENA. PUEDE CONTENER: TRIGO, SOJA, CEBADA, CENTENO Y MANÍ.",
        "expected": {
            "sin_tacc": False,      # Avena = TACC, alérgenos confirman GLUTEN
            "sin_lactosa": True,
            "sin_frutos_secos": False,  # PUEDE CONTENER MANÍ
            "vegano": True,
        },
        "motivos": {
            "sin_tacc": "Contiene avena + alérgenos: GLUTEN",
            "sin_frutos_secos": "Puede contener maní",
        },
    },

    "foto2": {
        "nombre": "Cereales de maíz (tipo Zucaritas)",
        "archivo": "foto2.jpeg",
        "ingredientes": [
            "maíz", "azúcar", "sal", "extracto de malta",
            "antioxidante: lecitina de soja",
        ],
        "alergenos": "CONTIENE SULFITOS Y DERIVADOS DE SOJA Y CEBADA. PUEDE CONTENER AVENA, ALMENDRA Y DERIVADOS DE TRIGO Y CENTENO.",
        "expected": {
            "sin_tacc": False,      # Extracto de malta = cebada, alérgenos confirman CEBADA/TRIGO
            "sin_lactosa": True,
            "sin_frutos_secos": False,  # PUEDE CONTENER ALMENDRA
            "vegano": True,
        },
        "motivos": {
            "sin_tacc": "Extracto de malta (cebada) + alérgenos",
            "sin_frutos_secos": "Puede contener almendra",
        },
    },

    "foto3": {
        "nombre": "Galletitas (tipo Criollitas)",
        "archivo": "foto3.jpeg",
        "ingredientes": [
            "azúcar", "harina de trigo enriquecida", "oleomargarina",
            "almidón de maíz", "aceite de girasol", "sal",
            "lecitina de soja", "bicarbonato de sodio",
            "saborizante artificial a vainilla", "ácido cítrico",
        ],
        "alergenos": "CONTIENE DERIVADO DE TRIGO Y DE SOJA. PUEDE CONTENER LECHE, MANÍ Y HUEVO.",
        "expected": {
            "sin_tacc": False,      # Harina de trigo
            "sin_lactosa": False,   # PUEDE CONTENER LECHE
            "sin_frutos_secos": False,  # PUEDE CONTENER MANÍ
            "vegano": False,        # PUEDE CONTENER LECHE y HUEVO
        },
        "motivos": {
            "sin_tacc": "Harina de trigo",
            "sin_lactosa": "Puede contener leche",
            "sin_frutos_secos": "Puede contener maní",
            "vegano": "Puede contener leche y huevo",
        },
    },

    "foto4": {
        "nombre": "Snack de maíz (tipo Doritos)",
        "archivo": "foto4.jpeg",
        "ingredientes": [
            "harina de maíz", "aceite vegetal de palma y canola", "TBHQ",
            "sal", "maltodextrina de maíz", "ácido cítrico", "azúcar",
            "glutamato monosódico", "aceite de soya", "cebolla en polvo",
            "bicarbonato de sodio", "azul brillante FCF",
            "saborizante natural, idéntico al natural y artificial",
            "hidrolizado de proteína de maíz", "extracto de levadura",
            "inosinato disódico", "guanilato disódico",
        ],
        "alergenos": "Elaborado en líneas que también procesan gluten, huevo, soya, leche, maní.",
        "expected": {
            "sin_tacc": False,      # Elaborado en líneas con gluten
            "sin_lactosa": False,   # Elaborado en líneas con leche
            "sin_frutos_secos": False,  # Elaborado en líneas con maní
            "vegano": False,        # Elaborado en líneas con huevo y leche
        },
        "motivos": {
            "sin_tacc": "Elaborado en líneas con gluten",
            "sin_lactosa": "Elaborado en líneas con leche",
            "sin_frutos_secos": "Elaborado en líneas con maní",
            "vegano": "Elaborado en líneas con huevo y leche",
        },
    },

    "foto5": {
        "nombre": "Salsa de tomate (tipo ketchup)",
        "archivo": "foto5.jpeg",
        "ingredientes": [
            "agua", "concentrado doble de tomate", "azúcar", "vinagre",
            "sal", "cebolla", "ajo", "ácido láctico",
            "glutamato de sodio", "goma xántica", "caramelo IV",
            "aromatizante", "sorbato de potasio",
        ],
        "alergenos": "",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto6": {
        "nombre": "Harina de trigo vitaminizada",
        "archivo": "foto6.jpeg",
        "ingredientes": [
            "harina de trigo enriquecida", "fumarato ferroso",
            "óxido de zinc", "vitamina B2", "vitamina B6",
            "vitamina B1", "vitamina A", "vitamina B9",
            "vitamina D", "vitamina B12", "cúrcuma",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
        "expected": {
            "sin_tacc": False,      # Harina de trigo
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,        # PUEDE CONTENER HUEVO
        },
        "motivos": {
            "sin_tacc": "Harina de trigo",
            "vegano": "Puede contener huevo",
        },
    },

    "foto7": {
        "nombre": "Almidón de maíz (Maizena)",
        "archivo": "foto7.jpeg",
        "ingredientes": ["almidón de maíz"],
        "alergenos": "CONTIENE SULFITOS.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto8": {
        "nombre": "Harina vitaminizada (idéntica a foto 6)",
        "archivo": "foto8.jpeg",
        "ingredientes": [
            "harina de trigo enriquecida", "fumarato ferroso",
            "óxido de zinc", "vitamina B2", "vitamina B6",
            "vitamina B1", "vitamina A", "vitamina B9",
            "vitamina D", "vitamina B12", "cúrcuma",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,
        },
    },

    "foto9": {
        "nombre": "Harina de trigo 000",
        "archivo": "foto9.jpeg",
        "ingredientes": ["harina de trigo enriquecida"],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,
        },
    },

    "foto10": {
        "nombre": "Mayonesa/aderezo",
        "archivo": "foto10.jpeg",
        "ingredientes": [
            "agua", "aceite de girasol", "azúcar", "extracto de tomate",
            "almidón modificado", "sal", "vinagre de alcohol",
            "huevo líquido", "jugo concentrado de limón",
            "goma xántica", "ácido fosfórico", "ácido sórbico",
            "aromatizantes", "EDTA disódico cálcico", "BHA", "BHT",
        ],
        "alergenos": "CONTIENE HUEVO.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,        # Huevo
        },
        "motivos": {
            "vegano": "Contiene huevo",
        },
    },

    "foto11": {
        "nombre": "Ketchup",
        "archivo": "foto11.jpeg",
        "ingredientes": [
            "agua", "concentrado doble de tomate", "azúcar",
            "vinagre de alcohol", "maltodextrina", "sal",
            "cebolla en polvo", "ajo en polvo", "especias",
            "goma xántica", "ácido cítrico", "sorbato de potasio",
            "aromatizantes naturales",
        ],
        "alergenos": "",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto12": {
        "nombre": "Mostaza",
        "archivo": "foto12.jpeg",
        "ingredientes": [
            "agua", "vinagre de alcohol", "vinagre de vino",
            "almidón modificado", "mostaza blanca", "cúrcuma",
            "canela", "nuez moscada", "semilla de apio",
            "ají molido", "comino", "clavo de olor",
            "pimienta negra", "tomillo", "orégano", "jengibre",
            "laurel", "azúcar", "sal", "aceite de girasol",
            "cebolla", "ajo", "goma xántica", "ácido sórbico",
            "caramelo IV", "clorofila", "aromatizante idéntico al natural",
            "EDTA disódico cálcico", "BHA", "BHT",
        ],
        "alergenos": "PUEDE CONTENER TRIGO, AVENA, CEBADA Y CENTENO.",
        "expected": {
            "sin_tacc": False,      # PUEDE CONTENER TRIGO/AVENA/CEBADA/CENTENO
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
        "motivos": {
            "sin_tacc": "Puede contener trigo, avena, cebada, centeno",
        },
    },

    "foto13": {
        "nombre": "Harina 0000",
        "archivo": "foto13.jpeg",
        "ingredientes": [
            "harina 0000 enriquecida", "harina de trigo",
            "sulfato ferroso", "nicotinamida", "tiamina",
            "ácido fólico", "riboflavina", "INS 341iii", "INS 928",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER DERIVADOS DE SOJA.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto14": {
        "nombre": "Chocolatada en polvo (Nesquik)",
        "archivo": "foto14.jpeg",
        "ingredientes": [
            "azúcar", "cacao en polvo", "suero de leche",
            "vitamina C", "vitamina D", "vitamina B1",
            "pirofosfato férrico", "sulfato de zinc",
            "sal", "canela en polvo", "lecitina de soja", "vainilla",
        ],
        "alergenos": "CONTIENE DERIVADOS DE LECHE Y DE SOJA.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": False,   # Suero de leche
            "sin_frutos_secos": True,
            "vegano": False,        # Suero de leche
        },
    },

    "foto15": {
        "nombre": "Sal (Celusal)",
        "archivo": "foto15.jpeg",
        "ingredientes": [
            "sal", "cloruro de sodio", "yodato de potasio",
            "INS 551", "INS 536",
        ],
        "alergenos": "Libre de gluten - Sin T.A.C.C.",
        "expected": {
            "sin_tacc": True,       # Declaración positiva: SIN TACC
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto16": {
        "nombre": "Tapas de empanadas",
        "archivo": "foto16.jpeg",
        "ingredientes": [
            "harina de trigo 000 enriquecida", "aceite de girasol alto oleico",
            "vinagre de alcohol", "sal", "cloruro de potasio",
            "INS 422", "INS 471", "INS 412", "INS 282", "INS 330", "INS 920",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO, LECHE, DERIVADOS DE SOJA, DE AVENA Y DE CEBADA.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": False,   # PUEDE CONTENER LECHE
            "sin_frutos_secos": True,
            "vegano": False,        # PUEDE CONTENER HUEVO y LECHE
        },
    },

    "foto17": {
        "nombre": "Caldo en cubo (Knorr)",
        "archivo": "foto17.jpeg",
        "ingredientes": [
            "sal", "grasa vegetal", "almidón de maíz", "azúcar",
            "aceite de palma", "BHA", "BHT", "pimienta roja",
            "perejil", "laurel en polvo", "ajo en polvo",
            "carne bovina deshidratada", "glutamato monosódico",
            "inosinato de sodio", "aromatizantes", "caramelo", "rocú",
            "ácido cítrico",
        ],
        "alergenos": "CONTIENE DERIVADOS DE SOJA. PUEDE CONTENER CEBADA.",
        "expected": {
            "sin_tacc": False,      # PUEDE CONTENER CEBADA
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,        # Carne bovina deshidratada
        },
    },

    "foto18": {
        "nombre": "Sopa instantánea (Knorr)",
        "archivo": "foto18.jpeg",
        "ingredientes": [
            "almidón de papa", "zapallo", "cebolla", "perejil",
            "azúcar", "maltodextrina", "jarabe de glucosa", "sal",
            "aceites vegetales", "romero", "caseinato de sodio",
            "pimienta negra", "glutamato monosódico",
            "inosinato disódico", "guanilato disódico",
            "goma xántica", "aromatizantes naturales", "annatto",
        ],
        "alergenos": "CONTIENE DERIVADO DE LECHE. PUEDE CONTENER PESCADO Y DERIVADOS DE SOJA Y DE TRIGO.",
        "expected": {
            "sin_tacc": False,      # PUEDE CONTENER TRIGO
            "sin_lactosa": False,   # Caseinato de sodio = derivado de leche
            "sin_frutos_secos": True,
            "vegano": False,        # Caseinato de sodio + puede contener pescado
        },
    },

    "foto19": {
        "nombre": "Tomate pelado enlatado",
        "archivo": "foto19.jpeg",
        "ingredientes": [
            "tomate pelado", "jugo de tomates", "ácido cítrico",
        ],
        "alergenos": "",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto20": {
        "nombre": "Puré de tomate",
        "archivo": "foto20.jpeg",
        "ingredientes": ["tomate", "ácido cítrico"],
        "alergenos": "",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto21": {
        "nombre": "Atún en lata",
        "archivo": "foto21.jpeg",
        "ingredientes": ["atún", "agua", "sal"],
        "alergenos": "CONTIENE PESCADO.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,        # Atún = pescado = animal
        },
    },

    "foto22": {
        "nombre": "Fideos al huevo",
        "archivo": "foto22.jpeg",
        "ingredientes": [
            "harina de trigo tipo 000 enriquecida", "huevo",
        ],
        "alergenos": "CONTIENE HUEVO Y DERIVADOS DE TRIGO. PUEDE CONTENER SOJA.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,        # Huevo
        },
    },

    "foto23": {
        "nombre": "Harina de trigo",
        "archivo": "foto23.jpeg",
        "ingredientes": ["harina de trigo enriquecida"],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER HUEVO Y SOJA.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,        # PUEDE CONTENER HUEVO
        },
    },

    "foto24": {
        "nombre": "Fideos de sémola",
        "archivo": "foto24.jpeg",
        "ingredientes": [
            "harina de trigo enriquecida", "sémola de trigo candeal", "agua",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO.",
        "expected": {
            "sin_tacc": False,      # Harina + sémola de trigo
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto25": {
        "nombre": "Imagen borrosa (no legible)",
        "archivo": "foto25.jpeg",
        "mala_calidad": True,
        "expected_error": True,     # El sistema debería rechazar esta imagen
    },

    "foto26": {
        "nombre": "Imagen borrosa (no legible)",
        "archivo": "foto26.jpeg",
        "mala_calidad": True,
        "expected_error": True,
    },

    # ══════════════════════════════════════════════════════════════════
    # FOTOS PENDIENTES DE AGREGAR AL DATASET (27-44)
    # Ground truth ya definido, falta copiar las imágenes
    # ══════════════════════════════════════════════════════════════════

    "foto27": {
        "nombre": "Galletitas de chocolate (tipo Pepitos)",
        "archivo": "foto27.jpeg",
        "ingredientes": [
            "harina de trigo enriquecida", "azúcar", "grasa bovina refinada",
            "jarabe de maíz de alta fructosa", "cacao alcalinizado", "sal",
            "bicarbonato de sodio", "bicarbonato de amonio",
            "lecitina de soja", "aromatizante artificial a vainilla",
            "caramelo IV",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO Y DE SOJA. PUEDE CONTENER LECHE, MANÍ Y AVENA.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": False,   # PUEDE CONTENER LECHE
            "sin_frutos_secos": False,  # PUEDE CONTENER MANÍ
            "vegano": False,        # Grasa bovina + puede contener leche
        },
    },

    "foto28": {
        "nombre": "Jugo de naranja",
        "archivo": "foto28.jpeg",
        "ingredientes": [
            "agua", "jugo concentrado de naranja", "azúcar", "ácido cítrico",
            "benzoato de sodio", "sorbato de potasio", "sucralosa",
            "acesulfame K", "aromatizante idéntico al natural de naranja",
            "amarillo ocaso FCF", "tartrazina",
        ],
        "alergenos": "CONTIENE TARTRAZINA.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto29": {
        "nombre": "Postre lácteo de chocolate",
        "archivo": "foto29.jpeg",
        "ingredientes": [
            "leche entera", "suero de queso en polvo", "azúcar",
            "cacao en polvo", "almidón modificado de maíz",
            "carragenina", "goma guar", "aromatizante artificial a chocolate",
        ],
        "alergenos": "CONTIENE LECHE Y DERIVADOS DE LECHE. PUEDE CONTENER SOJA.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": False,   # Leche entera + suero de queso
            "sin_frutos_secos": True,
            "vegano": False,        # Leche
        },
    },

    "foto30": {
        "nombre": "Snack de maíz sabor queso",
        "archivo": "foto30.jpeg",
        "ingredientes": [
            "harina de maíz", "aceite de girasol", "sal",
            "suero de queso en polvo", "maltodextrina",
            "glutamato monosódico", "inosinato disódico",
            "aromatizante idéntico al natural sabor queso",
            "annatto", "dióxido de silicio",
        ],
        "alergenos": "CONTIENE DERIVADOS DE LECHE. PUEDE CONTENER DERIVADOS DE TRIGO Y SOJA.",
        "expected": {
            "sin_tacc": False,      # PUEDE CONTENER TRIGO
            "sin_lactosa": False,   # Suero de queso en polvo
            "sin_frutos_secos": True,
            "vegano": False,        # Suero de queso
        },
    },

    "foto31": {
        "nombre": "Pan lactal",
        "archivo": "foto31.jpeg",
        "ingredientes": [
            "harina de trigo enriquecida", "agua", "levadura",
            "azúcar", "sal", "aceite de girasol alto oleico",
            "propionato de calcio", "ácido ascórbico",
            "estearoil lactilato de sodio",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO. PUEDE CONTENER AVENA, CEBADA Y CENTENO.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto32": {
        "nombre": "Mermelada de frutilla light",
        "archivo": "foto32.jpeg",
        "ingredientes": [
            "frutilla", "agua", "jarabe de glucosa", "pectina",
            "goma garrofín", "ácido cítrico", "sorbato de potasio",
            "ciclamato de sodio", "glicósidos de esteviol",
            "carmín", "aromatizante idéntico al natural a frutilla",
        ],
        "alergenos": "PUEDE CONTENER DERIVADOS DE LECHE.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": False,   # PUEDE CONTENER LECHE
            "sin_frutos_secos": True,
            "vegano": False,        # Carmín (INS 120) = cochinilla + puede contener leche
        },
    },

    "foto33": {
        "nombre": "Salchicha",
        "archivo": "foto33.jpeg",
        "ingredientes": [
            "carne bovina", "carne aviar", "agua", "primer jugo bovino",
            "almidón de maíz", "sal", "proteína de soja", "especias",
            "polifosfatos", "eritorbato de sodio", "nitrito de sodio",
            "nitrato de sodio", "carmín", "aromatizante humo",
        ],
        "alergenos": "CONTIENE DERIVADOS DE SOJA.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,        # Carne bovina + carne aviar + primer jugo + carmín
        },
    },

    "foto34": {
        "nombre": "Pan de queso / chipá",
        "archivo": "foto34.jpeg",
        "ingredientes": [
            "fécula de mandioca", "agua", "queso sardo",
            "queso mar del plata", "grasa bovina refinada",
            "huevo entero pasteurizado", "leche entera en polvo",
            "sal", "pirofosfato ácido de sodio", "bicarbonato de sodio",
        ],
        "alergenos": "CONTIENE HUEVO Y DERIVADOS DE LECHE. LIBRE DE GLUTEN - SIN T.A.C.C.",
        "expected": {
            "sin_tacc": True,       # Declaración positiva: SIN TACC
            "sin_lactosa": False,   # Queso + leche en polvo
            "sin_frutos_secos": True,
            "vegano": False,        # Queso + huevo + grasa bovina + leche
        },
    },

    "foto35": {
        "nombre": "Galletitas de agua (tipo Traviata)",
        "archivo": "foto35.jpeg",
        "ingredientes": [
            "harina de trigo enriquecida", "aceite de girasol de alto oleico",
            "sal", "extracto de malta", "levadura",
            "bicarbonato de sodio", "lecitina de soja",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO, CEBADA Y SOJA. PUEDE CONTENER AVENA Y CENTENO.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto36": {
        "nombre": "Jugo en polvo sabor manzana",
        "archivo": "foto36.jpeg",
        "ingredientes": [
            "azúcar", "maltodextrina", "jugo de manzana deshidratado",
            "ácido cítrico", "aspartamo", "acesulfame K",
            "fosfato tricálcico", "aromatizante idéntico al natural a manzana",
            "dióxido de titanio", "tartrazina", "azul brillante FCF",
        ],
        "alergenos": "CONTIENE TARTRAZINA. FENILCETONÚRICOS: CONTIENE FENILALANINA.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto37": {
        "nombre": "Mayonesa",
        "archivo": "foto37.jpeg",
        "ingredientes": [
            "agua", "aceite de girasol", "vinagre de alcohol",
            "almidón modificado de maíz", "azúcar",
            "yema de huevo pasteurizada", "sal",
            "jugo concentrado de limón", "goma xántica",
            "ácido sórbico", "aromatizante natural a mostaza",
            "EDTA disódico cálcico", "BHA", "BHT",
        ],
        "alergenos": "CONTIENE HUEVO. PUEDE CONTENER SOJA Y DERIVADOS DE TRIGO.",
        "expected": {
            "sin_tacc": False,      # PUEDE CONTENER TRIGO
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": False,        # Yema de huevo
        },
    },

    "foto38": {
        "nombre": "Yogur de durazno",
        "archivo": "foto38.jpeg",
        "ingredientes": [
            "leche entera pasteurizada", "azúcar",
            "pulpa de durazno", "almidón modificado",
            "aromatizante natural a durazno", "sorbato de potasio",
            "annatto", "leche en polvo descremada",
            "cultivos lácticos", "gelatina",
        ],
        "alergenos": "CONTIENE LECHE.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": False,   # Leche + cultivos lácticos
            "sin_frutos_secos": True,
            "vegano": False,        # Leche + gelatina
        },
    },

    "foto39": {
        "nombre": "Pan dulce",
        "archivo": "foto39.jpeg",
        "ingredientes": [
            "harina de trigo 0000 enriquecida", "azúcar", "agua",
            "aceite de palma", "huevo líquido pasteurizado",
            "pasas de uva", "fruta escurrida", "levadura",
            "jarabe de glucosa", "sal", "mono y diglicéridos de ácidos grasos",
            "estearoil lactilato de sodio", "propionato de calcio",
            "aromatizantes artificiales", "tartrazina",
        ],
        "alergenos": "CONTIENE HUEVO, DERIVADOS DE TRIGO Y TARTRAZINA. PUEDE CONTENER ALMENDRAS, MANÍ Y NUECES.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": True,
            "sin_frutos_secos": False,  # PUEDE CONTENER ALMENDRAS, MANÍ, NUECES
            "vegano": False,        # Huevo
        },
    },

    "foto40": {
        "nombre": "Salsa de soja",
        "archivo": "foto40.jpeg",
        "ingredientes": [
            "agua", "poroto de soja", "trigo", "sal",
            "caramelo III", "glutamato monosódico",
            "sorbato de potasio", "ácido láctico",
        ],
        "alergenos": "CONTIENE SOJA Y TRIGO.",
        "expected": {
            "sin_tacc": False,      # Trigo
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto41": {
        "nombre": "Gomitas",
        "archivo": "foto41.jpeg",
        "ingredientes": [
            "jarabe de glucosa", "azúcar", "agua", "gelatina",
            "ácido cítrico", "ácido láctico", "aromatizantes artificiales",
            "aceite vegetal de palma", "cera de abejas", "cera de carnauba",
            "rojo allura AC", "amarillo ocaso", "tartrazina",
            "azul brillante FCF",
        ],
        "alergenos": "CONTIENE TARTRAZINA. PUEDE CONTENER DERIVADOS DE SOJA Y LECHE.",
        "expected": {
            "sin_tacc": True,
            "sin_lactosa": False,   # PUEDE CONTENER LECHE
            "sin_frutos_secos": True,
            "vegano": False,        # Gelatina + cera de abejas + puede contener leche
        },
    },

    "foto42": {
        "nombre": "Cereales (tipo Corn Flakes)",
        "archivo": "foto42.jpeg",
        "ingredientes": [
            "harina de maíz", "azúcar", "extracto de malta", "sal",
            "vitaminas y minerales", "lecitina de soja",
        ],
        "alergenos": "CONTIENE DERIVADOS DE CEBADA Y DE SOJA. PUEDE CONTENER AVENA, TRIGO Y CENTENO.",
        "expected": {
            "sin_tacc": False,      # Malta de cebada
            "sin_lactosa": True,
            "sin_frutos_secos": True,
            "vegano": True,
        },
    },

    "foto43": {
        "nombre": "Alfajor de chocolate",
        "archivo": "foto43.jpeg",
        "ingredientes": [
            "dulce de leche", "leche entera", "azúcar", "jarabe de glucosa",
            "bicarbonato de sodio", "sorbato de potasio",
            "aceite vegetal fraccionado", "leche descremada en polvo",
            "suero de queso en polvo", "lecitina de soja",
            "aromatizante artificial a vainilla",
            "harina de trigo enriquecida", "grasa bovina",
            "cacao en polvo", "sal", "bicarbonato de amonio",
            "propionato de calcio",
        ],
        "alergenos": "CONTIENE LECHE Y DERIVADOS DE TRIGO Y SOJA. PUEDE CONTENER MANÍ.",
        "expected": {
            "sin_tacc": False,      # Harina de trigo
            "sin_lactosa": False,   # Dulce de leche + leche + suero de queso
            "sin_frutos_secos": False,  # PUEDE CONTENER MANÍ
            "vegano": False,        # Leche + grasa bovina
        },
    },

    "foto44": {
        "nombre": "Sopa de pollo con fideos",
        "archivo": "foto44.jpeg",
        "ingredientes": [
            "fideos", "harina de trigo enriquecida", "agua", "cúrcuma",
            "sal", "almidón de maíz", "azúcar", "aceite vegetal de palma",
            "glutamato monosódico", "inosinato disódico",
            "carne de pollo deshidratada", "perejil", "cebolla",
            "cúrcuma", "apio", "aromatizante idéntico al natural a pollo",
            "caramelo IV",
        ],
        "alergenos": "CONTIENE DERIVADOS DE TRIGO Y APIO. PUEDE CONTENER HUEVO, SOJA Y DERIVADOS DE LECHE.",
        "expected": {
            "sin_tacc": False,
            "sin_lactosa": False,   # PUEDE CONTENER LECHE
            "sin_frutos_secos": True,
            "vegano": False,        # Carne de pollo + puede contener huevo y leche
        },
    },
}


# ══════════════════════════════════════════════════════════════════
# Estadísticas del dataset
# ══════════════════════════════════════════════════════════════════

def print_stats():
    """Imprime estadísticas del ground truth."""
    total = len(GROUND_TRUTH)
    valid = sum(1 for v in GROUND_TRUTH.values() if not v.get("mala_calidad"))
    bad = sum(1 for v in GROUND_TRUTH.values() if v.get("mala_calidad"))

    stats = {"sin_tacc": [0, 0], "sin_lactosa": [0, 0], "sin_frutos_secos": [0, 0], "vegano": [0, 0]}
    for v in GROUND_TRUTH.values():
        if v.get("mala_calidad"):
            continue
        for r in stats:
            if v["expected"][r]:
                stats[r][0] += 1  # APTO
            else:
                stats[r][1] += 1  # NO APTO

    print(f"\n{'='*60}")
    print(f"  GROUND TRUTH — ESTADÍSTICAS")
    print(f"{'='*60}")
    print(f"  Total productos:     {total}")
    print(f"  Productos válidos:   {valid}")
    print(f"  Imágenes de mala calidad: {bad}")
    print(f"\n  Distribución por restricción (APTO / NO APTO):")
    for r, (apto, no_apto) in stats.items():
        print(f"    {r:25} {apto:3} APTO  /  {no_apto:3} NO APTO")
    print()


if __name__ == "__main__":
    print_stats()

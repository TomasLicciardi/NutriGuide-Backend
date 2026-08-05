# app/services/ingredient_facts.py
"""
Schema central del fact base — representación enriquecida de un ingrediente.

Diseño basado en separación fact base / rule base:
  - Este módulo define QUÉ se sabe del ingrediente (tags semánticos).
  - Los predicados de restricciones (rule base) viven en restriction_predicates.py
    y operan sobre estos tags, nunca sobre el name original.

IngredientFacts reemplaza progresivamente las dataclasses dispersas:
  - IngredientResult (deterministic_classifier)
  - OFFIngredientResult (openfoodfacts_service)
  - PubChemResult (pubchem_service)
  - INSResult (ins_parser_service)
  - GeminiIngredientClassification (gemini_service)

Cada fuente del enrichment paralelo produce tags parciales con su provenance,
y el motor de fusión los combina en un solo IngredientFacts por ingrediente.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


# ═══════════════════════════════════════════════════════════════════════════
# Enumeraciones del dominio
# ═══════════════════════════════════════════════════════════════════════════


class IngredientCategory(str, Enum):
    """Clasificación estructural del ingrediente."""
    BASE = "BASE"              # ingrediente alimentario principal
    ADITIVO = "ADITIVO"        # aditivo tecnológico (con o sin INS)
    FLAVORING = "FLAVORING"    # aromatizante/saborizante (caso especial)
    VITAMIN = "VITAMIN"
    MINERAL = "MINERAL"
    UNKNOWN = "UNKNOWN"


class Origin(str, Enum):
    """Origen del ingrediente — clave para predicado vegano."""
    PLANT = "plant"
    ANIMAL = "animal"
    SYNTHETIC = "synthetic"
    MINERAL = "mineral"
    NATURAL_EXTRACT = "natural_extract"  # aromatizante natural sin clarificar
    UNKNOWN = "unknown"


class FlavoringType(str, Enum):
    """
    Tipos de aromatizante según CAA Cap. XVIII Art. 1383.

    La política de evaluación depende del tipo:
      - ARTIFICIAL / IDENTICAL_TO_NATURAL → origin=synthetic, safe por defecto
      - NATURAL → origin=natural_extract, confianza media
      - UNSPECIFIED → flag de incertidumbre
    """
    ARTIFICIAL = "artificial"
    IDENTICAL_TO_NATURAL = "idéntico al natural"
    NATURAL = "natural"
    UNSPECIFIED = "unspecified"


# ═══════════════════════════════════════════════════════════════════════════
# Tags canónicos de alérgenos (alineados con Codex Alimentarius)
# ═══════════════════════════════════════════════════════════════════════════

# Identificadores únicos — los predicados los referencian.
ALLERGEN_GLUTEN = "gluten"
ALLERGEN_WHEAT = "wheat"
ALLERGEN_BARLEY = "barley"
ALLERGEN_RYE = "rye"
ALLERGEN_OATS = "oats"
ALLERGEN_MILK = "milk"
ALLERGEN_LACTOSE = "lactose"
ALLERGEN_DAIRY = "dairy"
ALLERGEN_TREE_NUT = "tree-nut"
ALLERGEN_PEANUT = "peanut"
ALLERGEN_SOY = "soy"
ALLERGEN_EGG = "egg"
ALLERGEN_FISH = "fish"
ALLERGEN_SHELLFISH = "shellfish"
ALLERGEN_SESAME = "sesame"
ALLERGEN_SULFITES = "sulfites"
ALLERGEN_HONEY = "honey"


# Conjuntos por restricción — usados por los predicados.
GLUTEN_SOURCES: frozenset = frozenset({
    ALLERGEN_GLUTEN, ALLERGEN_WHEAT, ALLERGEN_BARLEY,
    ALLERGEN_RYE, ALLERGEN_OATS,
})

DAIRY_SOURCES: frozenset = frozenset({
    ALLERGEN_MILK, ALLERGEN_LACTOSE, ALLERGEN_DAIRY,
})

NUT_SOURCES: frozenset = frozenset({
    ALLERGEN_TREE_NUT, ALLERGEN_PEANUT,
})

ANIMAL_SOURCES: frozenset = frozenset({
    ALLERGEN_MILK, ALLERGEN_LACTOSE, ALLERGEN_DAIRY,
    ALLERGEN_EGG, ALLERGEN_FISH, ALLERGEN_SHELLFISH,
    ALLERGEN_HONEY,
})


# Etiqueta en español para cada alérgeno canónico — usada al construir motivos
# visibles al usuario. Si falta una entrada, se devuelve el token original.
ALLERGEN_ES_LABELS = {
    ALLERGEN_GLUTEN: "gluten",
    ALLERGEN_WHEAT: "trigo",
    ALLERGEN_BARLEY: "cebada",
    ALLERGEN_RYE: "centeno",
    ALLERGEN_OATS: "avena",
    ALLERGEN_MILK: "leche",
    ALLERGEN_LACTOSE: "lactosa",
    ALLERGEN_DAIRY: "lácteos",
    ALLERGEN_TREE_NUT: "frutos secos",
    ALLERGEN_PEANUT: "maní",
    ALLERGEN_SOY: "soja",
    ALLERGEN_EGG: "huevo",
    ALLERGEN_FISH: "pescado",
    ALLERGEN_SHELLFISH: "mariscos",
    ALLERGEN_SESAME: "sésamo",
    ALLERGEN_SULFITES: "sulfitos",
    ALLERGEN_HONEY: "miel",
}


def allergens_es(allergens) -> str:
    """
    Formatea un conjunto de alérgenos canónicos como lista en español.

    Colapsa redundancia del grupo lácteo: si está "milk", omite "lactose" y
    "dairy" — para el usuario son la misma cosa y "lactosa, leche, lácteos"
    lee como ruido.
    """
    relevant = set(allergens)
    if ALLERGEN_MILK in relevant:
        relevant -= {ALLERGEN_LACTOSE, ALLERGEN_DAIRY}
    return ", ".join(sorted(ALLERGEN_ES_LABELS.get(a, a) for a in relevant))


# Targets sensoriales de alto riesgo — política conservadora para aromatizantes
# cuyo target es un alérgeno crítico (no se puede asumir safe automáticamente).
HIGH_RISK_FLAVORING_TARGETS: frozenset = frozenset({
    "almendra", "nuez", "avellana", "castaña", "castaña de cajú",
    "pistacho", "pecán", "macadamia",
    "maní", "cacahuete",
})


# ═══════════════════════════════════════════════════════════════════════════
# Provenance — trazabilidad de cada tag
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TagProvenance:
    """
    Origen de un tag específico — qué fuente lo aportó y con qué confianza.

    Permite explicabilidad final del veredicto: cuando un ingrediente falla
    una restricción, se puede mostrar qué tag exacto disparó el fallo y de
    qué fuente vino ese tag.
    """
    source: str
    # Valores válidos:
    #   "codex_ins"          — base oficial Codex Alimentarius
    #   "off_taxonomy"       — Open Food Facts taxonomy
    #   "foodon"             — FoodOn ontology
    #   "pubchem"            — PubChem PUG-REST
    #   "kb_cache"           — knowledge base local (cache de análisis previos)
    #   "zero_shot"          — clasificación zero-shot mDeBERTa
    #   "gemini"             — pre-clasificación de Gemini Vision
    #   "legal_declaration"  — declaración CONTIENE / PUEDE CONTENER
    #   "policy_caa"         — política regulatoria explícita (CAA Cap. XVIII)
    #   "parser"             — derivado del parser estructural

    confidence: float  # ∈ [0, 1]
    evidence: str      # explicación legible para el usuario final


# ═══════════════════════════════════════════════════════════════════════════
# IngredientFacts — el fact base
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class IngredientFacts:
    """
    Representación enriquecida de un ingrediente.

    Construido por enrich_ingredient() fusionando tags desde múltiples fuentes
    externas. Los predicados de restricciones operan sobre estos tags, nunca
    sobre el name_es original.

    Invariantes:
      - allergens, contains, derived_from son sets de identificadores canónicos
      - tag_provenance mantiene una entrada por cada tag presente
      - confidence es la confianza mínima entre los tags críticos para
        las restricciones del usuario
    """

    # ── Identidad ──
    name_es: str
    name_en: Optional[str] = None

    # ── Clasificación estructural ──
    category: IngredientCategory = IngredientCategory.UNKNOWN
    function_tag: Optional[str] = None
    # function_tag valores: "emulsionante", "conservante", "colorante",
    # "antioxidante", "estabilizante", "espesante", "edulcorante",
    # "acidulante", "humectante", "antiaglutinante", "leudante",
    # "saborizante", "secuestrante", "resaltador", etc.

    origin: Origin = Origin.UNKNOWN

    # ── Códigos regulatorios ──
    codex_ins_code: Optional[int] = None
    codex_ins_subcode: Optional[str] = None  # ej: "ii" en INS 500ii

    # ── Tags semánticos para predicados ──
    allergens: Set[str] = field(default_factory=set)
    contains: Set[str] = field(default_factory=set)
    derived_from: Set[str] = field(default_factory=set)

    # ── Caso especial: aromatizantes/saborizantes ──
    flavoring_type: Optional[FlavoringType] = None
    target_sensory: Optional[str] = None
    # target_sensory NO se evalúa como ingrediente — es solo descriptor sensorial.
    # Los predicados ignoran este campo excepto para política de alto riesgo
    # (HIGH_RISK_FLAVORING_TARGETS).

    # ── Información descriptiva (no afecta predicados) ──
    description_es: Optional[str] = None

    # ── Trazabilidad ──
    tag_provenance: Dict[str, List[TagProvenance]] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)
    confidence: float = 0.0

    # ═══════════════════════════════════════════════════════════════════════
    # Helpers de consulta — usados por los predicados de restricciones
    # ═══════════════════════════════════════════════════════════════════════

    def allergens_intersect(self, allergen_set: Set[str]) -> bool:
        """True si algún allergen del ingrediente está en allergen_set."""
        return bool(self.allergens & allergen_set)

    def contains_any(self, substance_set: Set[str]) -> bool:
        """True si algún 'contains' del ingrediente está en substance_set."""
        return bool(self.contains & substance_set)

    def derived_from_any(self, source_set: Set[str]) -> bool:
        """True si algún 'derived_from' del ingrediente está en source_set."""
        return bool(self.derived_from & source_set)

    def is_flavoring(self) -> bool:
        return self.category == IngredientCategory.FLAVORING

    def is_high_risk_flavoring(self) -> bool:
        """
        True si es un aromatizante con target sensorial de alto riesgo
        (frutos secos / maní). Estos casos NUNCA se asumen safe
        automáticamente — requieren confirmación por declaración legal.
        """
        if not self.is_flavoring() or self.target_sensory is None:
            return False
        return self.target_sensory.lower() in HIGH_RISK_FLAVORING_TARGETS

    # ═══════════════════════════════════════════════════════════════════════
    # Mutadores — usados por el motor de fusión durante el enrichment
    # ═══════════════════════════════════════════════════════════════════════

    def add_allergen(self, allergen: str, provenance: TagProvenance) -> None:
        self.allergens.add(allergen)
        self._record_provenance(f"allergen:{allergen}", provenance)

    def add_contains(self, substance: str, provenance: TagProvenance) -> None:
        self.contains.add(substance)
        self._record_provenance(f"contains:{substance}", provenance)

    def add_derived_from(self, source: str, provenance: TagProvenance) -> None:
        self.derived_from.add(source)
        self._record_provenance(f"derived_from:{source}", provenance)

    def _record_provenance(self, tag_key: str, provenance: TagProvenance) -> None:
        self.tag_provenance.setdefault(tag_key, []).append(provenance)
        if provenance.source not in self.sources:
            self.sources.append(provenance.source)


# ═══════════════════════════════════════════════════════════════════════════
# ProductLegalDeclaration — autoridad primaria sobre alérgenos
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ProductLegalDeclaration:
    """
    Declaración legal del producto extraída del texto de la etiqueta.

    Esta fuente PISA cualquier inferencia derivada del análisis de
    ingredientes individuales: el CAA Cap. XVIII Art. 1383 establece la
    responsabilidad legal del fabricante sobre las declaraciones de
    alérgenos, lo que la convierte en la fuente de mayor autoridad.

    Política definida con el usuario:
      - "CONTIENE X" → restricción aplicable, NO APTO
      - "PUEDE CONTENER X" → restricción aplicable, NO APTO (conservador)
      - "Sin TACC" / "Libre de gluten" → declaración positiva, APTO
    """

    # Conjuntos de alérgenos (identificadores canónicos)
    contains: Set[str] = field(default_factory=set)
    may_contain: Set[str] = field(default_factory=set)

    # Declaraciones positivas: {"sin_tacc", "vegano", "sin_lactosa", ...}
    positive_claims: Set[str] = field(default_factory=set)

    # Texto literal original (para auditoría y mostrar al usuario)
    raw_text: Optional[str] = None

    def declares_any(self, allergen_set: Set[str]) -> bool:
        """True si CONTIENE o PUEDE CONTENER algún alérgeno del set."""
        return bool((self.contains | self.may_contain) & allergen_set)

    def declares_in_contains(self, allergen_set: Set[str]) -> bool:
        """True solo si está en CONTIENE (no PUEDE CONTENER)."""
        return bool(self.contains & allergen_set)

    def declares_positive(self, claim: str) -> bool:
        return claim in self.positive_claims

    def matched_allergens(self, allergen_set: Set[str]) -> Set[str]:
        """Retorna los alérgenos del set que están declarados."""
        return (self.contains | self.may_contain) & allergen_set

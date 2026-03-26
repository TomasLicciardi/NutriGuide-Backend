# app/services/rag_service.py
"""
Servicio RAG simplificado para NutriGuide.

La base de conocimiento ahora contiene información estructurada y útil:
- Base de aditivos INS con origen real (animal/vegetal/sintético)
- Casos especiales argentinos resueltos
- Ingredientes ambiguos con resolución

Se usa como contexto cuando Gemini clasifica ingredientes desconocidos
(fallback del clasificador determinista).
"""

import logging
from typing import List, Dict
from sqlalchemy.orm import Session

from app.models import RAGContextDocument
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class RAGService:
    def initialize_rag_knowledge_base(self, db: Session):
        """
        Inicializa la base de conocimiento RAG.
        Agrega documentos faltantes sin borrar los existentes.
        """
        try:
            knowledge_documents = self._get_knowledge_documents()
            expected_count = len(knowledge_documents)

            existing_count = db.query(RAGContextDocument).count()
            if existing_count >= expected_count:
                logger.info(f"Base RAG ya inicializada ({existing_count} docs)")
                return

            existing_titles = {
                row[0] for row in db.query(RAGContextDocument.title).all()
            }

            added = 0
            for doc_data in knowledge_documents:
                if doc_data["title"] in existing_titles:
                    continue

                document = RAGContextDocument(
                    title=doc_data["title"],
                    content=doc_data["content"],
                    document_type=doc_data["type"],
                    relevance_score=doc_data["relevance"],
                )
                db.add(document)
                db.flush()
                embedding_service.store_rag_document_embedding(document, db)
                added += 1

            db.commit()
            if added > 0:
                logger.info(f"RAG: {added} documentos nuevos (total esperado: {expected_count})")

        except Exception as e:
            logger.error(f"Error inicializando RAG: {e}")
            db.rollback()

    async def get_classification_context(self, ingredients: List[str], db: Session) -> str:
        """Obtiene contexto RAG para clasificar ingredientes desconocidos."""
        return self._get_relevant_context(ingredients, db)

    def _get_relevant_context(self, ingredients: List[str], db: Session) -> str:
        """Busca documentos RAG relevantes por embeddings."""
        try:
            query = " ".join(ingredients[:5])
            relevant_docs = embedding_service.find_relevant_rag_documents(query, db, top_k=3)

            if not relevant_docs:
                return self._get_fallback_context()

            parts = []
            for doc, similarity in relevant_docs:
                if similarity > 0.35:
                    content = doc.content[:600] if len(doc.content) > 600 else doc.content
                    parts.append(f"**{doc.title}**:\n{content}")

            return "\n\n".join(parts) if parts else self._get_fallback_context()

        except Exception as e:
            logger.error(f"Error obteniendo contexto RAG: {e}")
            return self._get_fallback_context()

    @staticmethod
    def _get_fallback_context() -> str:
        return (
            "Reglas: Vegano=sin productos animales. Vegetariano=sin carne/pescado. "
            "Sin gluten=sin TACC. Sin lactosa=sin lacteos. Sin frutos secos=sin nueces/mani."
        )

    # ══════════════════════════════════════════════════════════════════════
    # Base de conocimiento estructurada
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_knowledge_documents() -> List[Dict]:
        return [
            {
                "title": "Aditivos INS de Origen Animal",
                "content": """ADITIVOS QUE AFECTAN RESTRICCIONES DIETETICAS:

INS 120 / Carmin / Acido carminico / Cochinilla:
- Origen: Insecto hembra Dactylopius coccus. Colorante rojo natural.
- Afecta: vegano (NO apto). Vegetariano SI apto (no es carne).
- Sinonimos: E120, rojo cochinilla, colorante natural rojo, CI 75470.

INS 441 / Gelatina:
- Origen: Colageno de huesos y piel animal (bovino/porcino).
- Afecta: vegano (NO apto), vegetariano (NO apto).
- Alternativa vegetal: agar agar (INS 406).

INS 542 / Fosfato de hueso:
- Origen: Huesos animales.
- Afecta: vegano, vegetariano.

INS 901 / Cera de abejas:
- Origen: Abejas.
- Afecta: vegano. Vegetariano SI apto.

INS 904 / Shellac / Goma laca:
- Origen: Secrecion del insecto Kerria lacca.
- Afecta: vegano. Vegetariano SI apto.

INS 966 / Lactitol:
- Origen: Derivado de lactosa.
- Afecta: sin_lactosa (NO apto para intolerantes).""",
                "type": "aditivos_animales",
                "relevance": 1.0,
            },
            {
                "title": "Aditivos INS Sinteticos - Seguros para las 5 Restricciones",
                "content": """ESTOS ADITIVOS SON SEGUROS PARA TODAS LAS RESTRICCIONES:

PRESERVANTES (INS 200-283):
- INS 200-203: Acido sorbico y sorbatos
- INS 210-213: Acido benzoico y benzoatos
- INS 220-228: Dioxido de azufre y sulfitos
- INS 280-283: Acido propionico y propionatos

ANTIOXIDANTES (INS 300-321):
- INS 300-304: Vitamina C y ascorbatos
- INS 306-309: Tocoferoles (Vitamina E)
- INS 319/320/321: TBHQ, BHA, BHT

ACIDULANTES (INS 330-341):
- INS 270: Acido lactico (fermentacion industrial, NO de lactosuero)
- INS 330-333: Acido citrico y citratos
- INS 334-337: Acido tartarico y tartratos
- INS 338-341: Acido fosforico y fosfatos

EMULSIFICANTES VEGETALES (INS 400-499):
- INS 400-407: Alginatos y carragenina (algas marinas)
- INS 410/412/414/415: Gomas (garrofin, guar, arabiga, xantica)
- INS 440: Pectinas
- INS 471: Monogliceridos (origen vegetal en Argentina)

SALES MINERALES (INS 500-580):
- INS 500-504: Carbonatos/bicarbonatos
- INS 551-559: Silicatos

POTENCIADORES (INS 620-635):
- INS 621: Glutamato monosodico
- INS 627/631/635: Nucleotidos

EDULCORANTES (INS 950-969):
- INS 950: Acesulfame K, INS 951: Aspartamo
- INS 955: Sucralosa, INS 960: Stevia""",
                "type": "aditivos_sinteticos",
                "relevance": 0.95,
            },
            {
                "title": "Colorantes INS 100-199 por Origen",
                "content": """COLORANTES VEGETALES/MINERALES (APTOS PARA VEGANOS):
- INS 100 Curcumina: curcuma (vegetal)
- INS 101 Riboflavina: sintetica/levadura
- INS 140/141 Clorofila: vegetal
- INS 150a-d Caramelo: azucar quemada
- INS 160a Beta-caroteno: zanahoria/sintesis
- INS 160b Annatto/Achiote: semillas
- INS 160c Oleorresina de pimenton: pimiento
- INS 162 Rojo de remolacha: remolacha
- INS 163 Antocianinas: frutas rojas
- INS 170 Carbonato de calcio: mineral

COLORANTES SINTETICOS (APTOS PARA TODOS):
- INS 102 Tartrazina: amarillo artificial
- INS 110 Amarillo Ocaso FCF
- INS 122 Azorrubina, INS 124 Ponceau 4R
- INS 129 Rojo Allura AC (Rojo N40)
- INS 132 Indigotina, INS 133 Azul Brillante FCF

COLORANTE ANIMAL (NO APTO VEGANO):
- INS 120 Carmin/Cochinilla: INSECTO""",
                "type": "colorantes",
                "relevance": 0.95,
            },
            {
                "title": "Ingredientes Ambiguos Argentinos - Resolucion",
                "content": """INGREDIENTES QUE GENERAN CONFUSION EN ETIQUETAS ARGENTINAS:

MANTECA:
- En Argentina: manteca = mantequilla (LACTEO). NO apto sin_lactosa ni vegano.
- Manteca de cacao: NO es lacteo, es grasa vegetal. APTO para todos.
- Manteca de mani: NO es lacteo, es pasta de mani. APTO sin_lactosa y vegano.

OLEOMARGARINA:
- Mezcla de aceites vegetales. En Argentina, generalmente SIN lacteos.
- APTO para veganos y sin_lactosa salvo que indique "con leche".

EXTRACTO DE MALTA:
- Origen: cebada. CONTIENE GLUTEN. NO apto sin_gluten.
- Diferente de maltodextrina (usualmente de maiz, APTO sin_gluten).

LECITINA:
- Lecitina de soja: APTO para veganos (vegetal).
- Lecitina de huevo: NO apto para veganos (animal).

GELATINA:
- Sin especificar origen: asumir ANIMAL. NO apto vegano ni vegetariano.
- Gelatina vegetal / agar agar: APTO para todos.

ACIDO LACTICO (INS 270):
- Producido por fermentacion bacteriana industrial. NO proviene de leche.
- APTO sin_lactosa y vegano.

HARINA 000 / 0000:
- En Argentina, harina numerada = SIEMPRE trigo. CONTIENE GLUTEN.

ALMIDONES MODIFICADOS (INS 1400-1442):
- En Argentina, generalmente de maiz o mandioca. APTO sin_gluten.
- Si dice "almidon modificado de trigo": NO apto sin_gluten.
- Si no especifica fuente: probablemente maiz, pero dudoso.

CASEINATO DE SODIO / CALCIO:
- Derivado de caseina (proteina de leche).
- NO apto sin_lactosa ni vegano.

SUERO DE LECHE / LACTOSUERO:
- Subproducto lacteo. NO apto sin_lactosa ni vegano.

NUEZ MOSCADA:
- Especia (Myristica fragrans). NO es fruto seco.
- APTO sin_frutos_secos.""",
                "type": "ambiguos_argentinos",
                "relevance": 1.0,
            },
            {
                "title": "Advertencias de Alergenos en Etiquetas Argentinas",
                "content": """INTERPRETACION LEGAL EN ARGENTINA:

"CONTIENE X": El ingrediente esta presente. Certeza total.
"PUEDE CONTENER X": Riesgo de contaminacion cruzada en fabrica.
"ELABORADO EN LINEAS QUE PROCESAN X": Igual que PUEDE CONTENER.
"SIN TACC": Certificacion oficial libre de gluten (Trigo, Avena, Cebada, Centeno).
"LIBRE DE GLUTEN": Equivalente a SIN TACC.

TACC = Trigo, Avena, Cebada, Centeno (termino argentino para fuentes de gluten).

PARA ALERGIAS/INTOLERANCIAS (sin_gluten, sin_lactosa, sin_frutos_secos):
- CONTIENE + PUEDE CONTENER = NO APTO (modo estricto).

PARA PREFERENCIAS DIETETICAS (vegano, vegetariano):
- CONTIENE + PUEDE CONTENER = NO APTO (modo estricto).

SULFITOS: Aditivo conservante. NO afecta ninguna de las 5 restricciones dieteticas.""",
                "type": "advertencias_legales",
                "relevance": 0.9,
            },
        ]


# Instancia global
rag_service = RAGService()

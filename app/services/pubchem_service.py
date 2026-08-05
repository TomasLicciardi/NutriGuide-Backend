# app/services/pubchem_service.py
"""
Servicio PubChem — Tier 4 del pipeline multi-fuente.

Consulta PUG-REST para identificar compuestos químicos/técnicos que
Open Food Facts no reconoce. Obtiene descripción y sinónimos para
inferir origen y seguridad del compuesto.

Útil para aditivos como TBHQ, BHA, BHT, carboximetilcelulosa, etc.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_TIMEOUT = 10.0

_ANIMAL_KEYWORDS = [
    "milk", "dairy", "casein", "whey", "lactose", "collagen",
    "gelatin", "bone", "animal", "beef", "pork", "fish",
    "egg", "albumin", "keratin", "lanolin", "tallow",
    "honey", "beeswax", "carmine", "cochineal", "shellac",
]

_GLUTEN_KEYWORDS = [
    "wheat", "barley", "rye", "oat", "gluten", "triticum",
    "hordeum", "secale", "avena",
]

_NUT_KEYWORDS = [
    "almond", "walnut", "hazelnut", "pistachio", "cashew",
    "macadamia", "pecan", "peanut", "arachis",
]

_PLANT_KEYWORDS = [
    "cellulose", "starch", "plant", "vegetable", "soy", "corn",
    "maize", "rice", "sugar", "citric", "ascorbic", "pectin",
    "gum", "alginate", "carrageenan", "agar",
]

_SYNTHETIC_KEYWORDS = [
    "synthetic", "artificial", "chemical", "petroleum",
]


def _kw_match(corpus: str, keywords: List[str]) -> bool:
    """
    Match por palabra completa (con plural opcional), no por substring.

    Evita el falso positivo clásico: `"oat" in "benzoate"` daba True y marcaba
    gluten en el benzoato de sodio. Con borde de palabra, "oat"/"oats" matchea
    solo cuando es realmente la palabra.
    """
    return any(
        re.search(r"\b" + re.escape(kw) + r"s?\b", corpus) for kw in keywords
    )


@dataclass
class PubChemResult:
    name_en: str
    found: bool = False
    cid: Optional[int] = None
    description: Optional[str] = None
    synonyms: List[str] = field(default_factory=list)
    inferred_origin: Optional[str] = None  # animal/vegetal/synthetic/mineral
    is_tacc_safe: Optional[bool] = None
    is_lactose_safe: Optional[bool] = None
    is_nut_safe: Optional[bool] = None
    is_vegan_safe: Optional[bool] = None
    evidence: List[str] = field(default_factory=list)


class PubChemService:
    """Tier 4: identifica compuestos técnicos usando PubChem PUG-REST."""

    async def identify_compounds(
        self, ingredients_en: List[str]
    ) -> Dict[str, PubChemResult]:
        """Consulta PubChem para cada ingrediente en inglés."""
        if not ingredients_en:
            return {}

        results: Dict[str, PubChemResult] = {}
        semaphore = asyncio.Semaphore(4)  # max 4 req en paralelo (limit 5/s)

        async def _query_one(name_en: str):
            async with semaphore:
                results[name_en] = await self._query_compound(name_en)

        await asyncio.gather(
            *[_query_one(name) for name in ingredients_en],
            return_exceptions=True,
        )

        found_count = sum(1 for r in results.values() if r.found)
        logger.info(f"PubChem: {found_count}/{len(ingredients_en)} compuestos encontrados")
        return results

    async def _query_compound(self, name_en: str) -> PubChemResult:
        """Consulta un compuesto individual en PubChem."""
        result = PubChemResult(name_en=name_en)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                desc_data = await self._fetch_description(client, name_en)
                if desc_data:
                    result.found = True
                    result.cid = desc_data.get("cid")
                    result.description = desc_data.get("description")
                    result.evidence.append(f"PubChem CID: {result.cid}")

                syn_data = await self._fetch_synonyms(client, name_en)
                if syn_data:
                    result.synonyms = syn_data[:20]

            if result.found:
                self._infer_properties(result)

        except httpx.TimeoutException:
            logger.warning(f"PubChem timeout para '{name_en}'")
            result.evidence.append("PubChem: timeout")
        except Exception as e:
            logger.warning(f"PubChem error para '{name_en}': {e}")
            result.evidence.append(f"PubChem: error ({type(e).__name__})")

        return result

    async def _fetch_description(
        self, client: httpx.AsyncClient, name_en: str
    ) -> Optional[dict]:
        url = f"{_BASE_URL}/compound/name/{name_en}/description/JSON"
        resp = await client.get(url)
        if resp.status_code != 200:
            return None

        data = resp.json()
        informations = data.get("InformationList", {}).get("Information", [])
        if not informations:
            return None

        cid = informations[0].get("CID")
        description = None
        for info in informations:
            desc = info.get("Description")
            if desc and len(desc) > 10:
                description = desc
                break

        return {"cid": cid, "description": description}

    async def _fetch_synonyms(
        self, client: httpx.AsyncClient, name_en: str
    ) -> Optional[List[str]]:
        url = f"{_BASE_URL}/compound/name/{name_en}/synonyms/JSON"
        resp = await client.get(url)
        if resp.status_code != 200:
            return None

        data = resp.json()
        info_list = data.get("InformationList", {}).get("Information", [])
        if not info_list:
            return None

        return info_list[0].get("Synonym", [])

    def _infer_properties(self, result: PubChemResult):
        """Infiere origen y seguridad a partir de descripción + sinónimos."""
        text_corpus = " ".join([
            result.description or "",
            " ".join(result.synonyms[:10]),
        ]).lower()

        # Inferir origen
        if _kw_match(text_corpus, _ANIMAL_KEYWORDS):
            result.inferred_origin = "animal"
            result.evidence.append("PubChem: origen inferido ANIMAL")
        elif _kw_match(text_corpus, _PLANT_KEYWORDS):
            result.inferred_origin = "vegetal"
            result.evidence.append("PubChem: origen inferido VEGETAL")
        elif _kw_match(text_corpus, _SYNTHETIC_KEYWORDS):
            result.inferred_origin = "sintetico"
            result.evidence.append("PubChem: origen inferido SINTÉTICO")

        # Inferir restricciones
        if _kw_match(text_corpus, _GLUTEN_KEYWORDS):
            result.is_tacc_safe = False
            result.evidence.append("PubChem: contiene keywords de gluten")
        else:
            result.is_tacc_safe = True

        dairy_match = _kw_match(text_corpus, ["milk", "dairy", "casein", "whey", "lactose"])
        if dairy_match:
            result.is_lactose_safe = False
            result.is_vegan_safe = False
            result.evidence.append("PubChem: contiene keywords lácteos")
        elif result.inferred_origin == "animal":
            result.is_lactose_safe = True
            result.is_vegan_safe = False
        elif result.inferred_origin in ("vegetal", "sintetico"):
            result.is_lactose_safe = True
            result.is_vegan_safe = True

        if _kw_match(text_corpus, _NUT_KEYWORDS):
            result.is_nut_safe = False
            result.evidence.append("PubChem: contiene keywords frutos secos")
        else:
            result.is_nut_safe = True

        # Detectar INS/E codes en sinónimos
        for syn in result.synonyms[:20]:
            m = re.match(r"^E\s*(\d{3,4})", syn, re.IGNORECASE)
            if m:
                result.evidence.append(f"PubChem sinónimo: código E{m.group(1)}")
                break


pubchem_service = PubChemService()

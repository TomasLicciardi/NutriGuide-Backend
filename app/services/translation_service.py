# app/services/translation_service.py
"""
Servicio de traducción ES→EN usando modelo local MarianMT.

Traduce ingredientes del español al inglés para poder consultarlos
en bases de datos globales (Open Food Facts, PubChem).

Modelo: Helsinki-NLP/opus-mt-es-en (~312MB)
Se carga una sola vez al startup y reutiliza para todas las requests.

v2.1: Agrega translate_batch_async() para no bloquear el event loop de FastAPI.
"""

import asyncio
import logging
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None
_lock = threading.Lock()

# Diccionario de traducciones conocidas para ingredientes que MarianMT
# traduce mal o no traduce (términos regionales argentinos, aditivos, etc.)
_FOOD_DICTIONARY: Dict[str, str] = {
    "goma xantica": "xanthan gum",
    "goma xantana": "xanthan gum",
    "goma guar": "guar gum",
    "goma arabiga": "gum arabic",
    "goma garrofin": "locust bean gum",
    "zapallo": "squash",
    "rocu": "annatto",
    "annatto": "annatto",
    "curcuma": "turmeric",
    "aji molido": "chili powder",
    "aji": "chili pepper",
    "clavo de olor": "clove",
    "oregano": "oregano",
    "perejil": "parsley",
    "romero": "rosemary",
    "tomillo": "thyme",
    "laurel": "bay leaf",
    "jengibre": "ginger",
    "canela": "cinnamon",
    "canela en polvo": "cinnamon powder",
    "pimienta negra": "black pepper",
    "pimienta roja": "red pepper",
    "comino": "cumin",
    "mostaza blanca": "white mustard",
    "semilla de apio": "celery seed",
    "caramelo iv": "caramel color",
    "caramelo": "caramel color",
    "clorofila": "chlorophyll",
    "edta disodico calcico": "calcium disodium edta",
    "edta disodico": "disodium edta",
    "caseinato de sodio": "sodium caseinate",
    "lecitina de soja": "soy lecithin",
    "sorbato de potasio": "potassium sorbate",
    "acido sorbico": "sorbic acid",
    "acido citrico": "citric acid",
    "acido lactico": "lactic acid",
    "acido folico": "folic acid",
    "acido ascorbico": "ascorbic acid",
    "bicarbonato de sodio": "sodium bicarbonate",
    "glutamato monosodico": "monosodium glutamate",
    "inosinato de sodio": "disodium inosinate",
    "inosinato disodico": "disodium inosinate",
    "guanilato disodico": "disodium guanylate",
    "cloruro de sodio": "sodium chloride",
    "cloruro de potasio": "potassium chloride",
    "sulfato ferroso": "ferrous sulfate",
    "sulfato de zinc": "zinc sulfate",
    "pirofosfato ferrico": "ferric pyrophosphate",
    "yodato de potasio": "potassium iodate",
    "carboximetilcelulosa": "carboxymethylcellulose",
    "nicotinamida": "nicotinamide",
    "tiamina": "thiamine",
    "riboflavina": "riboflavin",
    "maltodextrina": "maltodextrin",
    "almidon modificado": "modified starch",
    "almidon de maiz": "corn starch",
    "almidon de papa": "potato starch",
    "aceite de girasol": "sunflower oil",
    "aceite de girasol alto oleico": "high oleic sunflower oil",
    "aceite de palma": "palm oil",
    "aceite vegetal": "vegetable oil",
    "aceite vegetal de girasol": "sunflower oil",
    "aceites vegetales": "vegetable oils",
    "grasa vegetal": "vegetable fat",
    "jarabe de glucosa": "glucose syrup",
    "jarabe de maiz": "corn syrup",
    "vinagre de alcohol": "alcohol vinegar",
    "vinagre de vino": "wine vinegar",
    "concentrado doble de tomate": "double concentrated tomato paste",
    "cacao en polvo": "cocoa powder",
    "leche en polvo": "milk powder",
    "suero de leche": "whey",
    "cebolla en polvo": "onion powder",
    "ajo en polvo": "garlic powder",
    "laurel en polvo": "bay leaf powder",
    "harina de trigo": "wheat flour",
    "harina de trigo enriquecida": "enriched wheat flour",
    "harina de trigo 000 enriquecida": "enriched wheat flour",
    "harina 0000 enriquecida": "enriched wheat flour",
    "saborizante artificial": "artificial flavoring",
    "aromatizantes naturales": "natural flavorings",
    "aromatizante identico al natural": "nature-identical flavoring",
    "aromatizantes": "flavorings",
    "especias": "spices",
    "vainilla": "vanilla",
    "carne bovina deshidratada": "dehydrated beef",
    "gelatina": "gelatin",
    "almendras": "almonds",
    "nuez moscada": "nutmeg",
    "vitamina c": "vitamin c",
    "vitamina d": "vitamin d",
    "vitamina b1": "vitamin b1",
    "azucar": "sugar",
    "sal": "salt",
    "agua": "water",
}

_cache: Dict[str, str] = {}


def _load_model():
    """Carga el modelo MarianMT. Se llama una sola vez."""
    global _model, _tokenizer
    if _model is not None:
        return

    with _lock:
        if _model is not None:
            return

        from transformers import MarianMTModel, MarianTokenizer

        model_name = "Helsinki-NLP/opus-mt-es-en"
        logger.info(f"Cargando modelo de traducción: {model_name}")
        _tokenizer = MarianTokenizer.from_pretrained(model_name)
        _model = MarianMTModel.from_pretrained(model_name)
        logger.info("Modelo de traducción cargado correctamente")


class TranslationService:
    """Traduce ingredientes del español al inglés usando MarianMT local."""

    def __init__(self):
        _load_model()

    def translate(self, text_es: str) -> str:
        """Traduce un texto individual."""
        results = self.translate_batch([text_es])
        return results[0]

    def translate_batch(self, texts_es: List[str]) -> List[str]:
        """
        Traduce un lote de textos ES→EN.
        Prioridad: diccionario de alimentos → cache → modelo MarianMT.
        """
        if not texts_es:
            return []

        results: List[Optional[str]] = [None] * len(texts_es)
        to_translate: List[str] = []
        to_translate_indices: List[int] = []

        for i, text in enumerate(texts_es):
            key = text.lower().strip()
            if key in _FOOD_DICTIONARY:
                results[i] = _FOOD_DICTIONARY[key]
                _cache[key] = _FOOD_DICTIONARY[key]
            elif key in _cache:
                results[i] = _cache[key]
            else:
                to_translate.append(text)
                to_translate_indices.append(i)

        if to_translate:
            try:
                translated = self._run_translation(to_translate)
                for idx, (original, trans) in enumerate(zip(to_translate, translated)):
                    key = original.lower().strip()
                    _cache[key] = trans
                    results[to_translate_indices[idx]] = trans
            except Exception as e:
                logger.error(f"Error en traducción batch: {e}")
                for idx, original in enumerate(to_translate):
                    results[to_translate_indices[idx]] = original

        return [r if r is not None else texts_es[i] for i, r in enumerate(results)]

    @staticmethod
    def _run_translation(texts: List[str]) -> List[str]:
        """Ejecuta la traducción con el modelo cargado."""
        import torch

        tokens = _tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=128,
        )
        with torch.no_grad():
            output = _model.generate(
                **tokens,
                num_beams=2,
                max_length=64,
            )
        decoded = [
            _tokenizer.decode(t, skip_special_tokens=True) for t in output
        ]
        logger.info(f"Traducidos {len(texts)} ingredientes")
        return decoded

    async def translate_batch_async(self, texts_es: List[str]) -> List[str]:
        """Wrapper async que ejecuta la traducción en un thread separado."""
        return await asyncio.to_thread(self.translate_batch, texts_es)

    @staticmethod
    def get_cache_size() -> int:
        return len(_cache)


translation_service = TranslationService()

# app/services/loaders/__init__.py
"""
Loaders de bases externas — Fase 3 del pipeline v3.

Cargan al startup datos autoritativos en SQLite local:
  - Codex Alimentarius INS (aditivos oficiales)
  - Open Food Facts ingredients taxonomy

Reemplazan las listas hardcodeadas en app/config/tier1_data/.
"""

from app.services.loaders.codex_ins_loader import (
    CodexInsLoader,
    codex_ins_loader,
)
from app.services.loaders.off_taxonomy_loader import (
    OffTaxonomyLoader,
    off_taxonomy_loader,
)

__all__ = [
    "CodexInsLoader",
    "codex_ins_loader",
    "OffTaxonomyLoader",
    "off_taxonomy_loader",
]

"""Revalidación de las imágenes de la demo.

Uso (desde backend/):
    python scripts/evaluar_imagenes.py                 # usa ../demo_final
    python scripts/evaluar_imagenes.py ../otra_carpeta

Corre el pipeline completo sobre cada imagen y muestra qué restricciones
bloquea, por qué ingrediente, con qué explicación, y si el veredicto salió
por declaración legal o por deducción. Gasta 1 llamada a Gemini por imagen.
"""
import asyncio, sys, os, glob, time, json

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.getcwd())

from app.database.connection import SessionLocal, init_database
from app.services.analysis_pipeline import analysis_pipeline

RESTRICCIONES = ["sin_tacc", "sin_lactosa", "sin_frutos_secos", "vegano"]
CARPETA = sys.argv[1] if len(sys.argv) > 1 else os.path.join("..", "demo_final")


async def main():
    init_database()
    db = SessionLocal()
    salida = []
    rutas = sorted(glob.glob(os.path.join(CARPETA, "*.jp*g")) + glob.glob(os.path.join(CARPETA, "*.png")))
    for ruta in rutas:
        nombre = os.path.basename(ruta)
        with open(ruta, "rb") as f:
            data = f.read()
        tipo = "image/png" if ruta.lower().endswith(".png") else "image/jpeg"
        t0 = time.time()
        r = await analysis_pipeline.run(image_data=data, image_type=tipo,
                                        user_restrictions=RESTRICCIONES, db=db)
        dur = time.time() - t0
        print("=" * 78)
        print(f"{nombre}   {dur:.1f}s   ok={r.success}")
        if not r.success:
            print("   ERROR:", r.error_type, r.error)
            continue
        decl = r.declaration
        print(f"   declaración legal -> contiene={sorted(decl.contains) if decl else []} "
              f"puede_contener={sorted(decl.may_contain) if decl else []}")
        ings = [f.name_es for f in r.ingredient_facts]
        print(f"   ingredientes ({len(ings)}): {', '.join(ings)}")
        for rest, v in r.restrictions.items():
            motivo = v.motivo or ""
            estado = "APTO   " if v.apto else "NO APTO"
            fuente = "declaración legal" if "eclaraci" in motivo else ("DEDUCCIÓN" if not v.apto else "")
            print(f"   [{rest:17}] {estado}  {('(' + fuente + ')  ') if fuente else ''}{motivo[:90]}")
            for t in v.trigger_ingredients:
                print(f"        · {t.name}  ->  {t.explanation}")
        s = r.stats
        print(f"   stats: gemini={s.gemini_calls}  legal={s.resolved_by_legal} codex={s.resolved_by_codex} "
              f"off={s.resolved_by_off} kb={s.resolved_by_kb} pubchem={s.resolved_by_pubchem} "
              f"llm={s.resolved_by_llm} sin_resolver={s.unresolved}")
        salida.append({"imagen": nombre, "seg": round(dur, 1),
                       "restricciones": {k: {"apto": v.apto, "motivo": v.motivo,
                                             "triggers": [(t.name, t.explanation) for t in v.trigger_ingredients]}
                                         for k, v in r.restrictions.items()}})
    db.close()
    with open("evaluacion_imagenes.json", "w", encoding="utf-8") as f:
        json.dump(salida, f, indent=2, ensure_ascii=False)
    print(f"\n{len(salida)} imágenes evaluadas. Detalle en evaluacion_imagenes.json")


asyncio.run(main())

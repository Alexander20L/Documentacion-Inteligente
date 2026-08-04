import tempfile
import unittest
import hashlib
import shutil
from unittest.mock import patch
from pathlib import Path

from fastapi import HTTPException

from c4core import CandidateElement, CandidateRelationship, ElementKind, Provenance
from configuracion import rutas_c4
from configuracion import rutas_repositorios
from configuracion.rutas_repositorios import ruta_contenida, token_almacenamiento
from modelos.c4 import RevisionC4
from routers import c4 as router_c4
from servicios.c4_revision import (
    actualizar_contenido_revision,
    candidatos_detectados_contexto,
    crear_contenido_revision,
    materializar_revision,
    revision_publica,
)
from servicios.c4_archivos import metadata_artefacto
from servicios.c4_pipeline import _comando_structurizr
from servicios.servicio_graphify import (
    argumentos_agrupacion_graphify,
    argumentos_extraccion_graphify,
    argumentos_llm_graphify,
    validar_configuracion_llm,
)


class PathSafetyTests(unittest.TestCase):
    @patch.dict("os.environ", {"C4_LLM_PROVIDER": "ollama", "C4_OLLAMA_MODEL": "qwen3:8b"}, clear=False)
    def test_graphify_uses_local_ollama_without_api_key(self) -> None:
        self.assertEqual(
            argumentos_llm_graphify(),
            ["--backend", "ollama", "--model", "qwen3:8b", "--max-concurrency", "1"],
        )
        self.assertEqual(argumentos_extraccion_graphify(), ["--code-only"])
        self.assertEqual(argumentos_agrupacion_graphify(), ["--no-label"])
        validar_configuracion_llm({})

    def test_structurizr_jar_uses_distribution_classpath(self) -> None:
        command = _comando_structurizr("java-bin", "tools/structurizr/lib/structurizr-cli.jar")
        self.assertEqual(
            command,
            [
                "java-bin",
                "-cp",
                str(Path("tools/structurizr/lib") / "*"),
                "com.structurizr.cli.StructurizrCliApplication",
            ],
        )

    def test_rejects_paths_outside_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "runs"
            base.mkdir()
            self.assertEqual(ruta_contenida(base, "repo", "run").parent.name, "repo")
            with self.assertRaises(ValueError):
                ruta_contenida(base, "..", "escape")

    def test_artifact_path_is_scoped_to_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = rutas_c4.C4_RUNS_DIR
            rutas_c4.C4_RUNS_DIR = Path(directory) / "r"
            try:
                ruta = rutas_c4.obtener_ruta_ejecucion("repo", "run", "artifacts/model.md")
                token = token_almacenamiento("execution", "run")
                self.assertEqual(ruta.relative_to(Path(directory).resolve()).as_posix(), f"r/{token}/artifacts/model.md")
                with self.assertRaises(ValueError):
                    rutas_c4.obtener_ruta_ejecucion("repo", "run", "../../../secret")
            finally:
                rutas_c4.C4_RUNS_DIR = original

    def test_attempt_paths_are_short_isolated_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = rutas_c4.C4_ANALYSIS_ATTEMPTS_DIR
            rutas_c4.C4_ANALYSIS_ATTEMPTS_DIR = Path(directory) / "a"
            try:
                first = rutas_c4.obtener_repositorio_intento_analisis("task-a", 1)
                retry = rutas_c4.obtener_repositorio_intento_analisis("task-a", 2)
                other = rutas_c4.obtener_repositorio_intento_analisis("task-b", 1)
                self.assertEqual(len(first.relative_to(Path(directory).resolve()).parts), 4)
                self.assertEqual(len({first, retry, other}), 3)
                self.assertTrue(rutas_c4.es_repositorio_intento_analisis(first))
                self.assertFalse(rutas_c4.es_repositorio_intento_analisis(Path(directory) / "ordinary"))
                with self.assertRaises(ValueError):
                    rutas_c4.obtener_repositorio_intento_analisis("task-a", 0)
            finally:
                rutas_c4.C4_ANALYSIS_ATTEMPTS_DIR = original

    def test_repository_storage_does_not_use_uploaded_identifier_as_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = rutas_repositorios.REPOS_DIR
            rutas_repositorios.REPOS_DIR = Path(directory)
            try:
                root = rutas_repositorios.obtener_raiz_repositorio("../repo with spaces/and/unicode-á")
                self.assertEqual(root.parent, Path(directory).resolve())
                self.assertEqual(len(root.name), 26)
                self.assertNotIn("repo", root.name)
            finally:
                rutas_repositorios.REPOS_DIR = original

    def test_deep_repository_keeps_names_when_copied_to_short_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            relative = Path(*(["nested-directory-name"] * 6)) / "module.py"
            file = source / relative
            file.parent.mkdir(parents=True)
            file.write_text("def example():\n    return True\n", encoding="utf-8")
            original = rutas_c4.C4_ANALYSIS_ATTEMPTS_DIR
            rutas_c4.C4_ANALYSIS_ATTEMPTS_DIR = base / "a"
            try:
                work = rutas_c4.obtener_repositorio_intento_analisis("task", 1)
                shutil.copytree(source, work)
                self.assertEqual((work / relative).read_text(encoding="utf-8"), file.read_text(encoding="utf-8"))
            finally:
                rutas_c4.C4_ANALYSIS_ATTEMPTS_DIR = original

    def test_artifact_metadata_uses_bytes_hash_size_and_media_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ruta = Path(directory) / "context.svg"
            contenido = b"<svg/>"
            ruta.write_bytes(contenido)
            metadata = metadata_artefacto(ruta)
            self.assertEqual(metadata["media_type"], "image/svg+xml")
            self.assertEqual(metadata["size"], len(contenido))
            self.assertEqual(metadata["sha256"], hashlib.sha256(contenido).hexdigest())

    def test_artifact_metadata_can_be_verified_without_external_tools(self) -> None:
        contenido = b"png-bytes"
        with patch.object(Path, "read_bytes", return_value=contenido) as leer:
            metadata = metadata_artefacto(Path("diagram.png"))
        leer.assert_called_once_with()
        self.assertEqual(metadata["media_type"], "image/png")
        self.assertEqual(metadata["sha256"], hashlib.sha256(contenido).hexdigest())


class ReviewContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.detected = CandidateElement(
            id="system",
            kind=ElementKind.SOFTWARE_SYSTEM,
            name="Orders",
            provenance=Provenance.DETECTED,
            evidence_ids=("ev",),
        )
        self.inferred = CandidateElement(
            id="api",
            kind=ElementKind.CONTAINER,
            name="API",
            parent_id="system",
            provenance=Provenance.INFERRED,
            evidence_ids=("ev",),
        )
        self.relationship = CandidateRelationship(
            id="uses",
            source_id="system",
            target_id="api",
            description="Uses",
            provenance=Provenance.INFERRED,
            evidence_ids=("ev",),
        )

    def test_public_shape_hash_and_decision_defaults(self) -> None:
        contenido = crear_contenido_revision((self.detected, self.inferred), (self.relationship,))
        publica = revision_publica(contenido)
        self.assertEqual(set(publica), {"hash", "version", "elementos", "relaciones"})
        decisiones = {item["id"]: item["decision"] for item in (*publica["elementos"], *publica["relaciones"])}
        self.assertEqual(decisiones, {"api": "PENDIENTE", "system": "APROBADO", "uses": "PENDIENTE"})
        self.assertEqual(publica["hash"], contenido["revision"]["hash"])

    def test_update_increments_version_and_requires_all_inferences_decided(self) -> None:
        contenido = crear_contenido_revision((self.detected, self.inferred), (self.relationship,))
        solicitud = RevisionC4.model_validate(revision_publica(contenido))
        with self.assertRaisesRegex(ValueError, "Todos los candidatos"):
            materializar_revision(contenido, "reviewer")
        for item in (*solicitud.elementos, *solicitud.relaciones):
            if item.inferido:
                item.decision = "APROBADO"
        actualizado = actualizar_contenido_revision(contenido, solicitud)
        publica = revision_publica(actualizado)
        self.assertEqual(publica["version"], 2)
        self.assertNotEqual(publica["hash"], solicitud.hash)
        elementos, relaciones, decisiones = materializar_revision(actualizado, "reviewer")
        self.assertEqual(len(elementos), 2)
        self.assertEqual(len(relaciones), 1)
        self.assertEqual({item.target_id for item in decisiones}, {"api", "uses"})

    def test_detected_analyst_candidates_are_stable(self) -> None:
        contexto = {
            "nombre_sistema": "Orders",
            "descripcion": "Order processing",
            "proposito": "Sell products",
            "actores": [{"nombre": "Buyer", "descripcion": "Customer"}],
            "sistemas_externos": [{"nombre": "Bank", "descripcion": "Payments"}],
        }
        primero, sistema = candidatos_detectados_contexto(contexto, "ev")
        segundo, _ = candidatos_detectados_contexto(contexto, "ev")
        self.assertEqual(primero, segundo)
        self.assertEqual(len(primero), 3)
        self.assertIn(sistema, {item.id for item in primero})
        self.assertTrue(all(item.provenance == Provenance.ANALYST_PROVIDED for item in primero))


class ExploradorC4Tests(unittest.TestCase):
    def _run_explorador(self) -> tuple[dict, dict]:
        ejecucion = {"id": "ejec-1", "id_repositorio": "repo-1", "estado": "completado", "resultado": {"fase": "completado"}}
        revision_contenido = {
            "revision": {"hash": "h1", "version": 1, "elementos": [], "relaciones": []},
            "candidatos": {"elementos": [], "relaciones": []},
        }
        with patch("routers.c4.obtener_proyecto_del_usuario", lambda *a, **k: None), \
             patch("routers.c4.obtener_cliente_usuario", lambda *a, **k: object()), \
             patch("routers.c4._obtener_ejecucion", lambda c, r, e: dict(ejecucion)), \
             patch("routers.c4._obtener_revision", lambda c, e: {"contenido": revision_contenido}), \
             patch("routers.c4._obtener_tarea_actual", lambda c, e: None):
            respuesta = respuesta_falsa()
            resultado = router_c4.obtener_explorador("repo-1", "ejec-1", respuesta, objeto_usuario())
            return resultado, respuesta.headers

    def test_explorador_devuelve_revision_y_header(self) -> None:
        resultado, headers = self._run_explorador()
        self.assertEqual(resultado["ejecucion"]["estado"], "completado")
        self.assertEqual(resultado["revision"]["hash"], "h1")
        self.assertNotIn("graph", resultado)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

def objeto_usuario():
    from types import SimpleNamespace
    return SimpleNamespace(id="usuario-1")


def respuesta_falsa():
    from types import SimpleNamespace
    return SimpleNamespace(headers={})


if __name__ == "__main__":
    unittest.main()

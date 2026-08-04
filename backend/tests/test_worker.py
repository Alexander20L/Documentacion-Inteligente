import time
import unittest
from unittest.mock import Mock, patch

import httpx

from worker import _heartbeat_rpc_reintentable, procesar_tarea


class HeartbeatRetryTests(unittest.TestCase):
    def test_retries_transient_transport_error_then_succeeds(self) -> None:
        resultado = Mock()
        llamadas = []

        def func():
            llamadas.append(1)
            if len(llamadas) == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return resultado

        self.assertIs(
            _heartbeat_rpc_reintentable(func, "tarea-1", 1, sleep=lambda _segundos: None),
            resultado,
        )
        self.assertEqual(len(llamadas), 2)

    def test_raises_after_retries_exhausted(self) -> None:
        llamadas = []

        def func():
            llamadas.append(1)
            raise httpx.RemoteProtocolError("Server disconnected")

        with self.assertRaises(httpx.RemoteProtocolError):
            _heartbeat_rpc_reintentable(func, "tarea-1", 1, sleep=lambda _segundos: None)
        self.assertGreaterEqual(len(llamadas), 2)

    def test_propagates_non_transport_errors_immediately(self) -> None:
        llamadas = []

        def func():
            llamadas.append(1)
            raise RuntimeError("El heartbeat no devolvió la tarea")

        with self.assertRaisesRegex(RuntimeError, "no devolvió"):
            _heartbeat_rpc_reintentable(func, "tarea-1", 1, sleep=lambda _segundos: None)
        self.assertEqual(len(llamadas), 1)


class ProcesarTareaHeartbeatTests(unittest.TestCase):
    def _tarea(self) -> dict:
        return {
            "id": "tarea-1",
            "tipo": "analisis_c4",
            "id_repositorio": "repo-1",
            "usuario_id": "usuario-1",
            "intentos": 1,
            "progreso": 0,
            "fase": "ingesta",
            "paso": None,
            "mensaje": None,
            "unidades_completadas": None,
            "unidades_totales": None,
            "ejecucion_c4_id": "ejecucion-1",
            "payload": {},
        }

    def _admin_con_heartbeat(self, heartbeat_llamadas: dict):
        admin = Mock()
        admin.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"usuario_id": "usuario-1"}
        ]

        def rpc(nombre, *_args, **_kwargs):
            if nombre == "heartbeat_tarea_proyecto":
                heartbeat_llamadas["n"] += 1
                if heartbeat_llamadas["n"] == 1:
                    raise httpx.RemoteProtocolError("Server disconnected")
                return Mock(data=[{"id": "tarea-1"}])
            return Mock(data=[])

        admin.rpc.side_effect = rpc
        return admin

    def test_progress_heartbeat_survives_transient_transport_error(self) -> None:
        tarea = self._tarea()
        heartbeat_llamadas = {"n": 0}
        admin = self._admin_con_heartbeat(heartbeat_llamadas)

        progresos: list[tuple[str, ...]] = []

        def ejecutar_analisis(tarea_arg, heartbeat):
            heartbeat(50, "descubrimiento", "analizar_modulos", "Módulo 1/2", 1, 2)
            heartbeat(100, "revision", "revision_humana", "Esperando revisión humana", None, None)
            progresos.append(("ok",))

        completar = Mock()
        fallar = Mock()
        with patch("worker.supabase_admin", admin), \
             patch("worker.ejecutar_analisis_c4", ejecutar_analisis), \
             patch("worker.preparar_resultado_revision_c4", return_value={}), \
             patch("worker.completar_analisis_c4_rpc", completar), \
             patch("worker.fallar_tarea_c4_rpc", fallar), \
             patch.dict("os.environ", {"WORKER_HEARTBEAT_RETRY_ATTEMPTS": "1"}):
            procesar_tarea(tarea)

        self.assertEqual(heartbeat_llamadas["n"], 2)
        self.assertEqual(progresos, [("ok",)])
        completar.assert_called_once()
        fallar.assert_not_called()

    def test_lease_thread_survives_transient_transport_error(self) -> None:
        tarea = self._tarea()
        heartbeat_llamadas = {"n": 0}
        admin = self._admin_con_heartbeat(heartbeat_llamadas)

        def ejecutar_analisis(tarea_arg, heartbeat):
            time.sleep(1.2)

        completar = Mock()
        fallar = Mock()
        with patch("worker.supabase_admin", admin), \
             patch("worker.ejecutar_analisis_c4", ejecutar_analisis), \
             patch("worker.preparar_resultado_revision_c4", return_value={}), \
             patch("worker.completar_analisis_c4_rpc", completar), \
             patch("worker.fallar_tarea_c4_rpc", fallar), \
             patch("worker.LEASE_SECONDS", 3), \
             patch.dict("os.environ", {
                 "WORKER_HEARTBEAT_RETRY_ATTEMPTS": "1",
                 "WORKER_LEASE_RENEW_FLOOR_SECONDS": "0",
             }):
            procesar_tarea(tarea)

        self.assertGreaterEqual(heartbeat_llamadas["n"], 1)
        completar.assert_called_once()
        fallar.assert_not_called()


if __name__ == "__main__":
    unittest.main()

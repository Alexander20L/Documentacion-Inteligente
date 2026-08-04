import unittest

from servicios.c4_pipeline import filtrar_diagramas_publicados


class FiltrarDiagramasPublicadosTests(unittest.TestCase):
    def test_include_plantuml_svg(self) -> None:
        registros = [
            {
                "id": "a1",
                "nombre": "structurizr-context_element_x.svg",
                "tipo": "diagrama",
                "metadata": {"formato": "svg", "nivel": "context", "ruta_logica": "artifacts/plantuml/structurizr-context_element_x.svg"},
            }
        ]
        resultado = filtrar_diagramas_publicados(registros)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["nivel"], "context")
        self.assertEqual(resultado[0]["origen"], "plantuml")

    def test_include_mermaid_svg_with_origen(self) -> None:
        registros = [
            {
                "id": "a1",
                "nombre": "structurizr-context_element_x.svg",
                "tipo": "diagrama",
                "metadata": {"formato": "svg", "nivel": "context", "ruta_logica": "artifacts/mermaid/structurizr-context_element_x.svg"},
            }
        ]
        resultado = filtrar_diagramas_publicados(registros)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["origen"], "mermaid")

    def test_exclude_plantuml_png(self) -> None:
        registros = [
            {
                "id": "a1",
                "nombre": "structurizr-context_element_x.png",
                "tipo": "diagrama",
                "metadata": {"formato": "png", "nivel": "context", "ruta_logica": "artifacts/plantuml/structurizr-context_element_x.png"},
            }
        ]
        self.assertEqual(filtrar_diagramas_publicados(registros), [])

    def test_exclude_non_diagram_svg(self) -> None:
        registros = [
            {
                "id": "a1",
                "nombre": "graph.svg",
                "tipo": "indice_semantico",
                "metadata": {"formato": "svg", "nivel": "context", "ruta_logica": "semantic/graph.svg"},
            }
        ]
        self.assertEqual(filtrar_diagramas_publicados(registros), [])


if __name__ == "__main__":
    unittest.main()

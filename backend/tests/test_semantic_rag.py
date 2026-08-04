import hashlib
import io
import unittest
import urllib.error
from unittest.mock import patch

from semantic_rag import (
    DifyAPIError,
    DifyConfig,
    DifyKnowledgeIndex,
    InMemoryKnowledgeIndex,
    PublicationPolicy,
    PythonSemanticParser,
    SecurityScanner,
    SymbolKind,
    TypeScriptSemanticParser,
    ingest_python,
)


class _FakeDifyIndex(DifyKnowledgeIndex):
    def __init__(self, responses):
        super().__init__(DifyConfig(base_url="http://dify.test", api_key="test"))
        self.responses = list(responses)
        self.requests = []

    def _request(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if not self.responses:
            raise AssertionError(f"Unexpected Dify request: {method} {path}")
        return self.responses.pop(0)


PYTHON_SOURCE = '''from fastapi import FastAPI

app = FastAPI()

class Service:
    """Application service."""

    def first(self, value: str) -> str:
        return value.strip()

    def second(self) -> None:
        self.first("x")

@app.get("/items/{item_id}")
async def item(item_id: int) -> dict:
    return {"id": item_id}
'''


class PythonSemanticParserTests(unittest.TestCase):
    def test_oversized_class_splits_only_on_whole_method_boundaries(self) -> None:
        chunks = PythonSemanticParser(max_class_chars=80).parse(
            PYTHON_SOURCE, "src/api.py", tenant_id="tenant-a", repository_id="repo-a"
        )
        service = next(chunk for chunk in chunks if chunk.symbol.qualified_name == "src.api.Service")
        first = next(chunk for chunk in chunks if chunk.symbol.qualified_name == "src.api.Service.first")
        second = next(chunk for chunk in chunks if chunk.symbol.qualified_name == "src.api.Service.second")
        self.assertEqual(service.symbol.kind, SymbolKind.CLASS)
        self.assertNotIn("return value.strip()", service.content)
        self.assertEqual(first.parent_chunk_id, service.id)
        self.assertEqual(second.parent_chunk_id, service.id)
        self.assertTrue(first.content.startswith("def first"))
        self.assertIn("return value.strip()", first.content)
        self.assertEqual((first.symbol.start_line, first.symbol.end_line), (8, 9))

    def test_detects_fastapi_route_decorator(self) -> None:
        chunks = PythonSemanticParser().parse(
            PYTHON_SOURCE, "src/api.py", tenant_id="tenant-a", repository_id="repo-a"
        )
        route = next(chunk for chunk in chunks if chunk.symbol.name == "item")
        self.assertEqual(route.symbol.kind, SymbolKind.ROUTE)
        self.assertIn("fastapi_route", route.symbol.framework_roles)
        self.assertEqual(route.symbol.decorators, ("app.get('/items/{item_id}')",))

    def test_chunk_identity_is_stable_and_source_sensitive(self) -> None:
        parser = PythonSemanticParser()
        first = parser.parse(PYTHON_SOURCE, "src/api.py", tenant_id="t", repository_id="r")
        second = parser.parse(PYTHON_SOURCE, "src/api.py", tenant_id="t", repository_id="r")
        changed = parser.parse(PYTHON_SOURCE + "\n# change\n", "src/api.py", tenant_id="t", repository_id="r")
        self.assertEqual([chunk.id for chunk in first], [chunk.id for chunk in second])
        self.assertNotEqual(first[0].id, changed[0].id)


class SecurityScannerTests(unittest.TestCase):
    def test_denied_file_is_not_ingested_and_report_has_no_content(self) -> None:
        secret = "do-not-leak-this-value"
        chunks, report = ingest_python(
            f"PASSWORD={secret!r}", ".env", tenant_id="t", repository_id="r"
        )
        self.assertEqual(chunks, ())
        self.assertFalse(report.allowed)
        self.assertIsNone(report.redacted_text)
        self.assertNotIn(secret, report.model_dump_json())

    def test_text_secret_is_redacted_before_parsing(self) -> None:
        secret = "abcdefghijklmnopqrstuvwxyz"
        result = SecurityScanner().scan("settings.py", f'API_KEY = "{secret}"\n')
        self.assertTrue(result.allowed)
        self.assertEqual(result.policy, PublicationPolicy.REDACT)
        self.assertNotIn(secret, result.redacted_text or "")
        self.assertNotIn(secret, result.model_dump_json())
        self.assertIn("[REDACTED]", result.redacted_text or "")

    def test_token_expression_is_not_redacted_or_made_invalid(self) -> None:
        source = '''def authorization(api_key: str):
    token_prefix, token = api_key.split(" ")
    return token_prefix, token
'''
        result = SecurityScanner().scan("authentication.py", source)
        self.assertEqual(result.policy, PublicationPolicy.INDEX)
        self.assertEqual(result.redacted_text, source)
        chunks = PythonSemanticParser().parse(
            result.redacted_text or "", "authentication.py", tenant_id="t", repository_id="r",
        )
        self.assertEqual(tuple(item.symbol.name for item in chunks), ("authorization",))

    def test_quoted_secret_redaction_preserves_python_syntax(self) -> None:
        source = 'API_KEY = "abcdefghijklmnopqrstuvwxyz"\ndef configured():\n    return bool(API_KEY)\n'
        result = SecurityScanner().scan("settings.py", source)
        self.assertEqual(result.policy, PublicationPolicy.REDACT)
        self.assertIn('API_KEY = "[REDACTED]"', result.redacted_text or "")
        PythonSemanticParser().parse(
            result.redacted_text or "", "settings.py", tenant_id="t", repository_id="r",
        )

    def test_unquoted_code_reference_is_not_redacted(self) -> None:
        source = "TOKEN = application_token\n"
        result = SecurityScanner().scan("settings.py", source)
        self.assertEqual(result.redacted_text, source)
        self.assertEqual(result.policy, PublicationPolicy.INDEX)

    def test_unquoted_configuration_secret_is_redacted(self) -> None:
        result = SecurityScanner().scan("deployment.yaml", "token: abcdefghijklmnop\n")
        self.assertEqual(result.policy, PublicationPolicy.REDACT)
        self.assertEqual(result.redacted_text, "token: [REDACTED]\n")

    def test_sql_migration_is_not_excluded_by_default(self) -> None:
        result = SecurityScanner().scan("migrations/001_schema.sql", "create table orders(id uuid);")
        self.assertTrue(result.allowed)

    def test_denied_file_matching_is_case_insensitive(self) -> None:
        result = SecurityScanner().scan("config/Secrets.JSON", "not parsed")
        self.assertFalse(result.allowed)

    def test_multiline_redaction_preserves_line_numbers(self) -> None:
        source = """-----BEGIN PRIVATE KEY-----
secret material
-----END PRIVATE KEY-----
def service():
    return True
"""
        result = SecurityScanner().scan("settings.py", source)
        self.assertEqual((result.redacted_text or "").count("\n"), source.count("\n"))
        chunks = PythonSemanticParser().parse(
            result.redacted_text or "", "settings.py", tenant_id="t", repository_id="r",
        )
        service = next(item for item in chunks if item.symbol.name == "service")
        self.assertEqual(service.symbol.start_line, 4)


class TypeScriptSemanticParserTests(unittest.TestCase):
    def test_detects_angular_component_and_http_dependency(self) -> None:
        source = '''import { Component } from '@angular/core';

@Component({ selector: 'app-orders', template: '' })
export class OrdersComponent {
  load() { return this.http.get('/api/orders'); }
}
'''
        chunks = TypeScriptSemanticParser().parse(
            source,
            "src/app/orders/orders.component.ts",
            tenant_id="tenant-a",
            repository_id="repo-a",
        )
        component = next(item for item in chunks if item.symbol.name == "OrdersComponent")
        self.assertIn("angular_component", component.symbol.framework_roles)
        self.assertTrue(any("http.get" in item.target for item in component.dependencies))


class InMemoryIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        parser = PythonSemanticParser()
        self.alpha = parser.parse(
            "def search():\n    return 'needle'\n", "a.py", tenant_id="alpha", repository_id="repo"
        )[0]
        self.beta = parser.parse(
            "def search():\n    return 'needle'\n", "b.py", tenant_id="beta", repository_id="repo"
        )[0]

    def test_retrieval_enforces_tenant_repository_and_source(self) -> None:
        index = InMemoryKnowledgeIndex()
        index.index_chunks((self.alpha, self.beta))
        result = index.retrieve(
            "needle", tenant_id="alpha", repository_id="repo", source_hash=self.alpha.source_hash
        )
        self.assertEqual(tuple(hit.chunk_id for hit in result.hits), (self.alpha.id,))

    def test_retrieval_rejects_stale_local_hash(self) -> None:
        index = InMemoryKnowledgeIndex()
        index.index_chunks((self.alpha,))
        key = (self.alpha.tenant_id, self.alpha.repository_id, self.alpha.source_hash, self.alpha.id)
        index._chunks[key] = self.alpha.model_copy(update={"content": self.alpha.content + " stale"})
        result = index.retrieve(
            "needle", tenant_id="alpha", repository_id="repo", source_hash=self.alpha.source_hash
        )
        self.assertEqual(result.hits, ())
        self.assertEqual(result.audit.rejected_stale, 1)

    def test_identical_chunks_remain_isolated_between_tenants(self) -> None:
        parser = PythonSemanticParser()
        alpha = parser.parse("def search():\n    return 'needle'\n", "same.py", tenant_id="alpha", repository_id="repo")[0]
        beta = parser.parse("def search():\n    return 'needle'\n", "same.py", tenant_id="beta", repository_id="repo")[0]
        self.assertEqual(alpha.id, beta.id)
        index = InMemoryKnowledgeIndex()
        index.index_chunks((alpha, beta))
        for tenant in ("alpha", "beta"):
            result = index.retrieve("needle", tenant_id=tenant, repository_id="repo", source_hash=alpha.source_hash)
            self.assertEqual(tuple(hit.chunk_id for hit in result.hits), (alpha.id,))


class DifyIndexTests(unittest.TestCase):
    def test_retrieve_rejects_query_over_dify_limit_before_request(self) -> None:
        index = _FakeDifyIndex([])
        with self.assertRaisesRegex(ValueError, "at most 250"):
            index.retrieve("x" * 251, tenant_id="tenant", repository_id="repo", source_hash="source")
        self.assertEqual(index.requests, [])

    def test_retrieve_sends_complete_dify_retrieval_model(self) -> None:
        index = _FakeDifyIndex([{"records": []}])
        index._datasets[("tenant", "repo", "source")] = "dataset"

        index.retrieve("query", tenant_id="tenant", repository_id="repo", source_hash="source", limit=7)

        self.assertEqual(index.requests, [(
            "POST",
            "/v1/datasets/dataset/retrieve",
            {
                "query": "query",
                "retrieval_model": {
                    "search_method": "semantic_search",
                    "reranking_enable": False,
                    "top_k": 7,
                    "score_threshold_enabled": False,
                },
            },
        )])

    def test_http_error_includes_dify_response_body(self) -> None:
        error = urllib.error.HTTPError(
            "http://dify.test/v1/datasets",
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"code":"invalid_param","message":"reranking_enable is required"}'),
        )
        index = DifyKnowledgeIndex(DifyConfig(base_url="http://dify.test", api_key="test"))

        with patch("semantic_rag.dify.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(DifyAPIError, "reranking_enable is required"):
                index._request("POST", "/v1/datasets/dataset/retrieve", {"query": "query"})

    def test_dataset_discovery_paginates(self) -> None:
        name = "semantic-" + hashlib.sha256("tenant\0repo\0source".encode()).hexdigest()[:20]
        index = _FakeDifyIndex([
            {"data": [{"id": "other", "name": "other"}], "has_more": True},
            {"data": [{"id": "expected", "name": name}], "has_more": False},
        ])
        dataset_id = index.ensure_dataset(tenant_id="tenant", repository_id="repo", source_hash="source")
        self.assertEqual(dataset_id, "expected")
        self.assertEqual(index.requests[1][1], "/v1/datasets?page=2&limit=100")

    def test_changed_chunk_replaces_stale_remote_document(self) -> None:
        chunk = PythonSemanticParser().parse(
            "def search():\n    return 'new'\n", "same.py", tenant_id="tenant", repository_id="repo",
        )[0]
        index = _FakeDifyIndex([
            {"data": [{"id": "old-document", "name": chunk.id}], "has_more": False},
            {},
            {"document": {"id": "new-document"}},
        ])
        scope = (chunk.tenant_id, chunk.repository_id, chunk.source_hash)
        index._datasets[scope] = "dataset"
        index._document_refs[("dataset", chunk.id)] = ("old-document", "0" * 64)
        index.index_chunks((chunk,))
        self.assertEqual(index.requests[1][:2], ("DELETE", "/v1/datasets/dataset/documents/old-document"))
        self.assertEqual(index._document_refs[("dataset", chunk.id)], ("new-document", chunk.chunk_hash))


if __name__ == "__main__":
    unittest.main()

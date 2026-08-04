from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Iterator

from .identity import sha256_text, stable_chunk_hash, stable_chunk_id
from .models import DependencyRecord, ImportRecord, Language, PublicationPolicy, SemanticChunk, SymbolKind, SymbolRecord, Visibility
from .security import SecurityScanner

PARSER_VERSION = "tree-sitter-typescript-v1"


class TypeScriptCapabilityError(RuntimeError):
    pass


def _load_parser() -> Any:
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_typescript
    except ImportError as exc:
        raise TypeScriptCapabilityError(
            "TypeScript parsing requires optional packages 'tree-sitter' and 'tree-sitter-typescript'"
        ) from exc
    language_value = tree_sitter_typescript.language_typescript()
    try:
        language = Language(language_value)
    except TypeError:
        language = language_value
    try:
        return Parser(language)
    except TypeError:
        parser = Parser()
        parser.language = language
        return parser


def _walk(node: Any) -> Iterator[Any]:
    yield node
    for child in node.named_children:
        yield from _walk(child)


class TypeScriptSemanticParser:
    parser_version = PARSER_VERSION

    def __init__(self) -> None:
        self._parser = _load_parser()

    def parse(
        self, source: str, source_path: str, *, tenant_id: str, repository_id: str,
        source_hash: str | None = None, publication_policy: PublicationPolicy = PublicationPolicy.INDEX,
    ) -> tuple[SemanticChunk, ...]:
        encoded = source.encode("utf-8")
        tree = self._parser.parse(encoded)
        if tree.root_node.has_error:
            raise SyntaxError(f"Tree-sitter could not parse {source_path}")
        source_hash = source_hash or sha256_text(source)
        module = ".".join(PurePosixPath(source_path.replace("\\", "/")).with_suffix("").parts)

        def text(node: Any) -> str:
            return encoded[node.start_byte:node.end_byte].decode("utf-8")

        imports: list[ImportRecord] = []
        for node in tree.root_node.named_children:
            if node.type == "import_statement":
                source_node = node.child_by_field_name("source")
                imports.append(ImportRecord(module=text(source_node).strip("'\"") if source_node else "", line=node.start_point[0] + 1))

        chunks: list[SemanticChunk] = []
        symbol_types = {
            "class_declaration": SymbolKind.CLASS,
            "function_declaration": SymbolKind.FUNCTION,
            "method_definition": SymbolKind.METHOD,
        }
        for node in _walk(tree.root_node):
            kind = symbol_types.get(node.type)
            if kind is None:
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = text(name_node)
            parent_class = next((text(item.child_by_field_name("name")) for item in _walk(tree.root_node) if item.type == "class_declaration" and item.start_byte < node.start_byte < item.end_byte and item.child_by_field_name("name")), None)
            qualified = ".".join(filter(None, (module, parent_class if kind == SymbolKind.METHOD else None, name)))
            decorator_nodes = [item for item in node.named_children if item.type == "decorator"]
            if node.parent is not None:
                decorator_nodes.extend(
                    item for item in node.parent.named_children
                    if item.type == "decorator" and item not in decorator_nodes
                )
            decorators = tuple(text(item) for item in decorator_nodes)
            roles: list[str] = []
            decorator_names = " ".join(decorators)
            for marker, role in (("Component", "angular_component"), ("Injectable", "angular_injectable")):
                if marker in decorator_names:
                    roles.append(role)
            body_text = text(node)
            if "CanActivate" in body_text:
                roles.append("angular_guard")
            if "HttpInterceptor" in body_text or name.endswith("Interceptor"):
                roles.append("angular_interceptor")
            calls = tuple(
                DependencyRecord(target=text(item.child_by_field_name("function")), kind="call", line=item.start_point[0] + 1)
                for item in _walk(node) if item.type == "call_expression" and item.child_by_field_name("function")
            )
            if any(target in dependency.target for dependency in calls for target in ("http.get", "http.post", "http.put", "http.patch", "http.delete")):
                roles.append("http_client")
            symbol = SymbolRecord(
                name=name, qualified_name=qualified, kind=kind,
                visibility=Visibility.PRIVATE if name.startswith("#") else Visibility.PUBLIC,
                start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                signature=text(node.child_by_field_name("parameters")) if node.child_by_field_name("parameters") else "",
                decorators=decorators, framework_roles=tuple(dict.fromkeys(roles)),
            )
            content = text(node)
            chunk_id = stable_chunk_id(source_hash, source_path, qualified, self.parser_version)
            chunks.append(SemanticChunk(
                id=chunk_id, chunk_hash=stable_chunk_hash(chunk_id, content), source_hash=source_hash,
                tenant_id=tenant_id, repository_id=repository_id, source_path=source_path.replace("\\", "/"),
                language=Language.TYPESCRIPT, parser_version=self.parser_version, symbol=symbol,
                content=content, imports=tuple(imports), dependencies=calls, publication_policy=publication_policy,
            ))
        for node in _walk(tree.root_node):
            if node.type != "variable_declarator":
                continue
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if name_node is None or value_node is None or text(name_node).casefold() not in ("routes", "approutes"):
                continue
            name = text(name_node)
            qualified = f"{module}.{name}"
            content = text(node)
            symbol = SymbolRecord(
                name=name, qualified_name=qualified, kind=SymbolKind.MODULE, visibility=Visibility.PUBLIC,
                start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                framework_roles=("angular_routes",),
            )
            chunk_id = stable_chunk_id(source_hash, source_path, qualified, self.parser_version)
            chunks.append(SemanticChunk(
                id=chunk_id, chunk_hash=stable_chunk_hash(chunk_id, content), source_hash=source_hash,
                tenant_id=tenant_id, repository_id=repository_id, source_path=source_path.replace("\\", "/"),
                language=Language.TYPESCRIPT, parser_version=self.parser_version, symbol=symbol,
                content=content, imports=tuple(imports), publication_policy=publication_policy,
            ))
        return tuple(chunks)


def ingest_typescript(
    source: str,
    source_path: str,
    *,
    tenant_id: str,
    repository_id: str,
    scanner: SecurityScanner | None = None,
    parser: TypeScriptSemanticParser | None = None,
):
    scanner = scanner or SecurityScanner()
    result = scanner.scan(source_path, source)
    if not result.allowed:
        return (), result
    chunks = (parser or TypeScriptSemanticParser()).parse(
        result.redacted_text or "", source_path, tenant_id=tenant_id, repository_id=repository_id,
        source_hash=sha256_text(source), publication_policy=result.policy,
    )
    return chunks, result

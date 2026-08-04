from __future__ import annotations

import ast
from pathlib import PurePosixPath

from .identity import sha256_text, stable_chunk_hash, stable_chunk_id
from .models import (
    DependencyRecord,
    ImportRecord,
    Language,
    PublicationPolicy,
    SemanticChunk,
    SymbolKind,
    SymbolRecord,
    Visibility,
)
from .security import SecurityScanner

PARSER_VERSION = "python-ast-v1"


def _name(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (ValueError, TypeError):
        return node.__class__.__name__


def _visibility(name: str) -> Visibility:
    if name.startswith("__") and not name.endswith("__"):
        return Visibility.PRIVATE
    if name.startswith("_"):
        return Visibility.PROTECTED
    return Visibility.PUBLIC


def _module_name(path: str) -> str:
    normalized = str(PurePosixPath(path.replace("\\", "/")))
    without_suffix = normalized[:-3] if normalized.endswith(".py") else normalized
    parts = [part for part in without_suffix.split("/") if part not in (".", "__init__")]
    return ".".join(parts) or "module"


def _imports(tree: ast.Module) -> tuple[ImportRecord, ...]:
    records: list[ImportRecord] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                records.append(ImportRecord(module=item.name, alias=item.asname, line=node.lineno))
        elif isinstance(node, ast.ImportFrom):
            records.append(
                ImportRecord(
                    module=("." * node.level) + (node.module or ""),
                    names=tuple(item.name for item in node.names),
                    line=node.lineno,
                )
            )
    return tuple(records)


def _dependencies(node: ast.AST) -> tuple[DependencyRecord, ...]:
    return tuple(
        DependencyRecord(target=_name(item.func), kind="call", line=item.lineno)
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
    )


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> tuple[str, ...]:
    return tuple(_name(item) for item in node.decorator_list)


def _roles(node: ast.AST, decorators: tuple[str, ...], bases: tuple[str, ...]) -> tuple[str, ...]:
    roles: list[str] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        route_methods = {"get", "post", "put", "patch", "delete", "options", "head", "websocket", "api_route"}
        if any(item.rsplit(".", 1)[-1].split("(", 1)[0] in route_methods for item in decorators):
            roles.append("fastapi_route")
        argument_names = {argument.arg for argument in (*node.args.posonlyargs, *node.args.args)}
        if "request" in argument_names:
            roles.append("django_view")
    if isinstance(node, ast.ClassDef):
        if any(base.endswith(("models.Model", "Model")) for base in bases):
            roles.append("django_model")
        if any(base.endswith(("View", "APIView", "ViewSet")) for base in bases):
            roles.append("django_view")
    return tuple(roles)


def _symbol(node: ast.AST, qualified_name: str, kind: SymbolKind, bases: tuple[str, ...] = ()) -> SymbolRecord:
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    decorators = _decorators(node)
    if kind in (SymbolKind.FUNCTION, SymbolKind.METHOD) and "fastapi_route" in _roles(node, decorators, bases):
        kind = SymbolKind.ROUTE
    signature = ""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        signature = f"{prefix} {node.name}({_name(node.args)})"
        if node.returns:
            signature += f" -> {_name(node.returns)}"
    else:
        signature = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
    return SymbolRecord(
        name=node.name,
        qualified_name=qualified_name,
        kind=kind,
        visibility=_visibility(node.name),
        start_line=node.lineno,
        end_line=node.end_lineno or node.lineno,
        signature=signature,
        docstring=ast.get_docstring(node, clean=False),
        decorators=decorators,
        bases=bases,
        framework_roles=_roles(node, decorators, bases),
    )


class PythonSemanticParser:
    parser_version = PARSER_VERSION

    def __init__(self, *, max_class_chars: int = 24_000) -> None:
        self.max_class_chars = max_class_chars

    def parse(
        self,
        source: str,
        source_path: str,
        *,
        tenant_id: str,
        repository_id: str,
        source_hash: str | None = None,
        publication_policy: PublicationPolicy = PublicationPolicy.INDEX,
    ) -> tuple[SemanticChunk, ...]:
        tree = ast.parse(source, filename=source_path, type_comments=True)
        source_hash = source_hash or sha256_text(source)
        module = _module_name(source_path)
        imports = _imports(tree)
        chunks: list[SemanticChunk] = []

        def add(symbol: SymbolRecord, content: str, node: ast.AST, parent_id: str | None = None) -> SemanticChunk:
            chunk_id = stable_chunk_id(source_hash, source_path, symbol.qualified_name, self.parser_version)
            chunk = SemanticChunk(
                id=chunk_id,
                chunk_hash=stable_chunk_hash(chunk_id, content),
                source_hash=source_hash,
                tenant_id=tenant_id,
                repository_id=repository_id,
                source_path=source_path.replace("\\", "/"),
                language=Language.PYTHON,
                parser_version=self.parser_version,
                symbol=symbol,
                content=content,
                imports=imports,
                dependencies=_dependencies(node),
                publication_policy=publication_policy,
                parent_chunk_id=parent_id,
            )
            chunks.append(chunk)
            return chunk

        module_doc = ast.get_docstring(tree, clean=False)
        if imports or module_doc:
            import_lines = [ast.get_source_segment(source, node) or "" for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
            content = "\n".join(([module_doc] if module_doc else []) + import_lines)
            end_line = max((node.end_lineno or node.lineno for node in tree.body), default=1)
            symbol = SymbolRecord(
                name=module.rsplit(".", 1)[-1], qualified_name=module, kind=SymbolKind.MODULE,
                visibility=Visibility.PUBLIC, start_line=1, end_line=end_line, docstring=module_doc,
            )
            add(symbol, content, tree)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                content = ast.get_source_segment(source, node) or ""
                add(_symbol(node, f"{module}.{node.name}", SymbolKind.FUNCTION), content, node)
            elif isinstance(node, ast.ClassDef):
                qualified = f"{module}.{node.name}"
                bases = tuple(_name(base) for base in node.bases)
                content = ast.get_source_segment(source, node) or ""
                class_symbol = _symbol(node, qualified, SymbolKind.CLASS, bases)
                methods = [item for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
                if len(content) <= self.max_class_chars or not methods:
                    add(class_symbol, content, node)
                    continue
                method_names = ", ".join(item.name for item in methods)
                metadata = f"{class_symbol.signature}\n{class_symbol.docstring or ''}\nMethods: {method_names}".rstrip()
                parent = add(class_symbol, metadata, node)
                for method in methods:
                    method_content = ast.get_source_segment(source, method) or ""
                    add(_symbol(method, f"{qualified}.{method.name}", SymbolKind.METHOD, bases), method_content, method, parent.id)
        return tuple(chunks)


def ingest_python(
    source: str,
    source_path: str,
    *,
    tenant_id: str,
    repository_id: str,
    scanner: SecurityScanner | None = None,
    parser: PythonSemanticParser | None = None,
):
    scanner = scanner or SecurityScanner()
    result = scanner.scan(source_path, source)
    if not result.allowed:
        return (), result
    chunks = (parser or PythonSemanticParser()).parse(
        result.redacted_text or "", source_path, tenant_id=tenant_id, repository_id=repository_id,
        source_hash=sha256_text(source), publication_policy=result.policy,
    )
    return chunks, result

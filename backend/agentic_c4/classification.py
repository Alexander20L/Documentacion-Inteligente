from __future__ import annotations

import unicodedata
import re


_CAPABILITY_GENERIC_TERMS = {
    "actualizacion", "adapter", "adaptador", "api", "application", "aplicacion", "component", "componente",
    "creation", "creacion", "deletion", "eliminacion", "handler", "handlers", "management", "manager", "module",
    "modulo", "persistence", "persistencia", "repository", "repositorio", "retrieval", "server", "servidor",
    "service", "services", "servicio", "servicios", "update", "gestion",
}
_CAPABILITY_STOP_WORDS = {"and", "de", "del", "el", "la", "las", "los", "of", "the", "y"}
_CAPABILITY_ALIASES = {
    "article": "article", "articulo": "article",
    "authentication": "authentication", "autenticacion": "authentication",
    "comment": "comment", "comentario": "comment",
    "profile": "profile", "perfil": "profile",
    "tag": "tag", "etiqueta": "tag",
    "user": "user", "usuario": "user",
}


def _normalized_text(*values: str | None) -> str:
    joined = " ".join(value or "" for value in values)
    return unicodedata.normalize("NFKD", joined).encode("ascii", "ignore").decode("ascii").casefold()


def is_postgresql(name: str, technology: str | None = None) -> bool:
    value = _normalized_text(name, technology)
    return "postgresql" in value or "postgres" in value


def is_data_store(name: str, technology: str | None = None) -> bool:
    value = _normalized_text(name, technology)
    markers = (
        "base de datos",
        "data store",
        "database",
        "datastore",
        "mariadb",
        "mongodb",
        "mysql",
        "oracle db",
        "postgres",
        "redis",
        "sql server",
        "sqlite",
    )
    return any(marker in value for marker in markers)


def normalized_capability_name(name: str) -> str:
    tokens = []
    for token in re.findall(r"[a-z0-9]+", _normalized_text(name)):
        if token in _CAPABILITY_GENERIC_TERMS:
            continue
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
            token = token[:-1]
        token = _CAPABILITY_ALIASES.get(token, token)
        if token not in _CAPABILITY_GENERIC_TERMS and token not in _CAPABILITY_STOP_WORDS:
            tokens.append(token)
    return " ".join(tokens)


def capability_names_overlap(left: str, right: str) -> bool:
    left_terms = set(normalized_capability_name(left).split())
    right_terms = set(normalized_capability_name(right).split())
    if not left_terms or not right_terms:
        return False
    overlap = left_terms & right_terms
    return bool(overlap) and len(overlap) == min(len(left_terms), len(right_terms))


def capability_group_overlaps(names: tuple[str, ...]) -> bool:
    term_sets = [set(normalized_capability_name(name).split()) for name in names]
    if len(term_sets) < 2 or any(not terms for terms in term_sets):
        return False
    common_terms = set.intersection(*term_sets)
    return bool(common_terms) and len(common_terms) == min(len(terms) for terms in term_sets)

from __future__ import annotations

from typing import Any, Iterable

from c4core import (
    CandidateElement,
    CandidateRelationship,
    DecisionValue,
    ElementKind,
    HumanDecision,
    Provenance,
    stable_hash,
    stable_id,
)
from modelos.c4 import RevisionC4


TIPOS_ELEMENTO = {item.value: item for item in ElementKind}


METADATA_REVISION = (
    "resumen_evidencia", "agentes", "conflictos", "huerfanos", "hallazgos_juez", "resumen_semantico",
    "consolidacion_capacidades", "reparacion_capacidades",
)


def _derivacion_relacion(item: CandidateRelationship | dict[str, Any]) -> str:
    technology = item.technology if isinstance(item, CandidateRelationship) else item.get("technology")
    provenance = item.provenance.value if isinstance(item, CandidateRelationship) else item.get("provenance")
    if technology and "import" in technology.casefold():
        return "import_fuente"
    if technology == "PostgreSQL protocol":
        return "base_datos"
    if provenance == Provenance.ANALYST_PROVIDED.value:
        return "contexto_analista"
    return "inferencia"


def calcular_hash_revision(
    version: int,
    elementos: list[dict],
    relaciones: list[dict],
    metadata: dict[str, Any] | None = None,
) -> str:
    return stable_hash({
        "version": version,
        "elementos": elementos,
        "relaciones": relaciones,
        "metadata": metadata or {},
    })


def crear_contenido_revision(
    elementos: Iterable[CandidateElement],
    relaciones: Iterable[CandidateRelationship],
    version: int = 1,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidatos_elemento = tuple(sorted(elementos, key=lambda item: item.id))
    candidatos_relacion = tuple(sorted(relaciones, key=lambda item: item.id))
    candidatos_metadata = (metadata or {}).get("candidatos_metadata", {})
    publicos_elemento = [
        {
            "id": item.id,
            "nombre": item.name,
            "descripcion": item.description,
            "inferido": item.provenance == Provenance.INFERRED,
            "procedencia": item.provenance.value,
            "decision": "PENDIENTE" if item.provenance == Provenance.INFERRED else "APROBADO",
            "tipo": item.kind.value,
            "padre_id": item.parent_id,
            **candidatos_metadata.get(item.id, {}),
        }
        for item in candidatos_elemento
    ]
    publicos_relacion = [
        {
            "id": item.id,
            "nombre": item.description,
            "descripcion": item.description,
            "inferido": item.provenance == Provenance.INFERRED,
            "procedencia": item.provenance.value,
            "decision": "PENDIENTE" if item.provenance == Provenance.INFERRED else "APROBADO",
            "origen_id": item.source_id,
            "destino_id": item.target_id,
            "tecnologia": item.technology,
            "derivacion": _derivacion_relacion(item),
            **candidatos_metadata.get(item.id, {}),
        }
        for item in candidatos_relacion
    ]
    revision = {
        "version": version,
        "elementos": publicos_elemento,
        "relaciones": publicos_relacion,
        **{key: (metadata or {})[key] for key in METADATA_REVISION if key in (metadata or {})},
    }
    metadata_hash = {key: revision[key] for key in METADATA_REVISION if key in revision}
    revision["hash"] = calcular_hash_revision(version, publicos_elemento, publicos_relacion, metadata_hash)
    return {
        "revision": revision,
        "candidatos": {
            "elementos": [item.model_dump(mode="json") for item in candidatos_elemento],
            "relaciones": [item.model_dump(mode="json") for item in candidatos_relacion],
        },
    }


def revision_publica(contenido: dict[str, Any]) -> dict[str, Any]:
    revision = {
        **contenido.get("revision", contenido),
        "elementos": [dict(item) for item in contenido.get("revision", contenido).get("elementos", [])],
        "relaciones": [dict(item) for item in contenido.get("revision", contenido).get("relaciones", [])],
    }
    internos = contenido.get("candidatos") or {}
    elementos_internos = {item["id"]: item for item in internos.get("elementos", [])}
    relaciones_internas = {item["id"]: item for item in internos.get("relaciones", [])}
    for item in revision["elementos"]:
        if "padre_id" not in item and item.get("id") in elementos_internos:
            item["padre_id"] = elementos_internos[item["id"]].get("parent_id")
    for item in revision["relaciones"]:
        if "derivacion" in item or item.get("id") not in relaciones_internas:
            continue
        interno = relaciones_internas[item["id"]]
        item["derivacion"] = _derivacion_relacion(interno)
    return RevisionC4.model_validate(revision).model_dump(mode="json", exclude_none=True)


def validar_revision_editada(revision: RevisionC4) -> None:
    ids = [item.id for item in (*revision.elementos, *revision.relaciones)]
    if len(ids) != len(set(ids)):
        raise ValueError("La revisión contiene identificadores duplicados")
    elementos = {item.id: item for item in revision.elementos}
    for item in revision.elementos:
        if not item.inferido and item.decision != "APROBADO":
            raise ValueError(f"El candidato detectado {item.id} debe permanecer APROBADO")
        if item.tipo not in TIPOS_ELEMENTO:
            raise ValueError(f"Tipo C4 no soportado: {item.tipo}")
    for item in revision.relaciones:
        if not item.inferido and item.decision != "APROBADO":
            raise ValueError(f"La relación detectada {item.id} debe permanecer APROBADA")
        if item.origen_id not in elementos or item.destino_id not in elementos:
            raise ValueError(f"La relación {item.id} referencia un elemento inexistente")


def actualizar_contenido_revision(contenido: dict[str, Any], revision: RevisionC4) -> dict[str, Any]:
    validar_revision_editada(revision)
    internos = contenido.get("candidatos") or {}
    elementos_internos = {item["id"]: item for item in internos.get("elementos", [])}
    relaciones_internas = {item["id"]: item for item in internos.get("relaciones", [])}
    if set(elementos_internos) != {item.id for item in revision.elementos}:
        raise ValueError("No se pueden agregar ni eliminar elementos durante la revisión")
    if set(relaciones_internas) != {item.id for item in revision.relaciones}:
        raise ValueError("No se pueden agregar ni eliminar relaciones durante la revisión")

    elementos_core = []
    for item in revision.elementos:
        original = dict(elementos_internos[item.id])
        esperado_inferido = original["provenance"] == Provenance.INFERRED.value
        if item.inferido != esperado_inferido:
            raise ValueError("No se puede cambiar la procedencia de un candidato")
        if item.padre_id != original.get("parent_id"):
            raise ValueError("No se puede cambiar el contenedor padre durante la revisión")
        if item.tipo != original.get("kind"):
            raise ValueError("No se puede cambiar el tipo C4 durante la revisión")
        original.update(name=item.nombre, description=item.descripcion, kind=item.tipo)
        elementos_core.append(original)
    relaciones_core = []
    for item in revision.relaciones:
        original = dict(relaciones_internas[item.id])
        esperado_inferido = original["provenance"] == Provenance.INFERRED.value
        if item.inferido != esperado_inferido:
            raise ValueError("No se puede cambiar la procedencia de una relación")
        if item.derivacion != _derivacion_relacion(original):
            raise ValueError("No se puede cambiar el origen técnico de una relación")
        if item.origen_id != original.get("source_id") or item.destino_id != original.get("target_id"):
            raise ValueError("No se pueden cambiar los extremos de una relación durante la revisión")
        if item.tecnologia != original.get("technology"):
            raise ValueError("No se puede cambiar la tecnología de una relación durante la revisión")
        original.update(
            source_id=item.origen_id,
            target_id=item.destino_id,
            description=item.descripcion or item.nombre,
            technology=item.tecnologia,
        )
        relaciones_core.append(original)

    siguiente = {
        "elementos": revision.model_dump(mode="json")["elementos"],
        "relaciones": revision.model_dump(mode="json")["relaciones"],
        **{key: contenido["revision"][key] for key in METADATA_REVISION if key in contenido.get("revision", {})},
    }
    siguiente["version"] = revision.version + 1
    metadata_hash = {key: siguiente[key] for key in METADATA_REVISION if key in siguiente}
    siguiente["hash"] = calcular_hash_revision(siguiente["version"], siguiente["elementos"], siguiente["relaciones"], metadata_hash)
    return {
        **{clave: valor for clave, valor in contenido.items() if clave not in {"revision", "candidatos"}},
        "revision": siguiente,
        "candidatos": {"elementos": elementos_core, "relaciones": relaciones_core},
    }


def materializar_revision(contenido: dict[str, Any], reviewer: str):
    revision = RevisionC4.model_validate(contenido["revision"])
    validar_revision_editada(revision)
    pendientes = [
        item.id for item in (*revision.elementos, *revision.relaciones)
        if item.inferido and item.decision == "PENDIENTE"
    ]
    if pendientes:
        raise ValueError("Todos los candidatos inferidos deben tener una decisión")
    decisiones = tuple(
        HumanDecision(
            target_id=item.id,
            decision=DecisionValue.APPROVE if item.decision == "APROBADO" else DecisionValue.REJECT,
            reviewer=reviewer,
            rationale="Decisión registrada durante la revisión C4",
        )
        for item in (*revision.elementos, *revision.relaciones)
        if item.inferido
    )
    internos = contenido["candidatos"]
    return (
        tuple(CandidateElement.model_validate(item) for item in internos["elementos"]),
        tuple(CandidateRelationship.model_validate(item) for item in internos["relaciones"]),
        decisiones,
    )


def candidatos_detectados_contexto(contexto: dict[str, Any], evidence_id: str):
    sistema_id = stable_id("element", "analyst", "system", contexto["nombre_sistema"])
    elementos = [CandidateElement(
        id=sistema_id,
        kind=ElementKind.SOFTWARE_SYSTEM,
        name=contexto["nombre_sistema"],
        description=contexto.get("descripcion") or contexto.get("proposito", ""),
        provenance=Provenance.ANALYST_PROVIDED,
        evidence_ids=(evidence_id,),
    )]
    for actor in contexto.get("actores", []):
        elementos.append(CandidateElement(
            id=stable_id("element", "analyst", "person", actor["nombre"]),
            kind=ElementKind.PERSON,
            name=actor["nombre"],
            description=actor.get("descripcion", ""),
            provenance=Provenance.ANALYST_PROVIDED,
            evidence_ids=(evidence_id,),
        ))
    for externo in contexto.get("sistemas_externos", []):
        elementos.append(CandidateElement(
            id=stable_id("element", "analyst", "external", externo["nombre"]),
            kind=ElementKind.EXTERNAL_SYSTEM,
            name=externo["nombre"],
            description=externo.get("descripcion", ""),
            provenance=Provenance.ANALYST_PROVIDED,
            evidence_ids=(evidence_id,),
        ))
    return tuple(elementos), sistema_id


def relaciones_detectadas_contexto(
    elementos: Iterable[CandidateElement],
    sistema_id: str,
    evidence_id: str,
) -> tuple[CandidateRelationship, ...]:
    return tuple(
        CandidateRelationship(
            id=stable_id("relationship", "analyst", item.id, sistema_id, "uses"),
            source_id=item.id,
            target_id=sistema_id,
            description=f"{item.name} utiliza el sistema de software",
            technology="HTTPS",
            provenance=Provenance.ANALYST_PROVIDED,
            evidence_ids=(evidence_id,),
            tags=("analyst-context",),
        )
        for item in elementos
        if item.kind == ElementKind.PERSON
    )

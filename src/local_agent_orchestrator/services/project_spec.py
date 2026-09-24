from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from local_agent_orchestrator.models.plan_intake import PlanCandidate, PlanCandidateProject
from local_agent_orchestrator.models.project_spec import (
    ProjectSpec,
    ResearchRequirement,
)


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
_KNOWN_CAPABILITIES = {
    "python",
    "fastapi",
    "sqlite",
    "sqlalchemy",
    "pytest",
    "api-testing",
    "node",
    "typescript",
    "react",
    "vite",
    "godot",
    "gdscript",
}
_FEATURE_LABELS = {"create", "list", "lookup", "url_validation", "persistence", "search", "crud"}
_FEATURE_ACTIONS = {"create", "list", "lookup", "get", "update", "delete", "validate"}
_CAPABILITY_ALIASES = {
    "apitesting": "api-testing",
    "fastapitestclient": "api-testing",
}


def _canonical_capability(value: str) -> str:
    label = value.strip().casefold()
    key = re.sub(r"[\s_-]+", "", label)
    return _CAPABILITY_ALIASES.get(key, label)


def _is_feature_label(value: str) -> bool:
    normalized = re.sub(r"[\s-]+", "_", value.strip().casefold())
    return normalized in _FEATURE_LABELS or normalized.split("_", 1)[0] in _FEATURE_ACTIONS


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not result:
        raise ValueError("Project name must produce a safe slug")
    return result


def _project_name(markdown: str, request: str, project: PlanCandidateProject | None) -> str:
    if project is not None and project.name:
        name = project.name.strip()
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("Project name contains unsafe characters")
        return name
    for line in markdown.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            return heading.group(1).strip()
    return request.strip()


def _text(candidate: PlanCandidate, markdown: str, project: PlanCandidateProject | None) -> str:
    values = [markdown, candidate.request, *(task.description for task in candidate.tasks)]
    if project is not None:
        values.extend(
            item
            for item in (
                project.name,
                project.language,
                project.framework,
                project.engine,
                project.project_type,
                project.database,
                project.runtime,
                *project.capabilities,
            )
            if item
        )
    return " ".join(values).lower()


def _capabilities(candidate: PlanCandidate, markdown: str) -> tuple[list[str], list[str]]:
    project = candidate.project
    text = _text(candidate, markdown, project)
    requested = list(project.capabilities) if project is not None else []
    selected = {_canonical_capability(item) for item in requested if item.strip()}
    if re.search(r"\bpython\b|fastapi|pytest", text):
        selected.add("python")
    if "fastapi" in text:
        selected.update({"fastapi", "pytest", "api-testing"})
    if "sqlite" in text:
        selected.add("sqlite")
    if {"fastapi", "sqlite"} <= selected:
        selected.add("sqlalchemy")
    if re.search(r"\bpytest\b", text):
        selected.add("pytest")
    if re.search(r"\b(node|npm|javascript|typescript|react|vite|frontend|front-end)\b", text):
        selected.add("node")
    if re.search(r"\btypescript\b|\bts\b", text):
        selected.add("typescript")
    if "react" in text:
        selected.add("react")
    if "vite" in text:
        selected.add("vite")
    if re.search(r"\bgodot\b|\bgdscript\b", text):
        selected.add("godot")
    if "gdscript" in text:
        selected.add("gdscript")
    unknown = sorted(
        item
        for item in selected
        if item not in _KNOWN_CAPABILITIES and not _is_feature_label(item)
    )
    return sorted(selected & _KNOWN_CAPABILITIES), unknown


def _research_requirements(
    capabilities: Iterable[str],
    unknown: Iterable[str],
    project: PlanCandidateProject | None,
) -> list[ResearchRequirement]:
    requirements = [
        ResearchRequirement(topic=f"capability:{item}", reason="No trusted Workestra capability is registered for this request.")
        for item in unknown
    ]
    capability_set = set(capabilities)
    if project is None or project.intent == "existing":
        return requirements
    if capability_set & {"node", "typescript", "react", "vite"}:
        requirements.append(
            ResearchRequirement(
                topic="trusted Node/TypeScript bootstrap and verifier",
                reason="Workestra has no bounded Node project bootstrap profile yet.",
            )
        )
    if capability_set & {"godot", "gdscript"}:
        requirements.extend(
            [
                ResearchRequirement(
                    topic="Godot version and project bootstrap",
                    reason="The requested engine/version setup is not a trusted Workestra capability yet.",
                ),
                ResearchRequirement(
                    topic="Godot verification strategy",
                    reason="A deterministic headless verifier is required before execution can start.",
                ),
            ]
        )
    if not capability_set:
        requirements.append(
            ResearchRequirement(
                topic="project language, framework, and trusted verifier",
                reason="The new-project plan does not identify a supported stack.",
            )
        )
    return requirements


def derive_project_spec(
    candidate: PlanCandidate,
    markdown: str,
    *,
    projects_root: str | Path | None = None,
    occupied_workspace_paths: Iterable[str | Path] = (),
    occupied_project_ids: Iterable[str] = (),
    bound_project_id: str | None = None,
    bound_workspace_root: str | Path | None = None,
) -> ProjectSpec:
    project = candidate.project
    name = _project_name(markdown, candidate.request, project)
    capabilities, unknown = _capabilities(candidate, markdown)
    intent = project.intent if project is not None else "existing"
    slug = _slug(project.slug if project is not None and project.slug else name)
    workspace_root = None
    if intent == "new":
        root = (Path(projects_root).expanduser() if projects_root is not None else Path.home() / "Projeler").resolve()
        if bound_project_id == slug and bound_workspace_root is not None:
            bound_root = Path(bound_workspace_root).expanduser().resolve()
            if bound_root.is_relative_to(root) and bound_root.name == slug:
                workspace_root = bound_root
        if workspace_root is None:
            occupied_paths = {Path(path).expanduser().resolve() for path in occupied_workspace_paths}
            occupied_ids = set(occupied_project_ids)
            base_slug = slug
            suffix = 1
            while True:
                slug = base_slug if suffix == 1 else f"{base_slug}-{suffix}"
                candidate_root = root / slug
                if (
                    slug not in occupied_ids
                    and candidate_root.resolve() not in occupied_paths
                    and not candidate_root.exists()
                    and not candidate_root.is_symlink()
                ):
                    workspace_root = candidate_root.resolve()
                    break
                suffix += 1
                if suffix > 10_000:
                    raise ValueError("No safe workspace path is available under projects_root.")
    bootstrap_profile = None
    verifier = None
    if intent == "new" and "python" in capabilities:
        bootstrap_profile = "fastapi" if "fastapi" in capabilities else "python"
        verifier = ["uv", "run", "pytest", "-q"]
    research = _research_requirements(capabilities, unknown, project)
    if project is not None:
        research.extend(
            ResearchRequirement(topic="plan", reason=question)
            for question in project.research_questions
        )
    return ProjectSpec(
        name=name,
        slug=slug,
        intent=intent,
        workspace_root=str(workspace_root) if workspace_root is not None else None,
        language=project.language if project is not None and project.language else ("Python" if "python" in capabilities else None),
        framework=project.framework if project is not None and project.framework else ("FastAPI" if "fastapi" in capabilities else None),
        engine=project.engine if project is not None and project.engine else ("Godot" if "godot" in capabilities else None),
        project_type=project.project_type if project is not None else None,
        database=project.database if project is not None and project.database else ("SQLite" if "sqlite" in capabilities else None),
        runtime=project.runtime if project is not None else None,
        capabilities=capabilities,
        bootstrap_profile=bootstrap_profile,
        verifier=verifier,
        edit_boundaries=project.edit_boundaries if project is not None else [],
        review_requirements=project.review_requirements if project is not None else [],
        security_requirements=project.security_requirements if project is not None else [],
        completion_criteria=(project.completion_criteria if project is not None else []),
        research_requirements=research,
    )

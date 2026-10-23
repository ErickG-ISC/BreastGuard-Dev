"""CU-06: artículos educativos en markdown con metadatos (contenido público, sin tenant).

Cada archivo de `backend/app/content/blog/` empieza con un bloque de metadatos entre `---`:
`clave: valor` por línea y listas como `[a, b]`. Se leen con este parser propio (sin PyYAML) y
se validan al cargar: un artículo mal escrito hace fallar el arranque y las pruebas, nunca se
publica a medias.

Sin `revisado_por`, la interfaz muestra "Contenido educativo general" y nunca "validado".
"""

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

BLOG_DIR = Path(__file__).resolve().parents[1] / "content" / "blog"
FAQ_SLUG = "faq"
STATES = {"borrador", "revisado"}
TAGS = {
    "bi-rads",
    "resultados",
    "ecografia",
    "estudios",
    "autoexploracion",
    "prevencion",
    "cuando-consultar",
    "sobre-la-app",
}
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)


class BlogContentError(ValueError):
    pass


@dataclass(frozen=True)
class Article:
    slug: str
    title: str
    tags: tuple[str, ...]
    summary: str
    reviewed_by: str | None
    review_date: date | None
    status: str
    reading_minutes: int
    sources: tuple[str, ...]
    body: str


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [item.strip() for item in inner.split(",") if item.strip()] if inner else []
    return raw


def parse(text: str, name: str) -> Article:
    match = _FRONT.match(text.replace("\r\n", "\n"))
    if not match:
        raise BlogContentError(f"{name}: falta el bloque de metadatos entre ---")
    meta: dict = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise BlogContentError(f"{name}: línea de metadatos sin ':' -> {line!r}")
        meta[key.strip()] = _parse_value(value)

    required = ("slug", "titulo", "etiquetas", "resumen", "estado", "lectura_min", "fuentes")
    missing = [key for key in required if key not in meta]
    if missing:
        raise BlogContentError(f"{name}: faltan metadatos {missing}")

    slug = meta["slug"]
    if not _SLUG.match(slug) or f"{slug}.md" != name:
        raise BlogContentError(f"{name}: el slug debe coincidir con el nombre del archivo")
    tags = meta["etiquetas"]
    if not isinstance(tags, list) or not tags or set(tags) - TAGS:
        raise BlogContentError(f"{name}: etiquetas desconocidas {set(tags) - TAGS}")
    if meta["estado"] not in STATES:
        raise BlogContentError(f"{name}: estado inválido")
    sources = meta["fuentes"]
    if not isinstance(sources, list) or any(not s.startswith("https://") for s in sources):
        raise BlogContentError(f"{name}: las fuentes deben ser URLs https")
    reviewed_by = meta.get("revisado_por") or None
    review_date = date.fromisoformat(meta["fecha_revision"]) if meta.get("fecha_revision") else None
    if meta["estado"] == "revisado" and not (reviewed_by and review_date):
        raise BlogContentError(f"{name}: 'revisado' exige revisado_por y fecha_revision")

    return Article(
        slug=slug,
        title=meta["titulo"],
        tags=tuple(tags),
        summary=meta["resumen"],
        reviewed_by=reviewed_by,
        review_date=review_date,
        status=meta["estado"],
        reading_minutes=int(meta["lectura_min"]),
        sources=tuple(sources),
        body=match.group(2).strip(),
    )


@lru_cache
def load_all() -> dict[str, Article]:
    articles = {}
    for path in sorted(BLOG_DIR.glob("*.md")):
        article = parse(path.read_text(encoding="utf-8"), path.name)
        articles[article.slug] = article
    if FAQ_SLUG not in articles:
        raise BlogContentError("Falta faq.md")
    return articles


def articles() -> list[Article]:
    return [a for slug, a in load_all().items() if slug != FAQ_SLUG]


def get(slug: str) -> Article | None:
    return load_all().get(slug)

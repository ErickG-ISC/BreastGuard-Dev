"""CU-06: blog y preguntas frecuentes. Contenido público y general: sin sesión ni datos de tenant.

La recomendación por resultado ("Recomendado para ti") la arma el frontend con el último análisis
de la paciente; este endpoint nunca recibe datos de la paciente.
"""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from backend.app.schemas.blog import ArticleOut, ArticleSummary
from backend.app.services import blog

router = APIRouter()


def _out(article: blog.Article, model: type[ArticleSummary]):
    return model(**{k: v for k, v in asdict(article).items() if k in model.model_fields})


@router.get("/blog", response_model=list[ArticleSummary])
def list_articles():
    return [_out(a, ArticleSummary) for a in blog.articles()]


# Antes de /blog/{slug}
@router.get("/blog/faq", response_model=ArticleOut)
def get_faq():
    return _out(blog.get(blog.FAQ_SLUG), ArticleOut)


@router.get("/blog/{slug}", response_model=ArticleOut)
def get_article(slug: str):
    article = blog.get(slug)
    if article is None or slug == blog.FAQ_SLUG:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artículo no encontrado")
    return _out(article, ArticleOut)

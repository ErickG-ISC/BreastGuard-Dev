"""CU-06: blog y preguntas frecuentes (contenido público, metadatos y tono conservador)."""

import re

import pytest

from backend.app.services import blog

API = "/api/v1"
# Afirmaciones que el contenido nunca debe hacer (tono: conocer tu cuerpo y consultar)
FORBIDDEN = re.compile(
    r"detecta el c[aá]ncer|descarta el c[aá]ncer|validado m[eé]dicamente|diagn[oó]stico seguro"
    r"|est[aá]s sana|no tienes c[aá]ncer|garantiza",
    re.I,
)
# Cifras: sin porcentajes ni estadísticas propias en el contenido (se citan fuentes)
PERCENT = re.compile(r"\d+\s?%")


def test_todos_los_articulos_cargan_y_tienen_fuentes():
    articles = blog.articles()
    assert len(articles) >= 5
    for article in articles:
        assert article.sources, f"{article.slug} sin fuentes"
        assert article.status in {"borrador", "revisado"}
        assert article.reading_minutes > 0


def test_sin_revision_no_dicen_revisado():
    for article in blog.load_all().values():
        if article.reviewed_by is None:
            assert article.status == "borrador"


@pytest.mark.parametrize("slug", sorted(blog.load_all()))
def test_tono_conservador_y_sin_cifras(slug):
    article = blog.get(slug)
    text = f"{article.title}\n{article.summary}\n{article.body}"
    assert not FORBIDDEN.search(text), FORBIDDEN.search(text)
    assert not PERCENT.search(text)


def test_listado_publico_sin_cuerpo(client):
    response = client.get(f"{API}/blog")
    assert response.status_code == 200
    items = response.json()
    slugs = {a["slug"] for a in items}
    assert "faq" not in slugs and "bi-rads-3" in slugs
    assert all("body" not in a for a in items)
    assert all(a["reviewed_by"] is None for a in items)


def test_articulo_y_faq(client):
    article = client.get(f"{API}/blog/bi-rads-3")
    assert article.status_code == 200
    assert article.json()["body"].startswith("## ")
    assert article.json()["sources"]
    faq = client.get(f"{API}/blog/faq")
    assert faq.status_code == 200 and "¿El análisis reemplaza a mi médico?" in faq.json()["body"]


@pytest.mark.parametrize(
    "slug", ["no-existe", "..%2F..%2Fconsent_v1", "..%2f..%2fmain", "FAQ", "faq.md", "bi-rads-3.md"]
)
def test_slug_desconocido_404(client, slug):
    assert client.get(f"{API}/blog/{slug}").status_code == 404


def test_no_requiere_sesion_ni_toca_datos(client):
    # Sin Authorization: responde igual; con un token basura también (no lo lee)
    assert client.get(f"{API}/blog").status_code == 200
    assert client.get(f"{API}/blog", headers={"Authorization": "Bearer basura"}).status_code == 200


class TestParser:
    BASE = (
        "---\nslug: ejemplo\ntitulo: T\netiquetas: [prevencion]\nresumen: R\nrevisado_por:\n"
        "fecha_revision:\nestado: borrador\nlectura_min: 2\nfuentes: [https://example.org]\n---\n"
        "## Cuerpo\n"
    )

    def test_valido(self):
        article = blog.parse(self.BASE, "ejemplo.md")
        assert article.tags == ("prevencion",) and article.reviewed_by is None

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("slug: ejemplo", "slug: otro"),
            ("etiquetas: [prevencion]", "etiquetas: [inventada]"),
            ("estado: borrador", "estado: publicado"),
            ("estado: borrador", "estado: revisado"),
            ("fuentes: [https://example.org]", "fuentes: [http://example.org]"),
            ("lectura_min: 2\n", ""),
            ("---\nslug", "slug"),
        ],
    )
    def test_invalido(self, old, new):
        with pytest.raises(blog.BlogContentError):
            blog.parse(self.BASE.replace(old, new, 1), "ejemplo.md")

    def test_revisado_con_revisor_y_fecha(self):
        text = (
            self.BASE.replace("revisado_por:", "revisado_por: Dra. Ejemplo")
            .replace("fecha_revision:", "fecha_revision: 2026-10-01")
            .replace("estado: borrador", "estado: revisado")
        )
        article = blog.parse(text, "ejemplo.md")
        assert article.reviewed_by == "Dra. Ejemplo" and str(article.review_date) == "2026-10-01"

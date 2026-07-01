from django import template
from django.conf import settings

register = template.Library()


# See https://docs.djangoproject.com/en/5.1/howto/custom-template-tags/
@register.simple_tag(name="app_version")
def app_version() -> str:
    """Render ``settings.APP_VERSION`` verbatim.

    The chart's image tag may already start with ``v`` (``v1.0.0``,
    ``dev2-v1.1.0``), so this tag does not prepend a prefix — the
    displayed value matches the deployed image's tag exactly and the
    GitHub release link target resolves to a real tag.

    Returns:
        The current ``APP_VERSION`` string.
    """
    return settings.APP_VERSION


@register.simple_tag(name="support_email")
def support_email():
    return settings.SUPPORT_EMAIL

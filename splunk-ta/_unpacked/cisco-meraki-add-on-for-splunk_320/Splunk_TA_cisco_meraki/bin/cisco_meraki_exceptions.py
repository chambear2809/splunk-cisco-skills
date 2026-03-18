class TemplateCreationException(Exception):
    """Base class for template creation exceptions."""

    pass


class TemplateDeletionException(Exception):
    """Base class for template deletion exceptions."""

    pass


class WebhookCreationException(Exception):
    """Base class for webhook creation exceptions."""

    pass


class WebhookDeletionException(Exception):
    """Base class for webhook deletion exceptions."""

    pass

"""Nexus 9k Exceptions."""


class Nexus9kError(Exception):
    """Base class for all Nexus 9k errors."""

    def __init__(self, message):
        """Initialize Nexus 9k error class."""
        self.message = message

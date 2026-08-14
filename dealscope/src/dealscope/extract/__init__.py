"""Evidence extractors.

Each module here turns fetched pages into structured facts plus the
``Evidence`` records that justify them. Extractors never guess silently: if a
field cannot be supported by something observed on the site, it is left empty
and surfaces later as an explicit unknown.
"""

from . import commerce, contact, content, hiring, identity, people, structured, tech

__all__ = ["commerce", "contact", "content", "hiring", "identity", "people", "structured", "tech"]

"""dealscope — build an acquisition-buyer brief from a company's public website.

Typical use::

    from dealscope import analyze

    brief = analyze("stripe.com")
    print(brief.narrative)

The library reads publicly available pages, extracts evidence, scores what it
found, and writes a short brief aimed at someone considering buying the
business. It is a research accelerator, not a substitute for financial, legal,
or technical due diligence.
"""

from .config import Config, __version__
from .models import CompanyBrief, Evidence, RiskFlag, Signal
from .analyzer import analyze

__all__ = [
    "analyze",
    "Config",
    "CompanyBrief",
    "Evidence",
    "Signal",
    "RiskFlag",
    "__version__",
]

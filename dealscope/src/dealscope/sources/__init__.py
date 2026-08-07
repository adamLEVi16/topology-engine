"""Data sources other than the company's own website.

A website is what a business says about itself. These sources are what it had
to file. For an asset-heavy business — a haulier, a FedEx ISP, a landscaper
with a fleet — the filings are far better evidence than the marketing copy,
and they exist even when the business has no real website at all.

Every source here produces the same ``Evidence`` records as the website
extractors, so a fact's origin stays visible all the way to the brief.
"""

from . import fmcsa

__all__ = ["fmcsa"]

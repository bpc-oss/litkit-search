"""litkit — unified academic literature search toolkit."""

__version__ = "0.1.0"

# Re-export core public API.
from litkit.config import load_env, sync_keys
from litkit.core.pipeline import Pipeline
from litkit.downloaders import (
    ArxivDownloader,
    DownloadChain,
    EuropePmcDownloader,
    InstitutionalDownloader,
    PublisherDirectDownloader,
    SciHubDownloader,
)

__all__ = [
    "load_env",
    "sync_keys",
    "Pipeline",
    "ArxivDownloader",
    "DownloadChain",
    "EuropePmcDownloader",
    "InstitutionalDownloader",
    "PublisherDirectDownloader",
    "SciHubDownloader",
]

"""PDF downloaders with chain-of-responsibility pattern."""

from litkit.downloaders.annas_archive import AnnasArchiveDownloader
from litkit.downloaders.arxiv import ArxivDownloader
from litkit.downloaders.base import DownloadChain, Downloader
from litkit.downloaders.biorxiv import BiorxivDownloader
from litkit.downloaders.chinese_institutional import ChineseInstitutionalDownloader
from litkit.downloaders.europepmc import EuropePmcDownloader
from litkit.downloaders.institutional import InstitutionalDownloader
from litkit.downloaders.libgen import LibgenDownloader
from litkit.downloaders.pmc_ftp import PmcFtpDownloader
from litkit.downloaders.publisher_direct import PublisherDirectDownloader
from litkit.downloaders.scihub import SciHubDownloader
from litkit.downloaders.supplementary import SupplementaryDownloader, cached_path, is_cached
from litkit.downloaders.unpaywall import UnpaywallDownloader

__all__ = [
    "Downloader",
    "DownloadChain",
    "ArxivDownloader",
    "UnpaywallDownloader",
    "EuropePmcDownloader",
    "SciHubDownloader",
    "BiorxivDownloader",
    "PmcFtpDownloader",
    "PublisherDirectDownloader",
    "LibgenDownloader",
    "AnnasArchiveDownloader",
    "ChineseInstitutionalDownloader",
    "InstitutionalDownloader",
    "SupplementaryDownloader",
    "is_cached",
    "cached_path",
]

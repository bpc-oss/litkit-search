"""Chinese literature database resource registry.

The Shenzhen University profile intentionally stores library entry pages and
search URL templates separately.  Entry pages are the authoritative place for
access rules, while search URLs are best-effort convenience links for an
authenticated browser session.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class ChineseResource:
    """A Chinese literature database available through an institution."""

    name: str
    label: str
    provider: str
    library_page: str
    search_template: str
    access_note: str
    content_types: tuple[str, ...] = ("journal",)
    subscribed: bool = True

    def search_url(self, query: str) -> str:
        return self.search_template.format(query=quote(query, safe=""))


SZU_CHINESE_RESOURCES: dict[str, ChineseResource] = {
    "cnki": ChineseResource(
        name="cnki",
        label="中国知网CNKI系列数据库",
        provider="cnki",
        library_page="https://www.lib.szu.edu.cn/er/cnki",
        search_template="https://kns.cnki.net/kns8s/defaultresult/index?kw={query}",
        access_note=(
            "SZU subscribes to CNKI journals, dissertations, newspapers, proceedings, "
            "yearbooks, reference works, and patents. Use SZU library entry pages for "
            "off-campus unified authentication."
        ),
        content_types=(
            "journal",
            "doctoral_dissertation",
            "master_dissertation",
            "conference",
            "newspaper",
            "yearbook",
            "reference",
            "patent",
        ),
    ),
    "wanfang": ChineseResource(
        name="wanfang",
        label="万方数据智研AI+ / 万方智搜",
        provider="wanfang",
        library_page="https://www.lib.szu.edu.cn/node/18810",
        search_template="https://s.wanfangdata.com.cn/paper?q={query}",
        access_note=(
            "On campus, Wanfang should bind to the Shenzhen University institution "
            "automatically. Off campus, use institution login from the library entry."
        ),
        content_types=("journal", "dissertation", "conference", "report", "patent", "standard"),
    ),
    "cqvip": ChineseResource(
        name="cqvip",
        label="维普科创助手 / 维普中文资源",
        provider="cqvip",
        library_page="https://www.lib.szu.edu.cn/node/18891",
        search_template="https://qikan.cqvip.com/Qikan/Search/Index?key={query}",
        access_note=(
            "Use the SZU library trial entry first; the platform provides literature "
            "search, AI search, review generation, and reading tools."
        ),
        content_types=("journal", "dissertation", "patent", "policy", "standard"),
    ),
    "sinomed": ChineseResource(
        name="sinomed",
        label="SinoMed中国生物医学文献服务系统",
        provider="sinomed",
        library_page="https://www.sinomed.ac.cn/zh/advancedSearch.jsp",
        search_template="https://www.sinomed.ac.cn/zh/basicSearch.jsp?searchWord={query}",
        access_note=(
            "Best used for Chinese biomedical literature. Full-text access depends on "
            "SinoMed OA flags, document delivery, or overlap with CNKI/Wanfang/CQVIP."
        ),
        content_types=("journal", "biomedical", "dissertation", "citation"),
    ),
    "ncpssd": ChineseResource(
        name="ncpssd",
        label="国家哲学社会科学文献中心",
        provider="ncpssd",
        library_page="https://www.ncpssd.cn/",
        search_template="https://www.ncpssd.cn/Literature/search?keyword={query}",
        access_note="Useful for humanities and social-science Chinese literature.",
        content_types=("journal", "humanities", "social_science"),
    ),
}


def build_search_targets(
    query: str,
    sources: list[str] | None = None,
) -> list[tuple[ChineseResource, str]]:
    """Return resource/search-url pairs for *query*."""
    selected = sources or list(SZU_CHINESE_RESOURCES)
    targets: list[tuple[ChineseResource, str]] = []
    for name in selected:
        resource = SZU_CHINESE_RESOURCES.get(name.strip())
        if resource:
            targets.append((resource, resource.search_url(query)))
    return targets

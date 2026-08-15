from litkit.core.models import Paper
from litkit.verify.metadata_check import MetadataChecker


class _ClosableSource:
    instances = []
    result = None

    def __init__(self, config):
        self.closed = False
        self.__class__.instances.append(self)

    async def fetch_by_doi(self, doi):
        return self.__class__.result

    async def search(self, title, limit=5):
        class _Result:
            papers = []

        return _Result()

    async def close(self):
        self.closed = True


class _OpenAlexSource(_ClosableSource):
    pass


def test_verify_closes_sources_for_doi_lookup(monkeypatch):
    expected = Paper(doi="10.1234/test", title="Test Title", year=2024)
    _ClosableSource.instances.clear()
    _OpenAlexSource.instances.clear()
    _ClosableSource.result = expected
    _OpenAlexSource.result = None

    monkeypatch.setattr("litkit.verify.metadata_check.Crossref", _ClosableSource)
    monkeypatch.setattr("litkit.verify.metadata_check.OpenAlex", _OpenAlexSource)

    checker = MetadataChecker()
    result = __import__("asyncio").run(checker.verify(expected))

    assert result.status == "ok"
    assert _ClosableSource.instances
    assert all(instance.closed for instance in _ClosableSource.instances)


def test_verify_closes_sources_for_title_search(monkeypatch):
    ref = Paper(title="Recovered By Title", year=2024)

    class _SearchSource(_ClosableSource):
        async def search(self, title, limit=5):
            class _Result:
                papers = [Paper(title="Recovered By Title", year=2024)]

            return _Result()

    _SearchSource.instances.clear()
    monkeypatch.setattr("litkit.verify.metadata_check.Crossref", _SearchSource)
    monkeypatch.setattr("litkit.verify.metadata_check.OpenAlex", _OpenAlexSource)

    checker = MetadataChecker()
    result = __import__("asyncio").run(checker.verify(ref))

    assert result.status == "ok"
    assert _SearchSource.instances
    assert all(instance.closed for instance in _SearchSource.instances)

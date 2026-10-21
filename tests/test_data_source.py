"""DataSource: the accepted spellings, the legacy value, and the scheduling predicates."""
import pytest

from pydantic import ValidationError

from volttron.driver.base.config import DataSource, PointConfig


@pytest.mark.parametrize('given, expected', [
    ('short_poll', DataSource.SHORT_POLL), ('SHORT_POLL', DataSource.SHORT_POLL), ('Short Poll', DataSource.SHORT_POLL),
    ('long-poll', DataSource.LONG_POLL), ('poll_once', DataSource.POLL_ONCE), ('static', DataSource.STATIC),
    ('never_poll', DataSource.NEVER_POLL), ('never', DataSource.NEVER_POLL), ('NEVER', DataSource.NEVER_POLL),
    ('server', DataSource.SERVER), (DataSource.SERVER, DataSource.SERVER), ('', DataSource.SHORT_POLL),
])
def test_spellings(given, expected):
    assert PointConfig(volttron_point_name='p', data_source=given).data_source is expected
    assert PointConfig(**{'Volttron Point Name': 'p', 'Data Source': given}).data_source is expected


def test_unknown_value_is_rejected():
    with pytest.raises(ValidationError):
        PointConfig(volttron_point_name='p', data_source='sometimes')


def test_default_and_serialization():
    point = PointConfig(volttron_point_name='p')
    assert point.data_source is DataSource.SHORT_POLL
    assert PointConfig(volttron_point_name='p', data_source='never').model_dump()['data_source'] == 'never_poll'
    point.data_source = 'server'                                     # validate_assignment normalizes too
    assert point.data_source is DataSource.SERVER


def test_predicates():
    assert [d for d in DataSource if d.scheduled] == [DataSource.SHORT_POLL, DataSource.LONG_POLL]
    assert [d for d in DataSource if d.polled] == [DataSource.SHORT_POLL, DataSource.LONG_POLL, DataSource.POLL_ONCE]
    assert not DataSource.SERVER.polled and not DataSource.STATIC.polled and not DataSource.NEVER_POLL.polled

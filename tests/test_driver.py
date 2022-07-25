"""Unit tests for base driver"""


def test_base_interface_should_have_empty_point_map(generic_test_interface):

    assert not generic_test_interface.get_register_names()

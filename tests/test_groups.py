from app.groups import get_user_groups, user_has_tab


def test_get_user_groups_returns_all_groups_containing_user(tmp_groups_file):
    assert set(get_user_groups("alice")) == {"executives", "administrators"}


def test_get_user_groups_returns_empty_for_unknown_user(tmp_groups_file):
    assert get_user_groups("nobody") == []


def test_user_has_tab_true_when_any_group_allows_it(tmp_groups_file):
    assert user_has_tab("carol", "admin") is True


def test_user_has_tab_false_when_no_group_allows_it(tmp_groups_file):
    assert user_has_tab("carol", "dashboard") is False


def test_user_has_tab_false_for_unknown_user(tmp_groups_file):
    assert user_has_tab("nobody", "dashboard") is False

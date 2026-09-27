from app.groups import (
    add_group_member,
    get_user_groups,
    list_group_names,
    remove_group_member,
    set_user_groups,
    user_has_tab,
)


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


def test_set_user_groups_adds_to_selected_groups(tmp_groups_file):
    set_user_groups("dave", ["executives"])
    assert get_user_groups("dave") == ["executives"]


def test_set_user_groups_removes_from_deselected_groups(tmp_groups_file):
    # alice starts in both executives and administrators (see conftest.tmp_groups_file)
    set_user_groups("alice", ["executives"])
    assert set(get_user_groups("alice")) == {"executives"}


def test_set_user_groups_empty_list_removes_from_all_groups(tmp_groups_file):
    set_user_groups("alice", [])
    assert get_user_groups("alice") == []


def test_list_group_names_returns_all_configured_groups(tmp_groups_file):
    assert set(list_group_names()) == {"executives", "administrators", "developers"}


def test_add_group_member_adds_username_to_existing_group(tmp_groups_file):
    add_group_member("developers", "dave")

    assert get_user_groups("dave") == ["developers"]


def test_add_group_member_is_idempotent_for_an_existing_member(tmp_groups_file):
    add_group_member("administrators", "alice")  # alice is already a member

    assert set(get_user_groups("alice")) == {"executives", "administrators"}


def test_add_group_member_is_a_no_op_for_an_unknown_group(tmp_groups_file):
    add_group_member("nonexistent", "dave")

    assert get_user_groups("dave") == []


def test_remove_group_member_removes_username_from_group(tmp_groups_file):
    remove_group_member("administrators", "alice")

    assert "administrators" not in get_user_groups("alice")


def test_remove_group_member_is_a_no_op_for_a_non_member(tmp_groups_file):
    remove_group_member("developers", "alice")  # alice isn't in developers

    assert set(get_user_groups("alice")) == {"executives", "administrators"}


def test_remove_group_member_is_a_no_op_for_an_unknown_group(tmp_groups_file):
    remove_group_member("nonexistent", "alice")

    assert set(get_user_groups("alice")) == {"executives", "administrators"}

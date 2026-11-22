# SPDX-License-Identifier: GPL-3.0-or-later
from deskence.conflicts import STATE_ACTIVE, STATE_INACTIVE, find_conflicts


def ext(name, state=STATE_ACTIVE):
    return {"name": name, "state": state}


def test_known_dock_is_certain():
    found = find_conflicts("dock", {"dash-to-dock@micxgx.gmail.com": ext("Dash to Dock")})
    assert [(c.uuid, c.certain) for c in found] == [("dash-to-dock@micxgx.gmail.com", True)]


def test_inactive_extensions_are_ignored():
    assert find_conflicts("dock", {"dash-to-dock@micxgx.gmail.com":
                                   ext("Dash to Dock", STATE_INACTIVE)}) == []


def test_our_extensions_are_never_conflicts():
    assert find_conflicts("dock", {"dock@deskence.github.io": ext("Deskence Dock")}) == []


def test_unknown_by_name_is_uncertain():
    found = find_conflicts("tray", {"foo@bar": ext("Fancy AppIndicator Thing")})
    assert [(c.uuid, c.certain) for c in found] == [("foo@bar", False)]


def test_unrelated_extension():
    assert find_conflicts("desktop-icons", {"clock@x": ext("Clock Override")}) == []


def test_ding():
    found = find_conflicts("desktop-icons", {"ding@rastersoft.com": ext("Desktop Icons NG (DING)")})
    assert found and found[0].certain


def test_former_name_only_conflicts_once_the_new_extension_is_known():
    former = {"dock@bettergnome.github.io": ext("Better GNOME Desktop Dock")}
    # Updated during the session: the former dock runs until the next login.
    assert find_conflicts("dock", former) == []
    both = dict(former, **{"dock@deskence.github.io": ext("Deskence Dock")})
    found = find_conflicts("dock", both)
    assert [(c.uuid, c.certain) for c in found] == [("dock@bettergnome.github.io", True)]
    # Never reported for another feature.
    assert find_conflicts("tray", both) == []

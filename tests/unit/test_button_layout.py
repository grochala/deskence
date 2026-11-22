# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from deskence import button_layout as bl


@pytest.mark.parametrize("layout, expected", [
    ("appmenu:close", "appmenu:minimize,close"),
    ("appmenu:maximize,close", "appmenu:minimize,maximize,close"),
    ("close:appmenu", "close,minimize:appmenu"),
    (":", ":minimize"),
    ("", ":minimize"),
])
def test_enable_minimize(layout, expected):
    assert bl.set_button(layout, "minimize", True) == expected


def test_disable_keeps_other_entries():
    assert bl.set_button("icon,appmenu:minimize,maximize,close", "minimize", False) == \
        "icon,appmenu:maximize,close"


def test_close_is_kept_when_toggling():
    layout = bl.set_button("appmenu:close", "maximize", True)
    layout = bl.set_button(layout, "maximize", False)
    assert layout == "appmenu:close"


def test_enable_is_idempotent():
    layout = "appmenu:minimize,maximize,close"
    assert bl.set_button(layout, "minimize", True) == layout


def test_move_to_left_uses_gnome_order():
    assert bl.set_side("appmenu:minimize,maximize,close", "left") == \
        "close,minimize,maximize,appmenu:"


def test_move_back_to_right():
    left = bl.set_side("appmenu:minimize,maximize,close", "left")
    assert bl.set_side(left, "right") == "appmenu:minimize,maximize,close"


def test_spacer_and_menu_stay_on_their_side():
    assert bl.set_side("menu:spacer,close", "left") == "close,menu:spacer"


def test_side_detection():
    assert bl.side("close,minimize:appmenu") == "left"
    assert bl.side("appmenu:close") == "right"
    assert bl.side("appmenu:") == "right"
    assert bl.side("minimize:") == "left"


def test_has_button():
    assert bl.has_button("appmenu:minimize,close", "minimize")
    assert not bl.has_button("appmenu:close", "maximize")


def test_unknown_button_rejected():
    with pytest.raises(ValueError):
        bl.set_button("appmenu:close", "shade", True)

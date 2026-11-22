# SPDX-License-Identifier: GPL-3.0-or-later
"""Menus drawn by the shell: a Gio.MenuModel as JSON (see shellareas.py)."""

from gi.repository import GLib

ACTION_PREFIX = "win."


def strip_mnemonic(label):
    """"New _Folder…" -> "New Folder…"; "__" stands for "_"."""
    result = []
    chars = iter(label)
    for c in chars:
        if c == "_":
            c = next(chars, "")
        result.append(c)
    return "".join(result)


def _attribute(model, index, name):
    value = model.get_item_attribute_value(index, name, None)
    if value is None:
        return None
    return value.unpack()


def serialize(model, lookup_action, accel_label):
    """Sections of a menu: a list of lists of items.

    lookup_action(name): the Gio.Action of a window action, or None.
    accel_label(detailed_action): text of its shortcut, or "".
    Items that are neither sections nor submenus at the top level form a
    section of their own.
    """
    sections = []
    loose = []
    for i in range(model.get_n_items()):
        section = model.get_item_link(i, "section")
        if section is not None:
            if loose:
                sections.append(loose)
                loose = []
            items = _items(section, lookup_action, accel_label)
            if items:
                sections.append(items)
        else:
            item = _item(model, i, lookup_action, accel_label)
            if item is not None:
                loose.append(item)
    if loose:
        sections.append(loose)
    return sections


def _items(model, lookup_action, accel_label):
    items = []
    for i in range(model.get_n_items()):
        item = _item(model, i, lookup_action, accel_label)
        if item is not None:
            items.append(item)
    return items


def _item(model, index, lookup_action, accel_label):
    label = _attribute(model, index, "label")
    if label is None:
        return None
    submenu = model.get_item_link(index, "submenu")
    if submenu is not None:
        return {"label": strip_mnemonic(label), "action": None, "target": None,
                "enabled": True, "accel": "", "checked": None,
                "submenu": serialize(submenu, lookup_action, accel_label)}

    detailed = _attribute(model, index, "action") or ""
    target = _attribute(model, index, "target")
    if not detailed.startswith(ACTION_PREFIX):
        return None
    name = detailed[len(ACTION_PREFIX):]
    action = lookup_action(name)
    if action is None:
        return None
    checked = None
    state = action.get_state()
    if state is not None:
        # A radio item checks against its target, a toggle is a boolean.
        if target is not None:
            checked = state.unpack() == target
        elif state.is_of_type(GLib.VariantType.new("b")):
            checked = state.get_boolean()
    if target is not None:
        detailed = f"{detailed}::{target}"
    return {"label": strip_mnemonic(label), "action": name,
            "target": None if target is None else str(target),
            "enabled": action.get_enabled(), "accel": accel_label(detailed),
            "checked": checked, "submenu": None}

"""Stable server ordering helpers."""

from __future__ import annotations


def sort_servers_by_ping(
    servers: list,
    ping_by_index: dict[int, int | None],
    selected_index: int | None = None,
) -> tuple[list, int | None]:
    selected = None
    if selected_index is not None and 0 <= selected_index < len(servers):
        selected = servers[selected_index]

    indexed = list(enumerate(servers))
    indexed.sort(
        key=lambda item: (
            ping_by_index.get(item[0]) is None,
            ping_by_index.get(item[0]) if ping_by_index.get(item[0]) is not None else 0,
            item[0],
        )
    )
    ordered = [server for _index, server in indexed]

    new_selected_index = None
    if selected is not None:
        new_selected_index = next(
            (index for index, server in enumerate(ordered) if server is selected),
            None,
        )
    return ordered, new_selected_index

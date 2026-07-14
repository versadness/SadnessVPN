"""Pre-build validation for bundled native runtime files."""

from __future__ import annotations

import os
import struct


PE_MACHINE_AMD64 = 0x8664


class RuntimeArchitectureError(ValueError):
    """Raised when a bundled runtime file has an unsafe architecture."""


def read_pe_machine(path: str) -> int:
    """Return the machine field from a Windows PE file."""
    try:
        with open(path, "rb") as file:
            dos_header = file.read(64)
            if len(dos_header) < 64 or dos_header[:2] != b"MZ":
                raise RuntimeArchitectureError(f"Not a valid PE file: {path}")

            pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
            file.seek(pe_offset)
            pe_header = file.read(6)
    except OSError as exc:
        raise RuntimeArchitectureError(f"Cannot read runtime file: {path}") from exc

    if len(pe_header) < 6 or pe_header[:4] != b"PE\0\0":
        raise RuntimeArchitectureError(f"Not a valid PE file: {path}")

    return struct.unpack_from("<H", pe_header, 4)[0]


def validate_runtime_binaries(bin_dir: str) -> dict[str, int]:
    """Require matching 64-bit sing-box and Wintun runtime files."""
    expected_files = ("sing-box.exe", "wintun.dll")
    machines = {
        name: read_pe_machine(os.path.join(bin_dir, name))
        for name in expected_files
    }

    invalid = [
        f"{name}=0x{machine:04X}"
        for name, machine in machines.items()
        if machine != PE_MACHINE_AMD64
    ]
    if invalid:
        details = ", ".join(invalid)
        raise RuntimeArchitectureError(
            "SadnessVPN requires AMD64 (0x8664) runtime files; " + details
        )

    return machines

import os
import struct
import tempfile
import unittest
from pathlib import Path

from engine.runtime_validation import (
    PE_MACHINE_AMD64,
    RuntimeArchitectureError,
    read_pe_machine,
    validate_runtime_binaries,
)


PE_MACHINE_I386 = 0x014C


def _write_minimal_pe(path: Path, machine: int):
    content = bytearray(0x80)
    content[:2] = b"MZ"
    struct.pack_into("<I", content, 0x3C, 0x40)
    content[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<H", content, 0x44, machine)
    path.write_bytes(content)


class PeMachineParsingTests(unittest.TestCase):
    def test_reads_amd64_machine(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "runtime.exe")
            _write_minimal_pe(path, PE_MACHINE_AMD64)

            self.assertEqual(read_pe_machine(os.fspath(path)), PE_MACHINE_AMD64)

    def test_rejects_invalid_pe_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "runtime.exe")
            path.write_bytes(b"not a PE file")

            with self.assertRaisesRegex(RuntimeArchitectureError, "valid PE"):
                read_pe_machine(os.fspath(path))


class RuntimePairValidationTests(unittest.TestCase):
    @staticmethod
    def _write_all(bin_dir: Path, core_machine=PE_MACHINE_AMD64):
        awg_dir = bin_dir.joinpath("amneziawg")
        awg_dir.mkdir()
        _write_minimal_pe(bin_dir.joinpath("mihomo.exe"), core_machine)
        _write_minimal_pe(bin_dir.joinpath("wintun.dll"), PE_MACHINE_AMD64)
        _write_minimal_pe(awg_dir.joinpath("amneziawg.exe"), PE_MACHINE_AMD64)
        _write_minimal_pe(awg_dir.joinpath("awg.exe"), PE_MACHINE_AMD64)
        _write_minimal_pe(awg_dir.joinpath("wintun.dll"), PE_MACHINE_AMD64)

    def test_accepts_amd64_core_and_wintun(self):
        with tempfile.TemporaryDirectory() as root:
            bin_dir = Path(root)
            self._write_all(bin_dir)

            machines = validate_runtime_binaries(os.fspath(bin_dir))

            self.assertEqual(
                machines,
                {
                    "mihomo.exe": PE_MACHINE_AMD64,
                    "wintun.dll": PE_MACHINE_AMD64,
                    os.path.join("amneziawg", "amneziawg.exe"): PE_MACHINE_AMD64,
                    os.path.join("amneziawg", "awg.exe"): PE_MACHINE_AMD64,
                    os.path.join("amneziawg", "wintun.dll"): PE_MACHINE_AMD64,
                },
            )

    def test_rejects_x86_core_with_amd64_wintun(self):
        with tempfile.TemporaryDirectory() as root:
            bin_dir = Path(root)
            self._write_all(bin_dir, core_machine=PE_MACHINE_I386)

            with self.assertRaisesRegex(
                RuntimeArchitectureError,
                r"mihomo\.exe=0x014C",
            ):
                validate_runtime_binaries(os.fspath(bin_dir))

    def test_sing_box_is_no_longer_required_by_the_package(self):
        with tempfile.TemporaryDirectory() as root:
            bin_dir = Path(root)
            self._write_all(bin_dir)

            machines = validate_runtime_binaries(os.fspath(bin_dir))

            self.assertNotIn("sing-box.exe", machines)


if __name__ == "__main__":
    unittest.main()

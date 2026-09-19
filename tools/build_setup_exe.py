"""Build a single-file MSI bootstrapper carrying the Sadness VPN application icon."""
import hashlib
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.app_meta import APP_VERSION
from engine.update_policy import PRODUCT_CODE

MAGIC = b'SADNESSVPNMSI01'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    msi = ROOT / 'dist' / f'SadnessVPN-{APP_VERSION}-Setup-x64.msi'
    output = ROOT / 'dist' / f'SadnessVPN-{APP_VERSION}-Setup-x64.exe'
    compiler = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
    for required in (msi, compiler, ROOT / 'app.ico', ROOT / 'installer' / 'SetupBootstrap.cs'):
        if not required.is_file():
            raise FileNotFoundError(required)
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite existing setup: {output}')

    checksum = digest(msi)
    source = (ROOT / 'installer' / 'SetupBootstrap.cs').read_text(encoding='utf-8')
    replacements = {
        '__APP_VERSION__': APP_VERSION,
        '__PRODUCT_CODE__': PRODUCT_CODE,
        '__MSI_NAME__': msi.name,
        '__MSI_SHA256__': checksum,
    }
    for old, new in replacements.items():
        if old not in source:
            raise ValueError(f'Missing setup placeholder: {old}')
        source = source.replace(old, new)
    generated = ROOT / 'build' / f'SetupBootstrap-{APP_VERSION}.cs'
    generated.parent.mkdir(exist_ok=True)
    generated.write_text(source, encoding='utf-8-sig', newline='\r\n')
    stub = ROOT / 'build' / f'SadnessVPN-{APP_VERSION}-Setup-stub.exe'
    subprocess.run([
        str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
        '/reference:System.Windows.Forms.dll', '/out:' + str(stub),
        '/win32icon:' + str(ROOT / 'app.ico'), str(generated),
    ], check=True)
    with output.open('xb') as destination, stub.open('rb') as launcher, msi.open('rb') as payload:
        while block := launcher.read(1024 * 1024):
            destination.write(block)
        while block := payload.read(1024 * 1024):
            destination.write(block)
        destination.write(MAGIC)
        destination.write(struct.pack('<q', msi.stat().st_size))
    print(f'{output} sha256={digest(output)} bytes={output.stat().st_size} embedded_msi_sha256={checksum}')


if __name__ == '__main__':
    main()

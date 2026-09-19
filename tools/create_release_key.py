"""Create the publisher key outside the repository; print ONLY the public key."""
import argparse
import base64
import os
from pathlib import Path
import subprocess
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,PublicFormat,NoEncryption

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];directory=args.directory.resolve()
    if directory.is_relative_to(root):raise ValueError('Signing keys must stay outside the repository')
    directory.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        import win32api,win32security,win32con
        sid=win32security.GetTokenInformation(win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY),win32security.TokenUser)[0]
        user=win32security.ConvertSidToStringSid(sid)
        subprocess.run(['icacls.exe',str(directory),'/inheritance:r','/grant:r','*'+user+':(OI)(CI)F'],check=True,capture_output=True,creationflags=0x08000000)
    path=directory/'publisher-ed25519.pem'
    if path.exists():raise FileExistsError('Publisher key already exists; never replace it silently')
    key=Ed25519PrivateKey.generate()
    with path.open('xb') as stream:stream.write(key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
    print(base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode('ascii'))

if __name__=='__main__':main()

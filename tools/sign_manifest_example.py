"""Write a signed, LOCAL documentation example; never publishes or changes trust."""
import argparse
import base64
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from engine.update_manifest import canonical,verify
from engine.update_policy import PUBLIC_KEY_BASE64, ALLOWED_HOSTS
from engine.json_store import atomic_write_json


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--candidate',required=True,type=Path);parser.add_argument('--key',required=True,type=Path);args=parser.parse_args()
    data=json.loads((args.candidate/'update.json').read_text(encoding='utf-8'))
    key=load_pem_private_key(args.key.read_bytes(),password=None)
    data['signature']=base64.b64encode(key.sign(canonical(data))).decode('ascii')
    verify(data,PUBLIC_KEY_BASE64,ALLOWED_HOSTS or ['updates.example.invalid'],'beta')
    target=args.candidate/'signed-manifest.example.json'
    atomic_write_json(str(target),data)
    print('Signed LOCAL example verified. No publication.')


if __name__=='__main__':main()

"""Repeatable local build only. Publication is a separate command."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.app_meta import APP_VERSION

def main():
    p=argparse.ArgumentParser()
    # --msi-only: мажорный апгрейд, когда ProductCode сменился. Прямые MSP
    # с прежних версий в этом случае невозможны в принципе, поэтому шаги
    # сборки патчей и манифеста кандидата пропускаются.
    p.add_argument('--msi-only',action='store_true')
    # --base собирает прямой MSP с указанной версии. От MSP отказались: полный
    # MSI ставится поверх сам, поэтому по умолчанию баз нет и патчи не строятся.
    p.add_argument('--base',action='append',default=[]);p.add_argument('--notes')
    args=p.parse_args()
    from engine.update_manifest import version
    if not args.msi_only:
        if not args.notes:raise ValueError('--notes is required unless --msi-only')
    bases=sorted(set(args.base),key=version)
    if any(version(base)>=version(APP_VERSION) for base in bases):raise ValueError('Base must be older')
    if not args.msi_only and (ROOT/'dist/candidate'/APP_VERSION).exists():raise ValueError('Candidate already exists; do not overwrite tested files')
    commands=[
        # -t . импортирует tests как пакет: tests/__init__.py подменяет каталог
        # данных, и сборка не трогает профиль разработчика в ./data.
        [sys.executable,'-m','unittest','discover','-s','tests','-t','.','-q'],
        [sys.executable,'tools/test_rule_config_live.py'],
        [sys.executable,'tools/build_version_history.py'],
        [sys.executable,'-m','PyInstaller','--noconfirm','--workpath','build/pyinstaller-updater-'+APP_VERSION,'--distpath','dist/updater','SadnessUpdater.spec'],
        [sys.executable,'-m','PyInstaller','--noconfirm','--workpath','build/pyinstaller-'+APP_VERSION,'--distpath','dist/SadnessVPN-v'+APP_VERSION+'-installer-runtime','SadnessVPN.spec'],
        # Оболочка Electron собирается до MSI: build_msi.py забирает её вывод.
        ['npm.cmd' if sys.platform=='win32' else 'npm','run','pack:runtime'],
        [sys.executable,'installer/build_msi.py'],
    ]
    if not args.msi_only:
        commands += [[sys.executable,'installer/build_patch.py','--base',base,'--new',APP_VERSION] for base in bases]
        commands += [[sys.executable,'tools/release_candidate.py','--version',APP_VERSION,'--notes',args.notes,*[arg for base in bases for arg in ('--base',base)]]]
    for index,command in enumerate(commands):
        log=ROOT/'build'/f'candidate-{APP_VERSION}-{index}.log';log.parent.mkdir(exist_ok=True)
        with log.open('w',encoding='utf-8') as stream:
            result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(f'Step failed; inspect {log}')
        print(f'PASS step {index+1}/{len(commands)}',flush=True)
    print('MSI built.' if args.msi_only else 'Candidate built. Owner micro-test and separate publication approval still required.')

if __name__=='__main__':main()

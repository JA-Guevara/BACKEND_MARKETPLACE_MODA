"""Genera una clave local privada; no conecta a la base ni inicia una copia."""
from pathlib import Path
from cryptography.fernet import Fernet


def main():
    directory=Path(__file__).resolve().parents[2]/'_privado_bd'
    directory.mkdir(exist_ok=True)
    target=directory/'tenant-backup-encryption.env'
    if target.exists():
        raise SystemExit('Ya existe una clave privada. Conservála: reemplazarla impediría abrir las copias anteriores.')
    with target.open('x',encoding='utf-8') as output:
        output.write('TENANT_BACKUP_ENCRYPTION_KEY='+Fernet.generate_key().decode()+'\n')
    print('Clave creada en el archivo privado:',target)
    print('Configurá esa variable en el servidor y conservá la clave fuera de la plataforma. No la publiques en Git ni la envíes por chat.')


if __name__=='__main__':main()

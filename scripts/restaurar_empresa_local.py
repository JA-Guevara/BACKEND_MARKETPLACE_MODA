"""Ensaya un ZIP de negocio en una base LOCAL VACÍA. No admite destinos remotos."""
import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import re
import zipfile
from sqlalchemy import create_engine
import src.main  # registra los modelos
from src.infrastructure.database.base import Base
from src.infrastructure.database.safety import require_local_database
from src.plataforma_saas.application.tenant_backup_archive import restore_into_empty


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archivo',required=True,type=Path)
    parser.add_argument('--destino',required=True,help='URL de una base local vacía; nunca Supabase.')
    args=parser.parse_args()
    require_local_database(args.destino,allow_remote=False)
    with zipfile.ZipFile(args.archivo) as archive:
        if sum(info.file_size for info in archive.infolist())>100*1024*1024:
            raise SystemExit('El archivo supera 100 MB descomprimidos.')
        if len(archive.namelist())!=len(set(archive.namelist())):
            raise SystemExit('El archivo contiene entradas duplicadas.')
        manifest=json.loads(archive.read('manifest.json'))
        data=json.loads(archive.read('data.json'))
        files={}
        for name in archive.namelist():
            if name in ('manifest.json','data.json'): continue
            if not re.fullmatch(r'images/[0-9a-f]{32}\.webp',name):
                raise SystemExit('El paquete contiene una entrada no admitida.')
            raw=archive.read(name)
            files[name.split('/')[1]]={'data':base64.b64encode(raw).decode(),'sha256':sha256(raw).hexdigest()}
    engine=create_engine(args.destino)
    try:
        with engine.connect() as connection:
            if connection.dialect.name!='sqlite':
                raise SystemExit('El importador inicial admite ensayos SQLite. No aplica una recuperación sobre PostgreSQL en uso.')
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            Base.metadata.create_all(connection)
            connection.commit()
            with connection.begin():
                restore_into_empty(connection,{'manifest':manifest,'data':data,'files':files})
        print('Datos restaurados en el ensayo local. Cuentas inactivas. Las imágenes permanecen en el ZIP verificado.')
    finally:
        engine.dispose()


if __name__=='__main__': main()

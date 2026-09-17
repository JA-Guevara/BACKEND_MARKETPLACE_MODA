from hashlib import sha256

from pydantic import ValidationError as SchemaError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.shared.bulk.registry import RESOURCES, Resource
from src.shared.bulk.workbook import MAX_EXPORT_ROWS, build_workbook, read_rows
from src.shared.exceptions.base_exception import AppException
from src.shared.exceptions.domain_exception import ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import CollectionModel, SeasonModel


class ImportSession(Session):
    """Existing services own commit(); for a batch that means flush inside our transaction."""

    def commit(self):
        self.flush()


def resource_for(name: str) -> Resource:
    if name not in RESOURCES:
        raise ValidationError('Este recurso no admite cargas masivas.')
    return RESOURCES[name]


def reference_key(db, item, reference):
    parts = []
    for key in reference.keys:
        value = getattr(item, key)
        if key == 'season_id':
            season = db.get(SeasonModel, value) if value else None
            value = season.name if season else '(sin temporada)'
        parts.append(str(value or ''))
    return ' | '.join(parts)


def reference_map(db, reference):
    query = select(reference.model)
    if hasattr(reference.model, 'deleted_at'):
        query = query.where(reference.model.deleted_at.is_(None))
    items = db.scalars(query.limit(MAX_EXPORT_ROWS + 1)).unique().all()
    if len(items) > MAX_EXPORT_ROWS:
        raise ValidationError('Demasiadas referencias para Excel; máximo 10000.')
    result = {}
    for item in items:
        key = reference_key(db, item, reference)
        normalized = key.casefold()
        if normalized in result:
            raise ValidationError(f'Referencia ambigua: {key}. Corregí los nombres duplicados antes de importar.')
        result[normalized] = (item, key)
    return result


def workbook_for(db: Session, resource: Resource, *, template=False, search='', include_inactive=True,
                 include_deleted=False, branch_id=None):
    lookups = {}
    maps = {}
    for column, reference in resource.references.items():
        mapping = reference_map(db, reference)
        maps[column] = {item.id: key for item, key in mapping.values()}
        lookups[column] = [(key, getattr(item, 'name', key)) for item, key in mapping.values()]
    rows = []
    if not template:
        model = resource.model
        query = select(model)
        if hasattr(model, 'deleted_at') and not include_deleted:
            query = query.where(model.deleted_at.is_(None))
        if not include_inactive:
            query = query.where(model.is_active.is_(True))
        if search:
            fields = [getattr(model, key) for key in ('name', 'description', 'business_name', 'trade_name', 'tax_id', 'sku', 'brand')
                      if hasattr(model, key)]
            if fields:
                query = query.where(or_(*(column.ilike('%' + search + '%') for column in fields)))
        if branch_id and hasattr(model, 'branch_id'):
            query = query.where(model.branch_id == branch_id)
        records = db.scalars(query.order_by(model.id).limit(MAX_EXPORT_ROWS + 1)).unique().all()
        if len(records) > MAX_EXPORT_ROWS:
            raise ValidationError('La exportación supera 10000 registros. Reducí los filtros.')
        for item in records:
            row = {}
            for column in resource.columns:
                reference = resource.references.get(column)
                if reference:
                    reference_id = getattr(item, reference.target)
                    value = maps[column].get(reference_id)
                    if reference_id and value is None:
                        target = db.get(reference.model, reference_id)
                        value = reference_key(db, target, reference) if target else ''
                    row[column] = value
                else:
                    row[column] = getattr(item, column)
            rows.append(row)
    keys = [next((column for column, ref in resource.references.items() if ref.target == key), key)
            for key in resource.keys]
    instructions = [
        'FashionStore — completá únicamente la hoja Datos; no alteres sus encabezados.',
        'Clave estable: ' + ' + '.join(keys) + '. No se usan UUID. Estas claves no se cambian en modo Actualizar.',
        'Crear: rechaza claves existentes. Actualizar: exige que la clave exista; nunca crea registros.',
        'Máximo 1000 filas y 5 MB. Valores de referencia: copiar desde las hojas auxiliares.',
        'Las celdas vacías en Actualizar conservan el valor existente. Para borrar un valor, utilizá el formulario individual.',
        'No se importan estados, eliminaciones, permisos, contraseñas, pagos ni existencias.',
        'La vista previa prueba las mismas reglas del formulario y no guarda. Confirmar vuelve a validar; un error cancela todo el lote.',
        'Fechas: AAAA-MM-DD. Booleanos: TRUE/FALSE. NIT, códigos y teléfonos: formato Texto para preservar ceros.',
        'Prendas: importar después las variantes; imágenes y proveedores asociados se gestionan en Variantes y recursos.',
        'Orden sugerido: categorías, tallas, colores, temporadas, colecciones, prendas, variantes; ciudades, proveedores, sucursales, cajas.',
        'Las referencias compuestas usan « | »: ciudad | departamento | país; colección | temporada (o (sin temporada)).',
        'Exportación: todos los registros que coinciden con los filtros, hasta 10000; no solamente la página visible.',
        'Los horarios de sucursal se gestionan en el formulario individual y se conservan al actualizar con Excel.',
    ]
    return build_workbook(resource.columns, rows, lookups, instructions)


def _convert(db, resource, values, mode):
    data = {key: value for key, value in values.items() if value is not None and value != ''}
    for column, reference in resource.references.items():
        value = data.pop(column, None)
        if value is not None:
            resolved = reference_map(db, reference).get(str(value).strip().casefold())
            if not resolved:
                raise ValidationError(f'{column}: referencia no encontrada. Consultá la hoja auxiliar.')
            if not resolved[0].is_active:
                raise ValidationError(f'{column}: la referencia está inactiva.')
            data[reference.target] = resolved[0].id
    # Composite optional season is a meaningful stable-key component, not a random ID.
    if resource.model is CollectionModel and 'season_id' not in data:
        data['season_id'] = None
    for key in ('code', 'tax_id', 'sku', 'barcode', 'phone'):
        if key in data:
            data[key] = str(data[key])
    if 'country' in resource.keys and 'country' not in data:
        data['country'] = 'Bolivia'
    for key in resource.keys:
        if key not in data or (data[key] is None and key != 'season_id'):
            raise ValidationError(f'Falta la clave {key}. Completá todas las columnas de identificación.')
    query = select(resource.model)
    for key in resource.keys:
        value = data[key]
        column = getattr(resource.model, key)
        query = query.where(func.lower(column) == value.lower() if isinstance(value, str) else column == value)
    matches = db.scalars(query).unique().all()
    if len(matches) > 1:
        raise ValidationError('La clave coincide con varios registros; corregí los duplicados.')
    existing = matches[0] if matches else None
    if mode == 'create' and existing:
        raise ValidationError('La clave ya existe; utilizá Actualizar para modificarla.')
    if mode == 'update' and not existing:
        raise ValidationError('La clave no existe; utilizá Crear para darla de alta.')
    if existing and getattr(existing, 'deleted_at', None):
        raise ValidationError('El registro está eliminado; restauralo desde el formulario antes de actualizar.')
    if existing and 'product_id' in data and data['product_id'] != existing.product_id:
        raise ValidationError('Una variante no puede cambiar de prenda.')
    schema = resource.schema if mode == 'create' else resource.update_schema
    # product_id belongs to the add_variant service argument, not VariantCreate.
    product_id = data.pop('product_id', None)
    validated = schema.model_validate(data)
    return existing, validated, product_id


def process(db: Session, resource: Resource, actor, content: bytes, mode: str, *, confirm=False):
    if mode not in ('create', 'update'):
        raise ValidationError('Modo inválido. Elegí Crear o Actualizar.')
    rows = read_rows(content, resource.columns)
    report = {'digest': sha256(content).hexdigest(), 'mode': mode, 'total': len(rows),
              'valid': 0, 'errors': [], 'rows': [], 'imported': 0}
    # Service commits only flush. One outer savepoint contains every row and audit event.
    batch = db.begin_nested()
    work = ImportSession(bind=db.connection(), join_transaction_mode='rollback_only', expire_on_commit=False)
    seen = set()
    try:
        for number, values in rows:
            try:
                with work.begin_nested():
                    existing, data, product_id = _convert(work, resource, values, mode)
                    identity = tuple(str(getattr(data, key, None) if key != 'branch_id' else data.branch_id).casefold()
                                     for key in resource.keys)
                    if identity in seen:
                        raise ValidationError('Clave repetida dentro del archivo.')
                    seen.add(identity)
                    service = resource.service(work)
                    if resource.singular == 'variant':
                        if not product_id:
                            raise ValidationError('Falta product_slug.')
                        if mode == 'create':
                            service.add_variant(product_id, data, actor)
                        else:
                            service.update_variant(product_id, existing.id, data, actor)
                    elif mode == 'create':
                        getattr(service, 'create_' + resource.singular)(data, actor)
                    else:
                        getattr(service, 'update_' + resource.singular)(existing.id, data, actor)
                    work.flush()
                report['valid'] += 1
                report['rows'].append({'row': number, 'key': ' / '.join(identity), 'action': mode})
            except (AppException, SchemaError, IntegrityError) as exc:
                if isinstance(exc, SchemaError):
                    message = '; '.join('.'.join(map(str, err['loc'])) + ': ' + err['msg']
                                        for err in exc.errors(include_url=False, include_context=False, include_input=False))
                elif isinstance(exc, IntegrityError):
                    message = 'Conflicto de unicidad o relación. Revisá las claves y referencias.'
                else:
                    message = exc.message
                report['errors'].append({'row': number, 'message': message})
        if confirm and not report['errors']:
            RecordAuditEvent(work).execute(actor_user_id=actor.id, action='bulk.import',
                entity_type=resource.model.__tablename__, description=f'Importación Excel: {len(rows)} registros ({mode}).',
                metadata={'rows': len(rows), 'mode': mode, 'sha256': report['digest']})
            work.flush()
            work.close()
            batch.commit()
            db.commit()
            # ImportSession wrote through the same connection. Discard objects
            # cached by the request session before the import to avoid stale exports.
            db.expire_all()
            report['imported'] = len(rows)
        else:
            work.close()
            batch.rollback()
    except Exception:
        work.close()
        if batch.is_active:
            batch.rollback()
        raise
    return report

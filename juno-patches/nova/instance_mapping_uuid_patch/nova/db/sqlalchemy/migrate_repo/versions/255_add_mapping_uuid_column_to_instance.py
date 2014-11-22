from sqlalchemy import Column, String, MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    mapping_uuid = Column('mapping_uuid',
                          String(length=36))
    instances.create_column(mapping_uuid)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    mapping_uuid = instances.columns.mapping_uuid
    mapping_uuid.drop()

BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 20260903_0001

CREATE TABLE permissions (
    id UUID NOT NULL, 
    code VARCHAR(100) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    description VARCHAR(255), 
    module VARCHAR(50) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_permissions PRIMARY KEY (id), 
    CONSTRAINT uq_permissions_code UNIQUE (code)
);

CREATE INDEX ix_permissions_code ON permissions (code);

CREATE INDEX ix_permissions_module ON permissions (module);

CREATE TABLE roles (
    id UUID NOT NULL, 
    code VARCHAR(50) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    description VARCHAR(255), 
    is_system BOOLEAN DEFAULT false NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_roles PRIMARY KEY (id), 
    CONSTRAINT uq_roles_code UNIQUE (code)
);

CREATE INDEX ix_roles_code ON roles (code);

CREATE TABLE users (
    id UUID NOT NULL, 
    email VARCHAR(320) NOT NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    first_name VARCHAR(100) NOT NULL, 
    last_name VARCHAR(100) NOT NULL, 
    phone VARCHAR(30), 
    document_number VARCHAR(50), 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    is_verified BOOLEAN DEFAULT false NOT NULL, 
    failed_login_attempts INTEGER DEFAULT '0' NOT NULL, 
    locked_until TIMESTAMP WITH TIME ZONE, 
    last_login_at TIMESTAMP WITH TIME ZONE, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT uq_users_email UNIQUE (email), 
    CONSTRAINT uq_users_document_number UNIQUE (document_number)
);

CREATE INDEX ix_users_email ON users (email);

CREATE INDEX ix_users_deleted_at ON users (deleted_at);

CREATE TABLE role_permissions (
    role_id UUID NOT NULL, 
    permission_id UUID NOT NULL, 
    CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_id), 
    CONSTRAINT fk_role_permissions_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
    CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
);

CREATE TABLE user_roles (
    user_id UUID NOT NULL, 
    role_id UUID NOT NULL, 
    CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id), 
    CONSTRAINT fk_user_roles_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_user_roles_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE
);

CREATE TABLE refresh_tokens (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    jti VARCHAR(64) NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    replaced_by_jti VARCHAR(64), 
    created_by_ip VARCHAR(45), 
    revoked_by_ip VARCHAR(45), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_refresh_tokens PRIMARY KEY (id), 
    CONSTRAINT fk_refresh_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_refresh_tokens_jti UNIQUE (jti), 
    CONSTRAINT uq_refresh_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);

CREATE INDEX ix_refresh_tokens_jti ON refresh_tokens (jti);

CREATE TABLE password_reset_tokens (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_password_reset_tokens PRIMARY KEY (id), 
    CONSTRAINT fk_password_reset_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_password_reset_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_password_reset_tokens_user_id ON password_reset_tokens (user_id);

CREATE INDEX ix_password_reset_tokens_token_hash ON password_reset_tokens (token_hash);

CREATE TABLE email_verification_tokens (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_email_verification_tokens PRIMARY KEY (id), 
    CONSTRAINT fk_email_verification_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_email_verification_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_email_verification_tokens_user_id ON email_verification_tokens (user_id);

CREATE INDEX ix_email_verification_tokens_token_hash ON email_verification_tokens (token_hash);

CREATE TABLE user_addresses (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    label VARCHAR(50) NOT NULL, 
    recipient_name VARCHAR(200) NOT NULL, 
    phone VARCHAR(30) NOT NULL, 
    city VARCHAR(100) NOT NULL, 
    address_line VARCHAR(255) NOT NULL, 
    reference VARCHAR(255), 
    is_default BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_user_addresses PRIMARY KEY (id), 
    CONSTRAINT fk_user_addresses_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_addresses_user_id ON user_addresses (user_id);

CREATE TABLE audit_events (
    id UUID NOT NULL, 
    actor_user_id UUID, 
    action VARCHAR(100) NOT NULL, 
    entity_type VARCHAR(80) NOT NULL, 
    entity_id VARCHAR(100), 
    description TEXT NOT NULL, 
    metadata JSONB, 
    ip_address VARCHAR(45), 
    user_agent VARCHAR(500), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_audit_events PRIMARY KEY (id), 
    CONSTRAINT fk_audit_events_actor_user_id_users FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_events_actor_user_id ON audit_events (actor_user_id);

CREATE INDEX ix_audit_events_action ON audit_events (action);

CREATE INDEX ix_audit_events_entity_type ON audit_events (entity_type);

CREATE INDEX ix_audit_events_entity_id ON audit_events (entity_id);

CREATE INDEX ix_audit_events_created_at ON audit_events (created_at);

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000001', 'users.read', 'Consultar usuarios', 'Consultar usuarios y sus perfiles.', 'users', true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000002', 'users.write', 'Gestionar usuarios', 'Crear, editar, activar y eliminar usuarios.', 'users', true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000003', 'roles.read', 'Consultar roles', 'Consultar roles y permisos.', 'roles', true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000004', 'roles.write', 'Gestionar roles', 'Crear y modificar roles y permisos.', 'roles', true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000005', 'audit.read', 'Consultar bitacora', 'Consultar eventos de auditoria.', 'audit', true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO roles (id, code, name, description, is_system, is_active, created_at, updated_at) VALUES ('10000000-0000-0000-0000-000000000001', 'superadmin', 'Superadministrador', 'Control completo de la plataforma.', true, true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO roles (id, code, name, description, is_system, is_active, created_at, updated_at) VALUES ('10000000-0000-0000-0000-000000000002', 'admin', 'Administrador', 'Administracion general de la plataforma.', true, true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO roles (id, code, name, description, is_system, is_active, created_at, updated_at) VALUES ('10000000-0000-0000-0000-000000000003', 'store_manager', 'Encargado de sucursal', 'Operacion de una sucursal.', true, true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO roles (id, code, name, description, is_system, is_active, created_at, updated_at) VALUES ('10000000-0000-0000-0000-000000000004', 'cashier', 'Cajero', 'Ventas presenciales y caja.', true, true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO roles (id, code, name, description, is_system, is_active, created_at, updated_at) VALUES ('10000000-0000-0000-0000-000000000005', 'client', 'Cliente', 'Cliente de la tienda web y movil.', true, true, '2026-09-20 22:04:38.929396+00:00', '2026-09-20 22:04:38.929396+00:00');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000002');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000003');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000004');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000005');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000003');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000004');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000005');

INSERT INTO alembic_version (version_num) VALUES ('20260903_0001') RETURNING alembic_version.version_num;

-- Running upgrade 20260903_0001 -> 20260905_0002

CREATE TABLE cities (
    id UUID NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    department VARCHAR(100) NOT NULL, 
    country VARCHAR(100) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_cities PRIMARY KEY (id), 
    CONSTRAINT uq_cities_country UNIQUE (country, department, name)
);

CREATE INDEX ix_cities_name ON cities (name);

CREATE TABLE suppliers (
    id UUID NOT NULL, 
    business_name VARCHAR(180) NOT NULL, 
    trade_name VARCHAR(180), 
    tax_id VARCHAR(50) NOT NULL, 
    contact_name VARCHAR(150), 
    email VARCHAR(320), 
    phone VARCHAR(30), 
    address VARCHAR(255), 
    city VARCHAR(100), 
    notes TEXT, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_suppliers PRIMARY KEY (id), 
    CONSTRAINT uq_suppliers_tax_id UNIQUE (tax_id)
);

CREATE INDEX ix_suppliers_business_name ON suppliers (business_name);

CREATE INDEX ix_suppliers_tax_id ON suppliers (tax_id);

CREATE INDEX ix_suppliers_deleted_at ON suppliers (deleted_at);

CREATE TABLE branches (
    id UUID NOT NULL, 
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(150) NOT NULL, 
    city_id UUID NOT NULL, 
    address VARCHAR(255) NOT NULL, 
    phone VARCHAR(30), 
    latitude NUMERIC(10, 7), 
    longitude NUMERIC(10, 7), 
    opening_hours JSONB, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_branches PRIMARY KEY (id), 
    CONSTRAINT fk_branches_city_id_cities FOREIGN KEY(city_id) REFERENCES cities (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_branches_code UNIQUE (code), 
    CONSTRAINT uq_branches_city_id UNIQUE (city_id, name)
);

CREATE INDEX ix_branches_code ON branches (code);

CREATE INDEX ix_branches_name ON branches (name);

CREATE INDEX ix_branches_city_id ON branches (city_id);

CREATE INDEX ix_branches_deleted_at ON branches (deleted_at);

CREATE TABLE cash_points (
    id UUID NOT NULL, 
    branch_id UUID NOT NULL, 
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_cash_points PRIMARY KEY (id), 
    CONSTRAINT fk_cash_points_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_cash_points_branch_id UNIQUE (branch_id, code)
);

CREATE INDEX ix_cash_points_branch_id ON cash_points (branch_id);

CREATE INDEX ix_cash_points_deleted_at ON cash_points (deleted_at);

CREATE TABLE categories (
    id UUID NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    slug VARCHAR(140) NOT NULL, 
    description TEXT, 
    parent_id UUID, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_categories PRIMARY KEY (id), 
    CONSTRAINT fk_categories_parent_id_categories FOREIGN KEY(parent_id) REFERENCES categories (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_categories_slug UNIQUE (slug)
);

CREATE INDEX ix_categories_name ON categories (name);

CREATE INDEX ix_categories_slug ON categories (slug);

CREATE INDEX ix_categories_parent_id ON categories (parent_id);

CREATE TABLE sizes (
    id UUID NOT NULL, 
    code VARCHAR(30) NOT NULL, 
    name VARCHAR(80) NOT NULL, 
    sort_order INTEGER DEFAULT '0' NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_sizes PRIMARY KEY (id), 
    CONSTRAINT uq_sizes_code UNIQUE (code)
);

CREATE INDEX ix_sizes_code ON sizes (code);

CREATE TABLE colors (
    id UUID NOT NULL, 
    name VARCHAR(80) NOT NULL, 
    hex_code VARCHAR(7) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_colors PRIMARY KEY (id), 
    CONSTRAINT uq_colors_name UNIQUE (name), 
    CONSTRAINT uq_colors_hex_code UNIQUE (hex_code)
);

CREATE INDEX ix_colors_name ON colors (name);

CREATE TABLE seasons (
    id UUID NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    description TEXT, 
    start_date DATE, 
    end_date DATE, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_seasons PRIMARY KEY (id), 
    CONSTRAINT uq_seasons_name UNIQUE (name)
);

CREATE INDEX ix_seasons_name ON seasons (name);

CREATE TABLE collections (
    id UUID NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    description TEXT, 
    season_id UUID, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_collections PRIMARY KEY (id), 
    CONSTRAINT fk_collections_season_id_seasons FOREIGN KEY(season_id) REFERENCES seasons (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_collections_name UNIQUE (name, season_id)
);

CREATE INDEX ix_collections_name ON collections (name);

CREATE INDEX ix_collections_season_id ON collections (season_id);

CREATE TABLE products (
    id UUID NOT NULL, 
    name VARCHAR(180) NOT NULL, 
    slug VARCHAR(200) NOT NULL, 
    description TEXT NOT NULL, 
    brand VARCHAR(100), 
    gender VARCHAR(30), 
    base_price NUMERIC(12, 2) NOT NULL, 
    category_id UUID NOT NULL, 
    season_id UUID, 
    collection_id UUID, 
    is_featured BOOLEAN DEFAULT false NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_products PRIMARY KEY (id), 
    CONSTRAINT ck_products_ck_products_base_price_nonnegative CHECK (base_price >= 0), 
    CONSTRAINT fk_products_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_products_season_id_seasons FOREIGN KEY(season_id) REFERENCES seasons (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_products_collection_id_collections FOREIGN KEY(collection_id) REFERENCES collections (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_products_slug UNIQUE (slug)
);

CREATE INDEX ix_products_name ON products (name);

CREATE INDEX ix_products_slug ON products (slug);

CREATE INDEX ix_products_brand ON products (brand);

CREATE INDEX ix_products_gender ON products (gender);

CREATE INDEX ix_products_category_id ON products (category_id);

CREATE INDEX ix_products_season_id ON products (season_id);

CREATE INDEX ix_products_collection_id ON products (collection_id);

CREATE INDEX ix_products_is_featured ON products (is_featured);

CREATE INDEX ix_products_is_active ON products (is_active);

CREATE INDEX ix_products_deleted_at ON products (deleted_at);

CREATE TABLE product_variants (
    id UUID NOT NULL, 
    product_id UUID NOT NULL, 
    size_id UUID NOT NULL, 
    color_id UUID NOT NULL, 
    sku VARCHAR(80) NOT NULL, 
    barcode VARCHAR(80), 
    price_override NUMERIC(12, 2), 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_product_variants PRIMARY KEY (id), 
    CONSTRAINT ck_product_variants_ck_product_variants_price_override__0505 CHECK (price_override IS NULL OR price_override >= 0), 
    CONSTRAINT fk_product_variants_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
    CONSTRAINT fk_product_variants_size_id_sizes FOREIGN KEY(size_id) REFERENCES sizes (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_product_variants_color_id_colors FOREIGN KEY(color_id) REFERENCES colors (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_product_variants_product_id UNIQUE (product_id, size_id, color_id), 
    CONSTRAINT uq_product_variants_sku UNIQUE (sku), 
    CONSTRAINT uq_product_variants_barcode UNIQUE (barcode)
);

CREATE INDEX ix_product_variants_product_id ON product_variants (product_id);

CREATE INDEX ix_product_variants_size_id ON product_variants (size_id);

CREATE INDEX ix_product_variants_color_id ON product_variants (color_id);

CREATE INDEX ix_product_variants_sku ON product_variants (sku);

CREATE INDEX ix_product_variants_barcode ON product_variants (barcode);

CREATE TABLE product_images (
    id UUID NOT NULL, 
    product_id UUID NOT NULL, 
    url VARCHAR(1000) NOT NULL, 
    alt_text VARCHAR(255), 
    sort_order INTEGER DEFAULT '0' NOT NULL, 
    is_primary BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_product_images PRIMARY KEY (id), 
    CONSTRAINT fk_product_images_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE INDEX ix_product_images_product_id ON product_images (product_id);

CREATE TABLE ar_assets (
    id UUID NOT NULL, 
    product_id UUID NOT NULL, 
    asset_type VARCHAR(40) NOT NULL, 
    asset_url VARCHAR(1000) NOT NULL, 
    preview_url VARCHAR(1000), 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ar_assets PRIMARY KEY (id), 
    CONSTRAINT fk_ar_assets_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE INDEX ix_ar_assets_product_id ON ar_assets (product_id);

CREATE TABLE product_suppliers (
    id UUID NOT NULL, 
    product_id UUID NOT NULL, 
    supplier_id UUID NOT NULL, 
    supplier_sku VARCHAR(100), 
    unit_cost NUMERIC(12, 2), 
    is_primary BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_product_suppliers PRIMARY KEY (id), 
    CONSTRAINT ck_product_suppliers_ck_product_suppliers_unit_cost_nonnegative CHECK (unit_cost IS NULL OR unit_cost >= 0), 
    CONSTRAINT fk_product_suppliers_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
    CONSTRAINT fk_product_suppliers_supplier_id_suppliers FOREIGN KEY(supplier_id) REFERENCES suppliers (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_product_suppliers_product_id UNIQUE (product_id, supplier_id)
);

CREATE INDEX ix_product_suppliers_product_id ON product_suppliers (product_id);

CREATE INDEX ix_product_suppliers_supplier_id ON product_suppliers (supplier_id);

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000006', 'catalog.read', 'Consultar catalogo', 'Consultar productos y datos maestros.', 'catalog', true, '2026-09-20 22:04:38.975222+00:00', '2026-09-20 22:04:38.975222+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000007', 'catalog.write', 'Gestionar catalogo', 'Crear y modificar productos y datos maestros.', 'catalog', true, '2026-09-20 22:04:38.975222+00:00', '2026-09-20 22:04:38.975222+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000008', 'suppliers.read', 'Consultar proveedores', 'Consultar proveedores registrados.', 'suppliers', true, '2026-09-20 22:04:38.975222+00:00', '2026-09-20 22:04:38.975222+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000009', 'suppliers.write', 'Gestionar proveedores', 'Crear y modificar proveedores.', 'suppliers', true, '2026-09-20 22:04:38.975222+00:00', '2026-09-20 22:04:38.975222+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000010', 'branches.read', 'Consultar sucursales', 'Consultar ciudades, sucursales y cajas.', 'branches', true, '2026-09-20 22:04:38.975222+00:00', '2026-09-20 22:04:38.975222+00:00');

INSERT INTO permissions (id, code, name, description, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000011', 'branches.write', 'Gestionar sucursales', 'Crear y modificar ciudades, sucursales y cajas.', 'branches', true, '2026-09-20 22:04:38.975222+00:00', '2026-09-20 22:04:38.975222+00:00');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000006');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000007');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000008');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000009');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000010');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000011');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000006');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000007');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000008');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000009');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000010');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000011');

UPDATE alembic_version SET version_num='20260905_0002' WHERE alembic_version.version_num = '20260903_0001';

-- Running upgrade 20260905_0002 -> 20260910_0003

CREATE TABLE commerce_stock (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    variant_id UUID NOT NULL, 
    branch_id UUID NOT NULL, 
    quantity INTEGER DEFAULT '0' NOT NULL, 
    CONSTRAINT pk_commerce_stock PRIMARY KEY (id), 
    CONSTRAINT ck_commerce_stock_quantity_positive CHECK (quantity >= 0), 
    CONSTRAINT uq_commerce_stock_variant_id UNIQUE (variant_id, branch_id), 
    CONSTRAINT fk_commerce_stock_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_commerce_stock_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id) ON DELETE RESTRICT
);

CREATE TABLE commerce_cart_items (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    user_id UUID NOT NULL, 
    variant_id UUID NOT NULL, 
    quantity INTEGER NOT NULL, 
    CONSTRAINT pk_commerce_cart_items PRIMARY KEY (id), 
    CONSTRAINT ck_commerce_cart_items_quantity_positive CHECK (quantity > 0), 
    CONSTRAINT uq_commerce_cart_items_user_id UNIQUE (user_id, variant_id), 
    CONSTRAINT fk_commerce_cart_items_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_commerce_cart_items_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT
);

CREATE INDEX ix_commerce_cart_items_user_id ON commerce_cart_items (user_id);

CREATE TABLE commerce_orders (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    number VARCHAR(40) NOT NULL, 
    user_id UUID NOT NULL, 
    branch_id UUID NOT NULL, 
    customer_email VARCHAR(320) NOT NULL, 
    status VARCHAR(30) DEFAULT 'pending_payment' NOT NULL, 
    payment_status VARCHAR(30) DEFAULT 'pending' NOT NULL, 
    payment_method VARCHAR(30) NOT NULL, 
    payment_reference VARCHAR(255), 
    total NUMERIC(12, 2) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    address JSON NOT NULL, 
    items JSON NOT NULL, 
    tracking JSON NOT NULL, 
    carrier VARCHAR(120), 
    tracking_number VARCHAR(150), 
    stripe_session_id VARCHAR(255), 
    stripe_url VARCHAR(2000), 
    CONSTRAINT pk_commerce_orders PRIMARY KEY (id), 
    CONSTRAINT uq_commerce_orders_number UNIQUE (number), 
    CONSTRAINT fk_commerce_orders_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_commerce_orders_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_commerce_orders_stripe_session_id UNIQUE (stripe_session_id)
);

CREATE INDEX ix_commerce_orders_user_id ON commerce_orders (user_id);

CREATE INDEX ix_commerce_orders_status ON commerce_orders (status);

CREATE TABLE commerce_webhook_events (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    event_id VARCHAR(255) NOT NULL, 
    CONSTRAINT pk_commerce_webhook_events PRIMARY KEY (id), 
    CONSTRAINT uq_commerce_webhook_events_event_id UNIQUE (event_id)
);

INSERT INTO permissions (id, code, name, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000012', 'commerce.read', 'commerce.read', 'commerce', true, '2026-09-20 22:04:38.984649+00:00', '2026-09-20 22:04:38.984649+00:00');

INSERT INTO permissions (id, code, name, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000013', 'commerce.write', 'commerce.write', 'commerce', true, '2026-09-20 22:04:38.984649+00:00', '2026-09-20 22:04:38.984649+00:00');

INSERT INTO permissions (id, code, name, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000014', 'stock.read', 'stock.read', 'stock', true, '2026-09-20 22:04:38.984649+00:00', '2026-09-20 22:04:38.984649+00:00');

INSERT INTO permissions (id, code, name, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000015', 'stock.write', 'stock.write', 'stock', true, '2026-09-20 22:04:38.984649+00:00', '2026-09-20 22:04:38.984649+00:00');

INSERT INTO permissions (id, code, name, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000016', 'dashboard.read', 'dashboard.read', 'dashboard', true, '2026-09-20 22:04:38.984649+00:00', '2026-09-20 22:04:38.984649+00:00');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000012');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000013');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000014');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000015');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000016');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000012');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000013');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000014');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000015');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000016');

UPDATE alembic_version SET version_num='20260910_0003' WHERE alembic_version.version_num = '20260905_0002';

-- Running upgrade 20260910_0003 -> 20260912_0004

ALTER TABLE user_addresses ADD COLUMN postal_code VARCHAR(20);

ALTER TABLE user_addresses ADD COLUMN country VARCHAR(2) DEFAULT 'BO' NOT NULL;

UPDATE alembic_version SET version_num='20260912_0004' WHERE alembic_version.version_num = '20260910_0003';

-- Running upgrade 20260912_0004 -> 20260912_0005

CREATE TABLE reservations (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    user_id UUID NOT NULL, 
    branch_id UUID NOT NULL, 
    status VARCHAR(30) DEFAULT 'pending' NOT NULL, 
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    items JSON NOT NULL, 
    notes VARCHAR(1000), 
    tracking JSON DEFAULT '[]' NOT NULL, 
    CONSTRAINT pk_reservations PRIMARY KEY (id), 
    CONSTRAINT fk_reservations_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_reservations_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id) ON DELETE RESTRICT
);

CREATE INDEX ix_reservations_user_id ON reservations (user_id);

CREATE INDEX ix_reservations_branch_id ON reservations (branch_id);

CREATE INDEX ix_reservations_status ON reservations (status);

INSERT INTO permissions (id, code, name, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000017', 'reservations.read', 'reservations.read', 'reservations', true, '2026-09-20 22:04:38.991010+00:00', '2026-09-20 22:04:38.991010+00:00');

INSERT INTO permissions (id, code, name, module, is_active, created_at, updated_at) VALUES ('20000000-0000-0000-0000-000000000018', 'reservations.write', 'reservations.write', 'reservations', true, '2026-09-20 22:04:38.991010+00:00', '2026-09-20 22:04:38.991010+00:00');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000017');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000018');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000017');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000018');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000017');

INSERT INTO role_permissions (role_id, permission_id) VALUES ('10000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000018');

UPDATE alembic_version SET version_num='20260912_0005' WHERE alembic_version.version_num = '20260912_0004';

-- Running upgrade 20260912_0005 -> 20260916_0006

ALTER TABLE reservations ADD COLUMN client_key VARCHAR(64);

ALTER TABLE reservations ADD CONSTRAINT uq_reservations_user_client_key UNIQUE (user_id, client_key);

UPDATE alembic_version SET version_num='20260916_0006' WHERE alembic_version.version_num = '20260912_0005';

-- Running upgrade 20260916_0006 -> 20260916_0007

ALTER TABLE commerce_orders ADD COLUMN paid_at TIMESTAMP WITHOUT TIME ZONE;

CREATE INDEX ix_commerce_orders_paid_at ON commerce_orders (paid_at);

UPDATE alembic_version SET version_num='20260916_0007' WHERE alembic_version.version_num = '20260916_0006';

-- Running upgrade 20260916_0007 -> 20260917_0008

ALTER TABLE commerce_orders ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE commerce_orders ADD COLUMN sales_channel VARCHAR(10) DEFAULT 'web' NOT NULL;

ALTER TABLE commerce_orders ADD COLUMN cash_point_id UUID;

ALTER TABLE commerce_orders ADD COLUMN cashier_user_id UUID;

ALTER TABLE commerce_orders ADD COLUMN client_request_id UUID;

ALTER TABLE commerce_orders ADD COLUMN request_fingerprint VARCHAR(64);

ALTER TABLE commerce_orders ADD CONSTRAINT fk_commerce_orders_cash_point_id_cash_points FOREIGN KEY(cash_point_id) REFERENCES cash_points (id) ON DELETE RESTRICT;

ALTER TABLE commerce_orders ADD CONSTRAINT fk_commerce_orders_cashier_user_id_users FOREIGN KEY(cashier_user_id) REFERENCES users (id) ON DELETE RESTRICT;

ALTER TABLE commerce_orders ADD CONSTRAINT uq_commerce_orders_client_request_id UNIQUE (client_request_id);

CREATE TABLE commerce_stock_movements (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    variant_id UUID NOT NULL, 
    branch_id UUID NOT NULL, 
    delta INTEGER NOT NULL, 
    quantity_before INTEGER NOT NULL, 
    quantity_after INTEGER NOT NULL, 
    kind VARCHAR(40) NOT NULL, 
    reason VARCHAR(500) NOT NULL, 
    reference VARCHAR(100), 
    actor_id UUID, 
    actor_email VARCHAR(320), 
    CONSTRAINT pk_commerce_stock_movements PRIMARY KEY (id), 
    CONSTRAINT ck_commerce_stock_movements_nonnegative_balances CHECK (quantity_before >= 0 AND quantity_after >= 0), 
    CONSTRAINT ck_commerce_stock_movements_balanced_movement CHECK (quantity_after = quantity_before + delta), 
    CONSTRAINT fk_commerce_stock_movements_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_commerce_stock_movements_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_commerce_stock_movements_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_commerce_stock_movements_variant_id ON commerce_stock_movements (variant_id);

CREATE INDEX ix_commerce_stock_movements_branch_id ON commerce_stock_movements (branch_id);

UPDATE alembic_version SET version_num='20260917_0008' WHERE alembic_version.version_num = '20260916_0007';

-- Running upgrade 20260917_0008 -> 20260917_0009

ALTER TABLE reservations ADD COLUMN inventory_held BOOLEAN DEFAULT false NOT NULL;

UPDATE alembic_version SET version_num='20260917_0009' WHERE alembic_version.version_num = '20260917_0008';

-- Running upgrade 20260917_0009 -> 20260917_0010

CREATE TABLE virtual_tryon_assets (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    product_id UUID NOT NULL, 
    color_id UUID NOT NULL, 
    enabled BOOLEAN DEFAULT true NOT NULL, 
    mode VARCHAR(10) DEFAULT '2.5d' NOT NULL, 
    source_image_url VARCHAR(1000) NOT NULL, 
    transparent_url VARCHAR(1000), 
    mask_url VARCHAR(1000), 
    model_3d_url VARCHAR(1000), 
    garment_type VARCHAR(40), 
    body_region VARCHAR(20), 
    anchor_points JSONB, 
    ai_status VARCHAR(20) DEFAULT 'pending' NOT NULL, 
    ai_metadata JSONB, 
    ai_error TEXT, 
    CONSTRAINT pk_virtual_tryon_assets PRIMARY KEY (id), 
    CONSTRAINT tryon_producto_color UNIQUE (product_id, color_id), 
    CONSTRAINT fk_virtual_tryon_assets_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
    CONSTRAINT fk_virtual_tryon_assets_color_id_colors FOREIGN KEY(color_id) REFERENCES colors (id) ON DELETE RESTRICT
);

CREATE INDEX ix_virtual_tryon_assets_product_id ON virtual_tryon_assets (product_id);

CREATE INDEX ix_virtual_tryon_assets_color_id ON virtual_tryon_assets (color_id);

CREATE INDEX ix_virtual_tryon_assets_body_region ON virtual_tryon_assets (body_region);

UPDATE alembic_version SET version_num='20260917_0010' WHERE alembic_version.version_num = '20260917_0009';

-- Running upgrade 20260917_0010 -> 20260918_0011

ALTER TABLE branches ADD COLUMN notification_email VARCHAR(320);

UPDATE alembic_version SET version_num='20260918_0011' WHERE alembic_version.version_num = '20260917_0010';

-- Running upgrade 20260918_0011 -> 20260918_0012

CREATE TABLE commerce_order_returns (
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    order_id UUID NOT NULL, 
    user_id UUID, 
    branch_id UUID NOT NULL, 
    status VARCHAR(20) DEFAULT 'requested' NOT NULL, 
    reason VARCHAR(500) NOT NULL, 
    items JSON NOT NULL, 
    refund_amount NUMERIC(12, 2) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    resolution_note VARCHAR(500), 
    resolved_at TIMESTAMP WITH TIME ZONE, 
    resolved_by UUID, 
    client_request_id UUID, 
    CONSTRAINT pk_commerce_order_returns PRIMARY KEY (id), 
    CONSTRAINT fk_commerce_order_returns_order_id_commerce_orders FOREIGN KEY(order_id) REFERENCES commerce_orders (id) ON DELETE CASCADE, 
    CONSTRAINT fk_commerce_order_returns_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_commerce_order_returns_branch_id_branches FOREIGN KEY(branch_id) REFERENCES branches (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_commerce_order_returns_resolved_by_users FOREIGN KEY(resolved_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT uq_commerce_order_returns_client_request_id UNIQUE (client_request_id)
);

CREATE INDEX ix_commerce_order_returns_order_id ON commerce_order_returns (order_id);

CREATE INDEX ix_commerce_order_returns_user_id ON commerce_order_returns (user_id);

CREATE INDEX ix_commerce_order_returns_branch_id ON commerce_order_returns (branch_id);

CREATE INDEX ix_commerce_order_returns_status ON commerce_order_returns (status);

UPDATE alembic_version SET version_num='20260918_0012' WHERE alembic_version.version_num = '20260918_0011';

COMMIT;


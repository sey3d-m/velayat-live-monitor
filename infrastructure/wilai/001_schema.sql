-- WilAI proposed metadata schema (NOT installed or deployed).
-- Requires MySQL/MariaDB with utf8mb4. Keep confidential texts outside public_html.
-- Review Netafraz E1 database version/quota before applying.
CREATE TABLE IF NOT EXISTS wilai_users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email VARCHAR(254) NOT NULL,
  display_name VARCHAR(150) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('administrator','editor','researcher','viewer') NOT NULL DEFAULT 'viewer',
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_wilai_user_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS wilai_documents (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_system VARCHAR(48) NOT NULL,
  external_id VARCHAR(190) NOT NULL,
  title VARCHAR(500) NOT NULL,
  locale VARCHAR(16) NOT NULL DEFAULT 'fa',
  visibility ENUM('public','staff','restricted') NOT NULL DEFAULT 'staff',
  storage_path VARCHAR(1000) NOT NULL,
  sha256 CHAR(64) NOT NULL,
  bytes BIGINT UNSIGNED NOT NULL,
  imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_wilai_source_ref (source_system,external_id),
  KEY ix_wilai_visibility (visibility),
  KEY ix_wilai_source_system (source_system)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS wilai_audit_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  actor_id BIGINT UNSIGNED NULL,
  actor_type ENUM('user','automation') NOT NULL,
  action VARCHAR(80) NOT NULL,
  entity_type VARCHAR(64) NOT NULL,
  entity_id VARCHAR(190) NOT NULL,
  event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  meta_json TEXT NULL,
  PRIMARY KEY (id),
  KEY ix_wilai_audit_entity (entity_type,entity_id),
  KEY ix_wilai_audit_time (event_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

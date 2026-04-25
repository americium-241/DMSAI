"""LDAP / Active Directory authentication backend for DMSAI.

Uses the ``ldap3`` library.  All configuration is read from ``SystemConfig``
rows in the ``ldap`` category so it can be changed from the admin UI or
pre-seeded via ``auth.yaml``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from dmsai_models import SystemConfig, get_session

logger = logging.getLogger("dmsai.ldap")

try:
    import ldap3
    from ldap3 import Server, Connection, ALL, SUBTREE, Tls
    from ldap3.core.exceptions import LDAPException

    LDAP_AVAILABLE = True
except ImportError:
    LDAP_AVAILABLE = False


@dataclass
class LdapUserInfo:
    email: str
    full_name: str
    dn: str


def _get_ldap_config() -> dict:
    with get_session() as session:
        rows = session.query(SystemConfig).filter(
            SystemConfig.category == "ldap"
        ).all()
    return {r.key: r.value for r in rows}


def is_ldap_enabled() -> bool:
    cfg = _get_ldap_config()
    return cfg.get("ldap_enabled", "false").lower() == "true"


def authenticate_ldap(username: str, password: str) -> Optional[LdapUserInfo]:
    """Try to authenticate *username* / *password* against the configured LDAP
    server.  Returns ``LdapUserInfo`` on success, ``None`` on failure.
    """
    if not LDAP_AVAILABLE:
        logger.error("ldap3 package not installed — LDAP auth unavailable")
        return None

    cfg = _get_ldap_config()
    if cfg.get("ldap_enabled", "false").lower() != "true":
        return None

    server_url = cfg.get("ldap_server_url", "")
    if not server_url:
        logger.error("ldap_server_url is empty")
        return None

    bind_dn = cfg.get("ldap_bind_dn", "")
    bind_password = cfg.get("ldap_bind_password", "")
    search_base = cfg.get("ldap_search_base", "")
    user_filter = cfg.get("ldap_user_filter", "(uid={username})")
    email_attr = cfg.get("ldap_email_attribute", "mail")
    name_attr = cfg.get("ldap_fullname_attribute", "cn")
    use_tls = cfg.get("ldap_use_tls", "false").lower() == "true"
    require_group = cfg.get("ldap_require_group", "").strip()
    group_attr = cfg.get("ldap_group_attribute", "memberOf")

    import ssl as _ssl
    tls_config = Tls(validate=_ssl.CERT_REQUIRED) if use_tls or server_url.startswith("ldaps://") else None
    server = Server(server_url, get_info=ALL, tls=tls_config)

    search_filter = user_filter.replace("{username}", ldap3.utils.conv.escape_filter_chars(username))

    try:
        if bind_dn:
            conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
        else:
            conn = Connection(server, auto_bind=True)

        if use_tls and not server_url.startswith("ldaps://"):
            conn.start_tls()

        conn.search(
            search_base,
            search_filter,
            search_scope=SUBTREE,
            attributes=[email_attr, name_attr, group_attr],
        )

        if not conn.entries:
            logger.info("LDAP user not found: %s", username)
            conn.unbind()
            return None

        entry = conn.entries[0]
        user_dn = str(entry.entry_dn)
        conn.unbind()

        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        user_conn.unbind()

        email_val = str(getattr(entry, email_attr, "")) if hasattr(entry, email_attr) else ""
        name_val = str(getattr(entry, name_attr, username)) if hasattr(entry, name_attr) else username

        if not email_val:
            email_val = f"{username}@ldap.local"

        if require_group:
            groups = getattr(entry, group_attr, [])
            group_list = [str(g) for g in groups] if groups else []
            if require_group not in group_list:
                logger.info("LDAP user %s not in required group %s", username, require_group)
                return None

        return LdapUserInfo(email=email_val, full_name=name_val, dn=user_dn)

    except LDAPException:
        logger.info("LDAP authentication failed for %s", username)
        return None
    except Exception:
        logger.exception("Unexpected error during LDAP auth for %s", username)
        return None

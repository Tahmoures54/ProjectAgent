# tests/test_two_factor.py
from __future__ import annotations

import pyotp

from pms_app.blueprints.auth.helpers.two_factor import (
    consume_backup_code,
    generate_backup_codes,
    hash_backup_codes,
    make_qr_data_uri,
    verify_totp,
)
from pms_app.models.user import User


def _create_user(session, email_prefix, password="pass1234"):
    user = User(email=f"{email_prefix}@example.com", full_name=email_prefix, is_active=True)
    user.set_password(password)
    session.add(user)
    session.commit()
    return user


def _login(client, email, password="pass1234"):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=False)


def test_qr_data_uri_is_png():
    uri = "otpauth://totp/Project%20Agent:u@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Project%20Agent"
    data = make_qr_data_uri(uri)
    assert data and data.startswith("data:image/png;base64,")


def test_backup_code_consumed_once():
    codes = generate_backup_codes(2)
    stored = hash_backup_codes(codes)
    updated = consume_backup_code(stored, codes[0])
    assert updated is not None
    assert consume_backup_code(updated, codes[0]) is None
    assert consume_backup_code(updated, codes[1]) is not None


def test_login_with_2fa_redirects_to_challenge(client, db_session):
    user = _create_user(db_session, "tfa1")
    secret = pyotp.random_base32()
    user.two_fa_enabled = True
    user.two_fa_secret = secret
    db_session.commit()

    response = _login(client, user.email)
    assert response.status_code in (301, 302)
    assert "/login/2fa" in response.headers.get("Location", "")


def test_login_2fa_accepts_totp(client, db_session):
    user = _create_user(db_session, "tfa2")
    secret = pyotp.random_base32()
    user.two_fa_enabled = True
    user.two_fa_secret = secret
    db_session.commit()

    _login(client, user.email)
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code)
    response = client.post("/login/2fa", data={"otp_code": code}, follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/dashboard" in response.headers.get("Location", "") or "/users" in response.headers.get("Location", "")


def test_login_2fa_rejects_wrong_code(client, db_session):
    user = _create_user(db_session, "tfa3")
    user.two_fa_enabled = True
    user.two_fa_secret = pyotp.random_base32()
    db_session.commit()

    _login(client, user.email)
    response = client.post("/login/2fa", data={"otp_code": "000000"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "نادرست" in html or "Authenticator" in html


def test_login_2fa_accepts_backup_code_once(client, db_session):
    user = _create_user(db_session, "tfa4")
    codes = generate_backup_codes(2)
    user.two_fa_enabled = True
    user.two_fa_secret = pyotp.random_base32()
    user.two_fa_backup_hashes = hash_backup_codes(codes)
    db_session.commit()

    _login(client, user.email)
    response = client.post("/login/2fa", data={"otp_code": codes[0]}, follow_redirects=False)
    assert response.status_code in (301, 302)

    client.get("/logout")
    _login(client, user.email)
    again = client.post("/login/2fa", data={"otp_code": codes[0]})
    assert again.status_code == 200


def test_enable_2fa_page_requires_login(client):
    response = client.get("/enable-2fa", follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/login" in response.headers.get("Location", "")


def test_enable_2fa_shows_qr_and_confirms(client, db_session):
    user = _create_user(db_session, "tfa5")
    _login(client, user.email)

    page = client.get("/enable-2fa")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "data:image/png;base64," in html
    assert "Google Authenticator" in html
    assert "Microsoft Authenticator" in html

    with client.session_transaction() as sess:
        secret = sess.get("2fa_secret")
    assert secret
    code = pyotp.TOTP(secret).now()
    response = client.post("/enable-2fa", data={"otp_code": code}, follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/enable-2fa/backup-codes" in response.headers.get("Location", "")

    backup_page = client.get("/enable-2fa/backup-codes")
    assert backup_page.status_code == 200
    assert "کدهای پشتیبان" in backup_page.get_data(as_text=True)

    refreshed = db_session.get(User, user.id)
    db_session.refresh(refreshed)
    assert refreshed.two_fa_enabled is True
    assert refreshed.two_fa_secret == secret
    assert refreshed.two_fa_backup_hashes


def test_disable_2fa_requires_password(client, db_session):
    user = _create_user(db_session, "tfa6")
    _login(client, user.email)
    user.two_fa_enabled = True
    user.two_fa_secret = pyotp.random_base32()
    db_session.commit()

    bad = client.post("/disable-2fa", data={"disable-current_password": "wrong-pass"}, follow_redirects=False)
    assert bad.status_code in (301, 302)
    db_session.refresh(user)
    assert user.two_fa_enabled is True

    ok = client.post("/disable-2fa", data={"disable-current_password": "pass1234"}, follow_redirects=False)
    assert ok.status_code in (301, 302)
    db_session.refresh(user)
    assert user.two_fa_enabled is False
    assert user.two_fa_secret is None


def test_change_password_links_to_authenticator(client, db_session):
    user = _create_user(db_session, "tfa7")
    _login(client, user.email)
    html = client.get("/change-password").get_data(as_text=True)
    assert "/enable-2fa" in html
    assert "Authenticator" in html

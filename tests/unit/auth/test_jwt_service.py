from src.auth.infrastructure.security.jwt_service import JWTService


def test_access_token_round_trip() -> None:
    service = JWTService()
    token, expires_in = service.create_access_token("123")
    payload = service.decode(token, "access")
    assert payload["sub"] == "123"
    assert expires_in > 0


def test_refresh_tokens_include_unique_identifiers() -> None:
    service = JWTService()
    first, first_jti, _ = service.create_refresh_token("123")
    second, second_jti, _ = service.create_refresh_token("123")
    assert first != second
    assert first_jti != second_jti

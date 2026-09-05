import pytest

from src.auth.domain.password_policy import PasswordPolicy
from src.shared.exceptions.domain_exception import ValidationError


def test_accepts_a_strong_password() -> None:
    PasswordPolicy.validate("RopaSegura!2026", email="cliente@example.com")


@pytest.mark.parametrize(
    "password",
    ["corta1!", "sinmayuscula!2026", "SINMINUSCULA!2026", "SinNumeroEspecial!", "SinEspecial2026"],
)
def test_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(ValidationError):
        PasswordPolicy.validate(password)


def test_rejects_password_containing_email_name() -> None:
    with pytest.raises(ValidationError):
        PasswordPolicy.validate("cliente-Seguro!2026", email="cliente@example.com")

import re

from src.shared.exceptions.domain_exception import ValidationError


class PasswordPolicy:
    minimum_length = 12

    @classmethod
    def validate(cls, password: str, *, email: str | None = None) -> None:
        errors: list[str] = []
        if len(password) < cls.minimum_length:
            errors.append(f"Debe tener al menos {cls.minimum_length} caracteres.")
        if not re.search(r"[A-Z]", password):
            errors.append("Debe incluir una letra mayuscula.")
        if not re.search(r"[a-z]", password):
            errors.append("Debe incluir una letra minuscula.")
        if not re.search(r"\d", password):
            errors.append("Debe incluir un numero.")
        if not re.search(r"[^A-Za-z0-9]", password):
            errors.append("Debe incluir un caracter especial.")
        if email and email.split("@", 1)[0].lower() in password.lower():
            errors.append("No debe contener el nombre del correo electronico.")
        if errors:
            raise ValidationError("La contrasena no cumple la politica de seguridad.", details={"errors": errors})

"""Tests for schema name normalization (#6)."""
from idi.generation.spec_loader import normalize_schema_name


class TestSchemaNameNormalization:
    def test_strip_response_suffix(self):
        assert normalize_schema_name("UserResponse") == "User"

    def test_strip_dto_suffix(self):
        assert normalize_schema_name("UserDTO") == "User"

    def test_strip_create_prefix(self):
        assert normalize_schema_name("CreateUser") == "User"

    def test_strip_model_suffix(self):
        assert normalize_schema_name("UserModel") == "User"

    def test_no_suffix_to_strip(self):
        assert normalize_schema_name("User") == "User"

    def test_guard_empty_result(self):
        """Stripping 'Model' from 'Model' would leave empty, keep original."""
        assert normalize_schema_name("Model") == "Model"

    def test_guard_short_result(self):
        """Stripping 'DTO' from 'DTO' would leave empty, keep original."""
        assert normalize_schema_name("DTO") == "DTO"

    def test_first_matching_suffix_only(self):
        """UserResponseDTO ends with 'DTO', which matches first in suffix list."""
        assert normalize_schema_name("UserResponseDTO") == "UserResponse"

    def test_strip_input_suffix(self):
        assert normalize_schema_name("UserInput") == "User"

    def test_strip_request_suffix(self):
        assert normalize_schema_name("UserRequest") == "User"

    def test_strip_update_prefix(self):
        assert normalize_schema_name("UpdateUser") == "User"

    def test_strip_patch_prefix(self):
        assert normalize_schema_name("PatchUser") == "User"

    def test_suffix_preferred_over_prefix(self):
        """If both suffix and prefix could match, suffix wins (tried first)."""
        assert normalize_schema_name("CreateUserResponse") == "CreateUser"

    def test_short_result_guard_2_chars(self):
        """Result of 2 chars or less keeps original."""
        assert normalize_schema_name("GoModel") == "GoModel"

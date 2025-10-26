"""
Unit tests for CommandValidators

Test philosophy (pair-programming style):
- Test boundary conditions (empty, negative, wrong types)
- Test business rules (must be > 0, non-negative, etc.)
- Test error messages are descriptive
- Property tests would be ideal but manual execution for now
"""

import pytest
from cupertino_nvr.processor.validators import CommandValidators, CommandValidationError


class TestValidateModelId:
    """Test validate_model_id method."""

    def test_valid_model_id(self):
        """Valid model_id should return normalized value."""
        assert CommandValidators.validate_model_id("yolov8x-640") == "yolov8x-640"

    def test_strips_whitespace(self):
        """Should strip leading/trailing whitespace."""
        assert CommandValidators.validate_model_id("  yolov11x-640  ") == "yolov11x-640"

    def test_empty_string_raises_error(self):
        """Empty string should raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="must be non-empty"):
            CommandValidators.validate_model_id("")

    def test_whitespace_only_raises_error(self):
        """Whitespace-only string should raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="must be non-empty"):
            CommandValidators.validate_model_id("   ")

    def test_non_string_raises_error(self):
        """Non-string input should raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="must be string"):
            CommandValidators.validate_model_id(123)

        with pytest.raises(CommandValidationError, match="must be string"):
            CommandValidators.validate_model_id(None)

        with pytest.raises(CommandValidationError, match="must be string"):
            CommandValidators.validate_model_id(["yolov8x"])


class TestValidateFps:
    """Test validate_fps method."""

    def test_valid_fps_float(self):
        """Valid float FPS should return float."""
        assert CommandValidators.validate_fps(1.5) == 1.5

    def test_valid_fps_int(self):
        """Valid int FPS should return float."""
        assert CommandValidators.validate_fps(5) == 5.0

    def test_string_numeric_converts(self):
        """Numeric string should convert to float."""
        assert CommandValidators.validate_fps("0.5") == 0.5
        assert CommandValidators.validate_fps("10") == 10.0

    def test_zero_raises_error(self):
        """Zero FPS should raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="must be > 0"):
            CommandValidators.validate_fps(0)

        with pytest.raises(CommandValidationError, match="must be > 0"):
            CommandValidators.validate_fps(0.0)

    def test_negative_raises_error(self):
        """Negative FPS should raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="must be > 0"):
            CommandValidators.validate_fps(-1.5)

        with pytest.raises(CommandValidationError, match="must be > 0"):
            CommandValidators.validate_fps(-10)

    def test_non_numeric_raises_error(self):
        """Non-numeric input should raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="must be numeric"):
            CommandValidators.validate_fps("not-a-number")

        with pytest.raises(CommandValidationError, match="must be numeric"):
            CommandValidators.validate_fps(None)

        with pytest.raises(CommandValidationError, match="must be numeric"):
            CommandValidators.validate_fps([1.5])


class TestValidateSourceId:
    """Test validate_source_id method."""

    def test_valid_source_id_int(self):
        """Valid int source_id should return int."""
        assert CommandValidators.validate_source_id(8) == 8

    def test_valid_source_id_string(self):
        """Valid string source_id should convert to int."""
        assert CommandValidators.validate_source_id("10") == 10

    def test_zero_is_valid(self):
        """Zero source_id should be valid."""
        assert CommandValidators.validate_source_id(0) == 0
        assert CommandValidators.validate_source_id("0") == 0

    def test_float_converts_to_int(self):
        """Float source_id should convert to int (truncate)."""
        assert CommandValidators.validate_source_id(3.14) == 3
        assert CommandValidators.validate_source_id(8.9) == 8

    def test_negative_raises_error(self):
        """Negative source_id should raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="cannot be negative"):
            CommandValidators.validate_source_id(-1)

        with pytest.raises(CommandValidationError, match="cannot be negative"):
            CommandValidators.validate_source_id("-5")

    def test_non_numeric_raises_error(self):
        """Non-numeric input should raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="must be numeric"):
            CommandValidators.validate_source_id("not-a-number")

        with pytest.raises(CommandValidationError, match="must be numeric"):
            CommandValidators.validate_source_id(None)

        with pytest.raises(CommandValidationError, match="must be numeric"):
            CommandValidators.validate_source_id([8])


class TestCommandValidationError:
    """Test CommandValidationError exception."""

    def test_is_value_error_subclass(self):
        """CommandValidationError should be a ValueError subclass."""
        assert issubclass(CommandValidationError, ValueError)

    def test_can_be_raised_with_message(self):
        """CommandValidationError should accept error message."""
        with pytest.raises(CommandValidationError, match="test error"):
            raise CommandValidationError("test error")
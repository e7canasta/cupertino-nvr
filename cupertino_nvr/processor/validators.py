"""
Command Parameter Validators
=============================

Bounded context: Input validation for MQTT control commands.

This module is separated from command handlers to enable:
- Independent testing (property tests for validation rules)
- Clear validation rules documentation
- Easy extension (new commands = new validators)
- Reusability across different command handlers

Philosophy (Manifiesto de Diseño):
- "Cohesión > Ubicación" - Validators have one reason to change (business rules)
- "¿Este código es testeable en aislación?" - YES with bounded context
- "Simple para leer, NO simple para escribir una vez" - Clear validation logic
"""

from typing import Any


class CommandValidationError(ValueError):
    """
    Command parameter validation failed.

    This exception is raised when MQTT command parameters fail validation.
    The error message should be descriptive enough to send back to the client.
    """
    pass


class CommandValidators:
    """
    Validators for MQTT command parameters.

    All validators follow the same pattern:
    1. Accept ANY type (defensive)
    2. Validate type and business rules
    3. Return validated/normalized value
    4. Raise CommandValidationError with descriptive message on failure

    Usage:
        >>> from cupertino_nvr.processor.validators import CommandValidators
        >>> model_id = CommandValidators.validate_model_id("yolov8x-640")
        >>> fps = CommandValidators.validate_fps(1.5)
        >>> source_id = CommandValidators.validate_source_id(8)
    """

    @staticmethod
    def validate_model_id(model_id: Any) -> str:
        """
        Validate model_id parameter for CHANGE_MODEL command.

        Rules:
        - Must be non-empty string
        - Trimmed of leading/trailing whitespace

        Args:
            model_id: Model ID to validate (accepts any type)

        Returns:
            Validated and normalized model_id (stripped string)

        Raises:
            CommandValidationError: If validation fails

        Examples:
            >>> CommandValidators.validate_model_id("yolov8x-640")
            'yolov8x-640'
            >>> CommandValidators.validate_model_id("  yolov11x-640  ")
            'yolov11x-640'
            >>> CommandValidators.validate_model_id("")
            CommandValidationError: Invalid model_id: must be non-empty string
            >>> CommandValidators.validate_model_id(123)
            CommandValidationError: Invalid model_id: must be string, got int
        """
        if not isinstance(model_id, str):
            raise CommandValidationError(
                f"Invalid model_id: must be string, got {type(model_id).__name__}"
            )

        model_id_stripped = model_id.strip()
        if not model_id_stripped:
            raise CommandValidationError(
                f"Invalid model_id: must be non-empty string (got {model_id!r})"
            )

        return model_id_stripped

    @staticmethod
    def validate_fps(fps: Any) -> float:
        """
        Validate max_fps parameter for SET_FPS command.

        Rules:
        - Must be numeric (int or float)
        - Must be > 0

        Args:
            fps: FPS value to validate (accepts any type)

        Returns:
            Validated FPS as float

        Raises:
            CommandValidationError: If validation fails

        Examples:
            >>> CommandValidators.validate_fps(1.0)
            1.0
            >>> CommandValidators.validate_fps(5)
            5.0
            >>> CommandValidators.validate_fps("0.5")
            0.5
            >>> CommandValidators.validate_fps(0)
            CommandValidationError: Invalid max_fps: must be > 0
            >>> CommandValidators.validate_fps(-1.5)
            CommandValidationError: Invalid max_fps: must be > 0
            >>> CommandValidators.validate_fps("not a number")
            CommandValidationError: Invalid max_fps: must be numeric, got 'not a number'
        """
        try:
            fps_float = float(fps)
        except (ValueError, TypeError) as e:
            raise CommandValidationError(
                f"Invalid max_fps: must be numeric, got {fps!r}"
            ) from e

        if fps_float <= 0:
            raise CommandValidationError(
                f"Invalid max_fps: must be > 0, got {fps_float}"
            )

        return fps_float

    @staticmethod
    def validate_source_id(source_id: Any) -> int:
        """
        Validate source_id parameter for ADD_STREAM/REMOVE_STREAM commands.

        Rules:
        - Must be numeric (int or string convertible to int)
        - Must be >= 0 (non-negative)

        Args:
            source_id: Source ID to validate (accepts any type)

        Returns:
            Validated source_id as int

        Raises:
            CommandValidationError: If validation fails

        Examples:
            >>> CommandValidators.validate_source_id(8)
            8
            >>> CommandValidators.validate_source_id("10")
            10
            >>> CommandValidators.validate_source_id(0)
            0
            >>> CommandValidators.validate_source_id(-1)
            CommandValidationError: Invalid source_id: cannot be negative
            >>> CommandValidators.validate_source_id("not a number")
            CommandValidationError: Invalid source_id: must be numeric, got 'not a number'
            >>> CommandValidators.validate_source_id(3.14)
            3
        """
        try:
            source_id_int = int(source_id)
        except (ValueError, TypeError) as e:
            raise CommandValidationError(
                f"Invalid source_id: must be numeric, got {source_id!r}"
            ) from e

        if source_id_int < 0:
            raise CommandValidationError(
                f"Invalid source_id: cannot be negative, got {source_id_int}"
            )

        return source_id_int
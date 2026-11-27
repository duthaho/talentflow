"""Framework-free version preconditions shared by versioned commands."""


class VersionPreconditionRequiredError(ValueError):
    pass


class InvalidVersionPreconditionError(ValueError):
    pass


class VersionPreconditionFailedError(RuntimeError):
    def __init__(self, current_version: int):
        self.current_version = current_version
        super().__init__("Resource has changed; refresh and retry")


def resolve_expected_version(
    *, current_version: int, expected_version: int | None, if_match: tuple[str, ...] | None
) -> int:
    """Resolve header alternatives to the version used by the atomic repository write.

    Tokens are unquoted strong validators, or a lone wildcard, parsed by the API.
    A body-only mismatch remains the command's existing concurrency conflict.
    """
    if if_match is None:
        if expected_version is None:
            raise VersionPreconditionRequiredError("Supply If-Match or expected_version")
        return expected_version
    if (
        expected_version is not None
        and if_match != ("*",)
        and str(expected_version) not in if_match
    ):
        raise InvalidVersionPreconditionError("If-Match and expected_version disagree")
    if if_match != ("*",) and str(current_version) not in if_match:
        raise VersionPreconditionFailedError(current_version)
    if expected_version is not None and expected_version != current_version:
        raise VersionPreconditionFailedError(current_version)
    return current_version

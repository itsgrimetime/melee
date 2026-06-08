"""DecompMeAuthError must be a DecompMeAPIError subclass so callers can either
catch it specifically (to stop a batch on a dead cookie) or fall through to the
generic API-error handler."""

from src.client import DecompMeAPIError, DecompMeAuthError


def test_auth_error_is_api_error_subclass():
    assert issubclass(DecompMeAuthError, DecompMeAPIError)


def test_auth_error_instance_is_api_error():
    err = DecompMeAuthError("403")
    assert isinstance(err, DecompMeAPIError)
    assert str(err) == "403"

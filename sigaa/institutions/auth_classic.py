"""Classic SIGAA form authentication, with fields discovered from each render.

The flow is based on JucaGF/sigaa-tools-ufcg (MIT); see docs/institutions/ufcg.md.
No enrollment worker or submission logic is included.
"""
from ..errors import LoginRejectedError, MissingCredentialsError
from ..parsers.authentication import (
    authenticated_portal, has_account_picker, has_login_form, login_action,
)


def perform_login(session, profile):
    if not session._username or not session._password:
        raise MissingCredentialsError("missing SIGAA username or password")
    client = session._client
    page = client.get(profile.logon_url, follow_redirects=True)
    page.raise_for_status()
    action = login_action(page.text, str(page.url))
    # Check the action before adding secrets. Request hooks also guard redirects.
    profile.validate_url(action.action)
    fields = dict(action.fields)
    fields[action.username_field] = session._username
    fields[action.password_field] = session._password
    response = client.post(action.action, data=fields, follow_redirects=True)
    response.raise_for_status()
    if authenticated_portal(response.text, response.url, profile):
        return response.text
    if has_login_form(response.text):
        raise LoginRejectedError("login rejected; check credentials or required CAPTCHA/2FA")
    # An account/vínculo picker must be handled by the student, never bypassed.
    if has_account_picker(response.text):
        raise LoginRejectedError("login requires account selection")
    response = client.get(profile.portal_entry_url, follow_redirects=True)
    response.raise_for_status()
    if not authenticated_portal(response.text, response.url, profile):
        raise LoginRejectedError("login did not reach the authenticated student portal")
    return response.text

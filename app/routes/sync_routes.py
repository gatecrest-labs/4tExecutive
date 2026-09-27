"""Receives 4tSuite's pushed group-membership changes for this app.

New, additive blueprint -- 4texecutive's existing tab_required/
user_has_tab/groups.json enforcement is completely untouched; this
route only ever edits group membership, the same way an admin editing
config/groups.json by hand already could.

Exempt from CSRF: this is a pure bearer-token API endpoint with no
session/cookie involvement at all, authenticated by verify_service_token
instead -- Flask-WTF's CSRFProtect otherwise rejects every non-GET
request lacking a session-tied CSRF token, regardless of whether the
request uses cookies at all.
"""

from __future__ import annotations

from flask import Blueprint, abort, request

from app import csrf
from app.groups import add_group_member, list_group_names, remove_group_member
from app.sso_verify import verify_service_token

bp = Blueprint("sync", __name__)
csrf.exempt(bp)


@bp.route("/4tsuite/groups", methods=["POST"])
def receive_group_push():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    claims = verify_service_token(token, expected_scope="groups_push")
    if claims is None:
        abort(403)
    data = request.get_json()
    if data["group"] not in list_group_names():
        abort(400, description=f"no such group: {data['group']}")
    if data["member"]:
        add_group_member(data["group"], data["username"])
    else:
        remove_group_member(data["group"], data["username"])
    return "", 204

#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course,
# and is released under the "MIT License Agreement". Please see the LICENSE
# file that should have been included as part of this package.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
app.sampleapp
~~~~~~~~~~~~~~~~~

Sample REST app with Phase 3 cookie-based session authentication.
"""

import asyncio
import json
import secrets
import time
from urllib.parse import parse_qs

from daemon import AsynapRous

app = AsynapRous()

SESSION_COOKIE = "session_id"
SESSION_TTL_SECONDS = 3600

USERS = {
    "alice": {
        "password": "wonderland",
        "role": "user",
    },
    "admin": {
        "password": "admin123",
        "role": "admin",
    },
}

SESSIONS = {}


def json_response(body, status=200, headers=None):
    return {
        "status": status,
        "headers": headers or {},
        "body": body,
        "content_type": "application/json; charset=utf-8",
    }


def parse_body(body, headers):
    content_type = headers.get("Content-Type", "")
    if not body:
        return {}
    if "application/json" in content_type:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def create_session(username):
    session_id = secrets.token_urlsafe(32)
    SESSIONS[session_id] = {
        "username": username,
        "role": USERS[username]["role"],
        "created_at": time.time(),
    }
    return session_id


def get_session(request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None

    session = SESSIONS.get(session_id)
    if not session:
        return None

    if time.time() - session["created_at"] > SESSION_TTL_SECONDS:
        SESSIONS.pop(session_id, None)
        return None

    return session


def require_user(request):
    session = get_session(request)
    if not session:
        return None, json_response(
            {"error": "Unauthorized", "message": "Login required"},
            status=401,
        )
    return session, None


def require_role(request, role):
    session, error = require_user(request)
    if error:
        return None, error
    if session["role"] != role:
        return None, json_response(
            {"error": "Forbidden", "message": "Insufficient permission"},
            status=403,
        )
    return session, None


def session_cookie(session_id):
    return (
        "{}={}; Path=/; Max-Age={}; HttpOnly; SameSite=Lax".format(
            SESSION_COOKIE,
            session_id,
            SESSION_TTL_SECONDS,
        )
    )


def expired_session_cookie():
    return (
        "{}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax".format(
            SESSION_COOKIE
        )
    )


@app.route("/login", methods=["POST", "PUT"])
def login(headers, body, request):
    data = parse_body(body, headers)
    username = data.get("username", "")
    password = data.get("password", "")
    user = USERS.get(username)

    if not user or user["password"] != password:
        return json_response(
            {"error": "Unauthorized", "message": "Invalid credentials"},
            status=401,
        )

    session_id = create_session(username)
    return json_response(
        {
            "message": "Login successful",
            "username": username,
            "role": user["role"],
        },
        headers={"Set-Cookie": session_cookie(session_id)},
    )


@app.route("/logout", methods=["POST", "PUT"])
def logout(headers, body, request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        SESSIONS.pop(session_id, None)

    return json_response(
        {"message": "Logout successful"},
        headers={"Set-Cookie": expired_session_cookie()},
    )


@app.route("/private", methods=["GET"])
def private(headers, body, request):
    session, error = require_user(request)
    if error:
        return error
    return json_response(
        {
            "message": "Private route access granted",
            "username": session["username"],
            "role": session["role"],
        }
    )


@app.route("/admin", methods=["GET"])
def admin(headers, body, request):
    session, error = require_role(request, "admin")
    if error:
        return error
    return json_response(
        {
            "message": "Admin route access granted",
            "username": session["username"],
        }
    )


@app.route("/echo", methods=["POST"])
def echo(headers="guest", body="anonymous"):
    try:
        message = json.loads(body)
        return json_response({"received": message})
    except json.JSONDecodeError:
        return json_response({"error": "Invalid JSON"}, status=400)


@app.route("/hello", methods=["POST"])
def hello(headers, body):
    data = {"id": 1, "name": "Alice", "email": "alice@example.com"}
    return json_response(data)


@app.route("/async-hello", methods=["GET"])
async def async_hello(headers, body, request):
    await asyncio.sleep(0.01)
    return json_response({"message": "Hello from async route"})


def create_sampleapp(ip, port):
    app.prepare_address(ip, port)
    app.run()

#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.backend
~~~~~~~~~~~~~~~~~

This module provides a backend object to manage and persist backend daemon.
Phase 4 prioritizes the asyncio backend while keeping the older synchronous
socket handlers available as compatibility fallbacks.

Requirements:
--------------
- socket: provide socket networking interface.
- threading: Enables concurrent client handling via threads.
- response: response utilities.
- httpadapter: the class for handling HTTP requests.
- CaseInsensitiveDict: provides dictionary for managing headers or routes.


Notes:
------
- The server create daemon threads for client handling.
- The current implementation error handling is minimal, socket errors are printed to the console.
- The actual request processing is delegated to the HttpAdapter class.

Usage Example:
--------------
>>> create_backend("127.0.0.1", 9000, routes={})

"""

import asyncio
import inspect
import logging
import socket
import threading

from .httpadapter import HttpAdapter

LOGGER = logging.getLogger(__name__)

mode_async = "coroutine"


def configure_logging():
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="[%(levelname)s] %(name)s: %(message)s",
        )


def log_routes(routes, label="Route settings"):
    if not routes:
        return
    LOGGER.info(label)
    for key, value in routes.items():
        marker = "**ASYNC** " if inspect.iscoroutinefunction(value) else ""
        LOGGER.info(
            "   + ('%s', '%s'): %s%s",
            key[0],
            key[1],
            marker,
            str(value),
        )


def handle_client(ip, port, conn, addr, routes):
    """
    Initializes an HttpAdapter instance and delegates the client handling logic to it.

    :param ip (str): IP address of the server.
    :param port (int): Port number the server is listening on.
    :param conn (socket.socket): Client connection socket.
    :param addr (tuple): client address (IP, port).
    :param routes (dict): Dictionary of route handlers.
    """
    LOGGER.info("Handling accepted connection from %s", addr)
    daemon = HttpAdapter(ip, port, conn, addr, routes)

    # Handle client
    daemon.handle_client(conn, addr, routes)


# Callback for handling new client (itself run in sync mode)
def handle_client_callback(server, ip, port, conn, addr, routes):
    """
    Initialize connection instance and delegates the client handling logic to it.

    :param ip (str): IP address of the server.
    :param port (int): Port number the server is listening on.
    :param routes (dict): Dictionary of route handlers.
    """
    LOGGER.info("Handling callback connection from %s", addr)

    daemon = HttpAdapter(ip, port, conn, addr, routes)

    # Handle client
    daemon.handle_client(conn, addr, routes)


# Coroutine async/await for handling new client
async def handle_client_coroutine(reader, writer, routes=None):
    """
    Coroutine in async communication to initialize connection instance
    then delegates the client handling logic to it.

    :param reader (StreamReader): Stream reader wrapper.
    :param write (Stream write): Stream write wrapper.
    """
    addr = writer.get_extra_info("peername")
    LOGGER.info("Async accepted connection from %s", addr)
    daemon = HttpAdapter(None, None, None, addr, routes or {})
    await daemon.handle_client_coroutine(reader, writer)


async def async_server(ip="0.0.0.0", port=7000, routes=None):
    routes = routes or {}
    configure_logging()

    LOGGER.info("asyncio backend listening on %s:%s", ip, port)
    log_routes(routes, label="Async route settings")

    try:
        server = await asyncio.start_server(
            lambda reader, writer: handle_client_coroutine(reader, writer, routes),
            ip,
            port,
            reuse_address=True,
        )
    except OSError as exc:
        LOGGER.error("Cannot bind backend on %s:%s: %s", ip, port, exc)
        raise

    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    LOGGER.info("asyncio.start_server active sockets: %s", sockets)
    try:
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        LOGGER.info("Async backend cancellation requested")
        raise
    finally:
        server.close()
        await server.wait_closed()
        LOGGER.info("Async backend closed on %s:%s", ip, port)
    return


def run_backend(ip, port, routes):
    """
    Starts the backend server, binds to the specified IP and port, and listens for incoming
    connections. Each connection is handled in a separate thread. The backend accepts incoming
    connections and spawns a thread for each client.


    :param ip (str): IP address to bind the server.
    :param port (int): Port number to listen on.
    :param routes (dict): Dictionary of route handlers.
    """
    # This global variable to configure the asynchrnous mode or not
    global mode_async

    configure_logging()

    routes = routes or {}
    LOGGER.info("run_backend with routes=%s", routes)
    # Process async stream for registering the service and terminate
    if mode_async == "coroutine":

        try:
            asyncio.run(async_server(ip, port, routes))
        except KeyboardInterrupt:
            LOGGER.info("Backend stopped by keyboard interrupt")
        return

    # Process socket object
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((ip, port))
        server.listen(50)

        LOGGER.info("Listening on %s:%s", ip, port)
        log_routes(routes)

        while True:
            # Accept connection
            conn, addr = server.accept()

            if mode_async == "callback":
                handle_client_callback(server, ip, port, conn, addr, routes)

            else:
                client_thread = threading.Thread(
                    target=handle_client,
                    args=(ip, port, conn, addr, routes),
                )
                client_thread.daemon = True
                client_thread.start()


    except KeyboardInterrupt:
        LOGGER.info("Backend stopped by keyboard interrupt")
    except socket.error as e:
        LOGGER.error("Socket error: %s", e)
    finally:
        server.close()


def create_backend(ip, port, routes=None):
    """
    Entry point for creating and running the backend server.

    :param ip (str): IP address to bind the server.
    :param port (int): Port number to listen on.
    :param routes (dict, optional): Dictionary of route handlers. Defaults to empty dict.
    """

    run_backend(ip, port, routes or {})

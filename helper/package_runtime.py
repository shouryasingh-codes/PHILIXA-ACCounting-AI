"""Packaged lifecycle adapter. No installation or credential mutation on import."""
import asyncio
import ctypes
import os
from pathlib import Path


def is_packaged():
    if os.name != 'nt':
        return False
    size = ctypes.c_uint32(0)
    # APPMODEL_ERROR_NO_PACKAGE=15700; insufficient buffer=122 means packaged.
    result = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(size), None)
    if result == 15700:
        return False
    if result != 122:
        raise RuntimeError('Windows package identity unavailable')
    return True


def data_home():
    if not is_packaged():
        return Path(os.environ.get('LOCALAPPDATA', '.')) / 'PhilixaConnect'
    from winrt.windows.storage import ApplicationData
    return Path(ApplicationData.current.local_folder.path) / 'PhilixaConnect'


def startup_state():
    if not is_packaged():
        return 'legacy'
    from winrt.windows.applicationmodel import StartupTask
    async def read():
        task = await StartupTask.get_async('PhilixaStartup')
        return {0: 'disabled', 1: 'disabled_by_user', 2: 'enabled',
                3: 'disabled_by_policy', 4: 'enabled_by_policy'}.get(int(task.state), 'unknown')
    return asyncio.run(read())


def startup_enabled(state):
    return state in ('enabled', 'enabled_by_policy')

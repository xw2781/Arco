
import os
import sys
import stat
import time
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from server_config import resolve_server_config_path, write_server_config


PROJECT_ROOT_NAME = "Arco Server"
DEFAULT_DEPLOY_ROOT = Path(os.environ.get("ARCRHO_DEPLOY_ROOT", rf"E:\{PROJECT_ROOT_NAME}")).expanduser()

COMPONENTS = {
    "admin": {
        "dirs": ("arcrho_admin",),
        "apps": ("ArcRho Admin Control",),
    },
    "engine": {
        "dirs": ("arcrho_engine", "ArcRho Engine", "ADAS Agent"),
        "apps": ("ArcRho Engine", "ADAS Agent"),
    },
    "orchestrator": {
        "dirs": ("arcrho_orchestrator", "ArcRho Orchestrator", "ADAS Master"),
        "apps": ("ArcRho Orchestrator", "ADAS Master"),
    },
    "launcher": {
        "dirs": ("arcrho_launcher", "ArcRho Launcher", "ADAS Shell"),
        "apps": ("ArcRho Launcher", "ADAS Shell"),
    },
    "bridge": {
        "dirs": ("arcrho_bridge",),
        "apps": ("ArcRho Bridge",),
    },
    "bridge_worker": {
        "dirs": ("arcrho_bridge_worker",),
        "apps": ("ArcRho Bridge Worker",),
    },
    "gateway": {
        "dirs": ("arcrho_gateway",),
        "apps": ("ArcRho Gateway",),
    },
    "credential": {
        "dirs": ("arcrho_credential",),
        "apps": ("ArcRho Credential",),
    },
}

COMPONENT_ALIASES = {
    "admin": "admin",
    "admin_control": "admin",
    "agent": "engine",
    "worker": "engine",
    "engine": "engine",
    "master": "orchestrator",
    "manager": "orchestrator",
    "supervisor": "orchestrator",
    "orchestrator": "orchestrator",
    "shell": "launcher",
    "launcher": "launcher",
    "bridge": "bridge",
    "rpc_bridge": "bridge",
    "bridge_worker": "bridge_worker",
    "rpc_bridge_worker": "bridge_worker",
    "gateway": "gateway",
    "credential": "credential",
}

SERVER_COMPONENT_ROLES = (
    "admin",
    "bridge",
    "engine",
    "launcher",
    "orchestrator",
)

# Every role that owns an app folder under ``<workspace>/apps``. The offline
# installer ships SERVER_COMPONENT_ROLES; the Gateway and the Credential helper
# are deployed straight from the repository, so they belong to the deployed set
# without being part of the installed payload. The Credential helper is run on
# demand by a client — the Excel add-in starts it when the PC has no Gateway
# credential — so, like the Launcher, it is never supervised and owns no
# instance role.
DEPLOYED_COMPONENT_ROLES = (*SERVER_COMPONENT_ROLES, "gateway", "credential")


def _configured_root() -> Path | None:
    configured_root = os.environ.get("ARCRHO_ROOT") or os.environ.get("ADAS_ROOT")
    if configured_root:
        return Path(configured_root).expanduser()
    return None


def _frozen_project_root() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None

    exe_dir = Path(sys.executable).resolve().parent
    # One-file layout: <root>\apps\<App>.exe
    if exe_dir.name.lower() == "apps":
        return exe_dir.parent

    # One-dir layout: <root>\apps\<App>\<App>.exe
    if exe_dir.parent.name.lower() == "apps":
        return exe_dir.parent.parent
    return None


def find_project_root(start_path: Path) -> Path:
    configured_root = _configured_root()
    if configured_root:
        return configured_root.resolve()

    frozen_root = _frozen_project_root()
    if frozen_root is not None:
        # The deployed layout is authoritative and supports any user-selected
        # workspace folder name.  Do not fall back to a drive/name heuristic.
        return frozen_root.resolve()

    for start in (DEFAULT_DEPLOY_ROOT, start_path):
        current = start.resolve()
        for candidate in (current, *current.parents):
            if candidate.name.lower() == PROJECT_ROOT_NAME.lower():
                return candidate
    raise RuntimeError(f'Could not find a parent folder named "{PROJECT_ROOT_NAME}" from: {start_path}')


PROJECT_ROOT = find_project_root(Path(__file__).resolve().parent)

def resolve_config_path() -> Path:
    return resolve_server_config_path(PROJECT_ROOT)


CONFIG_PATH = resolve_config_path()


def get_project_root() -> Path:
    configured_root = _configured_root()
    if configured_root:
        return configured_root.resolve()
    return PROJECT_ROOT


def component_key(role: str) -> str:
    key = COMPONENT_ALIASES.get(str(role).strip().lower())
    if key is None:
        known = ", ".join(sorted(COMPONENT_ALIASES))
        raise KeyError(f"Unknown ArcRho component role '{role}'. Known roles: {known}")
    return key


def component_dir_candidates(role: str) -> tuple[str, ...]:
    return COMPONENTS[component_key(role)]["dirs"]


def component_app_candidates(role: str) -> tuple[str, ...]:
    return COMPONENTS[component_key(role)]["apps"]


def component_app_name(role: str) -> str:
    return component_app_candidates(role)[0]


def resolve_existing_path(*paths: str | os.PathLike) -> Path:
    candidates = [Path(path) for path in paths]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def resolve_app_dir(role: str) -> Path:
    root = get_project_root()
    candidates = []
    for name in component_app_candidates(role):
        candidates.append(root / "apps" / name)
    for name in component_dir_candidates(role):
        candidates.extend(
            (
                root / "core" / name,
                root / "server-components" / "src" / name,
                root / "src" / name,
            )
        )
    return resolve_existing_path(*candidates)


def resolve_app_path(role: str, *parts: str | os.PathLike) -> Path:
    normalized_parts = tuple(str(part) for part in parts)
    if normalized_parts and normalized_parts[0].lower() == "instances":
        return get_project_root().joinpath(
            "runtime",
            "instances",
            component_dir_candidates(role)[0],
            *normalized_parts[1:],
        )
    return resolve_app_dir(role).joinpath(*parts)


def resolve_app_exe(role: str) -> Path:
    root = get_project_root()
    app_dir = resolve_app_dir(role)
    component_dir_name = component_dir_candidates(role)[0]
    app_names = component_app_candidates(role)
    candidates = [
        root / "apps" / app_name / f"{app_name}.exe"
        for app_name in app_names
    ]
    candidates.extend(
        root / "apps" / f"{app_name}.exe"
        for app_name in app_names
    )
    candidates.extend(
        root / "builds" / component_dir_name / "dist" / f"{app_name}.exe"
        for app_name in app_names
    )
    candidates.extend(
        root / "builds" / component_dir_name / "dist" / app_name / f"{app_name}.exe"
        for app_name in app_names
    )
    candidates.extend(
        app_dir / "dist" / app_name / f"{app_name}.exe"
        for app_name in app_names
    )
    return resolve_existing_path(*candidates)


FUNCTION_ALIASES = {
    "ArcRhoTri": "ADASTri",
    "ArcRhoVec": "ADASVec",
    "ArcRhoProjectSettings": "ADASProjectSettings",
    "ArcRhoHeaders": "ADASHeaders",
}

CONFIG_KEY_ALIASES = {
    "apps.engine.": "apps.agent.",
    "apps.agent.": "apps.engine.",
    "apps.orchestrator.": "apps.master.",
    "apps.master.": "apps.orchestrator.",
    "apps.bridge_worker.": "apps.rpc_bridge_worker.",
    "apps.rpc_bridge_worker.": "apps.bridge_worker.",
}


def normalize_function_name(function_name: Any) -> str:
    return FUNCTION_ALIASES.get(str(function_name), str(function_name))


def function_brand(function_name: Any) -> str:
    return "ArcRho" if str(function_name).lower().startswith("arcrho") else "ADAS"


def is_vector_function(function_name: Any) -> bool:
    return normalize_function_name(function_name) == "ADASVec"


def config_key_candidates(key_path: str) -> list[str]:
    candidates = [key_path]
    for prefix, alias_prefix in CONFIG_KEY_ALIASES.items():
        if key_path.startswith(prefix):
            candidates.append(alias_prefix + key_path[len(prefix):])
    return candidates


class File:
    """
    Get a file object, perform basic operations: open, rename, move, copy, delete, find newer/old version...
    """
    def __init__(self, path):

        self.path = path
        self.name = os.path.basename(path)

        if os.path.exists(path) is False:
            print(f'File [{self.name}] does not exist on this PC.')
            return
        
        if not os.path.isfile(self.path):
            self.is_file = False
            return
        else:
            self.is_file = True
            # print('This is a folder, not a file :(')
        
        self.location = os.path.dirname(path)
        self.user = self.get_user()
        self.owner = self.get_owner()

        self.last_modified_timestamp = os.path.getmtime(self.path)
        self.last_modified_time = datetime.fromtimestamp(self.last_modified_timestamp)
        self.creation_timestamp = os.path.getctime(self.path)
        self.creation_time = datetime.fromtimestamp(self.creation_timestamp)
        self.read_only = not os.access(self.path, os.W_OK)
        self.size_on_disk = os.path.getsize(self.path)

    def open(self):
        os.startfile(self.path)

    def rename(self, new_name):
        if os.path.exists(self.path + '\\' + new_name):
            print(f"File '{new_name}' already exists.")
            return
        os.rename(self.path, new_name)

    def get_user(self):
        import zipfile
        import xml.dom.minidom
        try:
            # Open the MS Office file to see the XML structure.
            document = zipfile.ZipFile(self.path)
            # Open/read the core.xml (contains the last user and modified date).
            uglyXML = xml.dom.minidom.parseString(document.read('docProps/core.xml')).toprettyxml(indent='  ')
            # Split lines in order to create a list.
            asText = uglyXML.splitlines()
            # loop the list in order to get the value you need. In my case last Modified By and the date.
            for item in asText:
                if 'lastModifiedBy' in item:
                    itemLength = len(item)-20
                    a_name = item[21:itemLength]
                    # print('Modified by:', item[21:itemLength])
                    info = 'Modified by:' + item[21:itemLength]

                if 'dcterms:modified' in item:
                    itemLength = len(item)-29
                    # print('Modified On:', item[46:itemLength])
            return info
        except:
            return 'unknown'

    def get_owner(self):
        import win32security
        sd = win32security.GetFileSecurity(self.path, win32security.OWNER_SECURITY_INFORMATION)
        owner_sid = sd.GetSecurityDescriptorOwner()
        owner_name, domain, _ = win32security.LookupAccountSid(None, owner_sid)
        return [owner_name, domain]

    def move_to(self, new_path, print_msg=True):
        if os.path.isdir(new_path):       
            new_path = new_path + '\\' + self.name

        if os.path.exists(new_path):
            print(f"File '{new_path}' already exists.")
            return

        if not os.path.exists(os.path.dirname(new_path)):
            os.makedirs(os.path.dirname(new_path))

        # Move the file to the destination folder
        os.rename(self.path, new_path)

        if print_msg == True:
            print(f"File moved to {new_path}")

        self.location = os.path.dirname(new_path)
        self.path = new_path

    def delete(self):
        if os.path.exists(self.path):
            # Delete the file
            os.remove(self.path)
            print(f"File '{self.path}' deleted successfully.")
        else:
            print(f"File '{self.path}' does not exist.")

    def is_read_only(self):
        file_attributes = os.stat(self.path).st_mode
        # Check if user write permission is missing
        return not (file_attributes & stat.S_IWUSR)
    
    def set_read_only(self, is_read_only=True):
        if is_read_only in [True, 1]:
            file_attributes = os.stat(self.path).st_mode
            os.chmod(self.path, file_attributes & ~stat.S_IWUSR)
        else:
            file_attributes = os.stat(self.path).st_mode
            os.chmod(self.path, file_attributes | stat.S_IWRITE)


_last_good_config: dict | None = None


def load_config() -> dict:
    # config.json is rewritten by other ArcRho apps; on Windows a concurrent
    # replace/lock makes open() raise PermissionError, and a torn read can
    # raise JSONDecodeError. Retry briefly, then fall back to the last
    # successfully loaded config rather than crashing long-running loops.
    global _last_good_config

    if not CONFIG_PATH.exists():
        return {}

    last_error: Exception | None = None
    for attempt in range(5):
        if attempt:
            time.sleep(0.1 * attempt)
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            _last_good_config = data
            return data
        except (OSError, json.JSONDecodeError) as e:
            last_error = e

    if _last_good_config is not None:
        return _last_good_config
    raise last_error


def save_config(data: dict) -> None:
    write_server_config(CONFIG_PATH, data)


def get_config_value(
    key_path: str,
    default: Any = None,
) -> Any:
    """
    key_path example:
      'shared.data_dir'
      'apps.orchestrator.max_workers'
    """
    data = load_config()

    if key_path == "root":
        return str(get_project_root())

    for candidate in config_key_candidates(key_path):
        cur = data
        for key in candidate.split("."):
            if not isinstance(cur, dict) or key not in cur:
                break
            cur = cur[key]
        else:
            return cur

    return default


def set_config_value(
    key_path: str,
    value: Any,
) -> None:
    """
    Creates missing nodes automatically.
    """
    data = load_config()

    cur = data
    keys = key_path.split(".")
    for key in keys[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]

    cur[keys[-1]] = value
    save_config(data)

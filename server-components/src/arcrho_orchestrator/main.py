import os
import sys
import time
import uuid
import json
import psutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

# Resolve packaged, deployed src layout, and repo src layout.
_MODULE_ROOT = Path(__file__).resolve().parent
_SOURCE_ROOT = _MODULE_ROOT.parent
_PRODUCT_ROOT = _SOURCE_ROOT.parent
_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", _MODULE_ROOT)).resolve()

for _path in (_PRODUCT_ROOT, _SOURCE_ROOT, _BUNDLE_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:
    from src.utils import *
except ModuleNotFoundError:
    from utils import *

os.environ.setdefault("ARCRHO_ROOT", str(get_project_root()))

engine_instance_path = str(resolve_app_path("engine", "instances"))
bridge_instance_path = str(resolve_app_path("bridge", "instances"))
orchestrator_instance_path = str(resolve_app_path("orchestrator", "instances"))
gateway_instance_path = str(resolve_app_path("gateway", "instances"))

device_name = os.environ.get("COMPUTERNAME")
session_user = os.getlogin()
ts = datetime.now().strftime("%y%m%d-%H%M%S-%f")[:-3]
orchestrator_id = f'{device_name}@' + session_user + "@" + ts

id_folder = orchestrator_instance_path
id_path = str(Path(id_folder) / f"{orchestrator_id}.json")

# A frozen component imports its runtime before it publishes a heartbeat, so on
# a cold server that gap is longer than any fixed sleep. Wait for the heartbeat
# instead of guessing, and give a stuck launch lock a ceiling well above it.
INSTANCE_REGISTRATION_TIMEOUT_SECONDS = 45
INSTANCE_POLL_SECONDS = 0.5
LAUNCH_LOCK_STALE_SECONDS = 120
HEARTBEAT_REFRESH_SECONDS = 10


def kill_extra_python_processes():
    # collect python processes
    py_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'exe', 'create_time']):
        try:
            proc_name = proc.info['name'].lower() if proc.info['name'] else ''
            if any(name.lower() in proc_name for name in ('ADAS Master.exe', 'ArcRho Master.exe', 'Arco Orchestrator.exe')):
                py_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # if only one, do nothing
    if len(py_procs) <= 1:
        return 0

    # here we kill everything
    killed = 0
    for proc in py_procs[:-1]:
        try:
            proc.terminate()
            killed += 1
        except Exception:
            pass

    return killed

def remove_old_instances(FOLDER, AGE_SECONDS=60):
    if not os.path.isdir(FOLDER):
        return

    now = time.time()

    for name in os.listdir(FOLDER):
        path = os.path.join(FOLDER, name)
        # only remove files
        if not os.path.isfile(path):
            continue
        try:
            mtime = os.path.getmtime(path)
            if now - mtime > AGE_SECONDS:
                os.remove(path)
        except Exception:
            # ignore locked / race-condition files
            pass


def file_counts(FOLDER):
    if not os.path.isdir(FOLDER):
        return 0
    file_count = sum(
        1 for name in os.listdir(FOLDER)
        if os.path.isfile(os.path.join(FOLDER, name))
        and name.lower().endswith(".json")
    )
    return file_count


def instance_file_user(name):
    """Extract the login from instance file names.

    Engine/orchestrator ids look like ``MACHINE@user@ts`` and bridge/worker ids
    like ``role@MACHINE@user@ts``; the user is the second-to-last token in both.
    """

    parts = Path(name).stem.split("@")
    return parts[-2] if len(parts) >= 3 else ""


def user_file_counts(FOLDER, user):
    if not os.path.isdir(FOLDER):
        return 0
    normalized = str(user).casefold()
    return sum(
        1 for name in os.listdir(FOLDER)
        if os.path.isfile(os.path.join(FOLDER, name))
        and name.lower().endswith(".json")
        and instance_file_user(name).casefold() == normalized
    )


def limit_user_instance_files(FOLDER, user, max_count):
    """Keep the newest max_count instance files owned by one user.

    Other users' instance files are never touched: on a shared PC each user
    session runs its own bridge, and deleting a fresh heartbeat kills it.
    """

    if not os.path.isdir(FOLDER):
        return
    normalized = str(user).casefold()
    paths = []
    for name in os.listdir(FOLDER):
        path = os.path.join(FOLDER, name)
        if not (os.path.isfile(path) and name.lower().endswith(".json")):
            continue
        if instance_file_user(name).casefold() != normalized:
            continue
        try:
            paths.append((os.path.getmtime(path), path))
        except OSError:
            pass

    paths.sort(reverse=True)
    for _, path in paths[max_count:]:
        try:
            safe_remove(path)
        except OSError:
            pass


def launch_lock_path(name: str):
    return get_project_root() / "runtime" / "locks" / f"{name}_launch.lock"


def clear_stale_launch_lock(path):
    """Release a lock an Orchestrator died holding."""

    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return
    if age > LAUNCH_LOCK_STALE_SECONDS:
        safe_remove(str(path))


@contextmanager
def launch_slot(name: str):
    """Serialize launches of a component whose cap is machine-wide.

    Every signed-in user runs an Orchestrator, and each one compared the live
    instance count against the cap on its own. Several read the same deficit in
    the same second and each launched to fill it, so a five-worker cap produced
    eight or nine Engines. Only the holder of this lock may launch, and it
    holds it until the new instance registers, so the next Orchestrator decides
    against a current count. Acquisition never blocks: an Orchestrator that
    loses simply retries on its next pass.
    """

    path = launch_lock_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    clear_stale_launch_lock(path)
    try:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    except OSError:
        # A workspace that cannot hold the lock must not silently lose the cap.
        yield False
        return

    try:
        os.write(handle, json.dumps({'Server': orchestrator_id}).encode('utf-8'))
    finally:
        os.close(handle)
    try:
        yield True
    finally:
        safe_remove(str(path))


def touch_heartbeat():
    """Refresh this Orchestrator's own heartbeat during a long wait.

    Waiting for cold components to register can outlast the staleness window
    another Orchestrator reaps by, and losing the file makes this process exit.
    """

    try:
        payload = read_json(id_path)
    except OSError:
        return
    payload['Last seen'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        write_json(id_path, payload)
    except OSError:
        pass


def wait_for_new_instance(count_instances, baseline):
    """Wait for a launched app to publish its heartbeat.

    Returning as soon as the count rises keeps the cap comparison honest; the
    previous fixed sleep relaunched into the startup gap whenever a cold frozen
    component took longer than it to register.
    """

    deadline = time.monotonic() + INSTANCE_REGISTRATION_TIMEOUT_SECONDS
    next_refresh = time.monotonic() + HEARTBEAT_REFRESH_SECONDS
    while time.monotonic() < deadline:
        if count_instances() > baseline:
            return True
        if not os.path.exists(id_path):
            return False
        if time.monotonic() >= next_refresh:
            touch_heartbeat()
            next_refresh = time.monotonic() + HEARTBEAT_REFRESH_SECONDS
        time.sleep(INSTANCE_POLL_SECONDS)
    return count_instances() > baseline


def replenish_instances(role: str, lock_name: str, count_instances, target: int):
    """Launch one capped app at a time, while each one registers, up to target.

    A launch that does not register within the timeout ends the pass. Launching
    the rest of the deficit on top of it helps in neither failure mode: a
    component crashing on startup would just leave more dead processes behind
    and delay the pass by another timeout each, and one merely slower than the
    timeout would be joined by copies that all register later and overshoot the
    very cap this serialization exists to hold. The next pass refills whatever
    is still missing against a current count.
    """

    for _ in range(max(0, int(target))):
        if count_instances() >= target:
            return
        with launch_slot(lock_name) as acquired:
            if not acquired:
                return
            baseline = count_instances()
            if baseline >= target:
                return
            if not launch_app(role):
                return
            if not wait_for_new_instance(count_instances, baseline):
                return


def launch_app(role: str):
    exe = resolve_app_exe(role)
    if not exe.exists():
        return False
    # Give each app its own folder as working directory so a long-running
    # child never keeps this process's folder locked against a redeploy.
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
    return True


def read_json(json_file, retries=50, delay=0.02):
    for _ in range(retries):
        try:
            with open(json_file, mode='r', encoding='utf-8') as f:
                return json.load(f)
        except (PermissionError, json.JSONDecodeError):
            time.sleep(delay)
    raise PermissionError(f"Cannot open {json_file}")


def write_json(json_file, arg):
    os.makedirs(os.path.dirname(json_file), exist_ok=True)
    tmp_file = f"{json_file}.{uuid.uuid4()}.tmp"
    with open(tmp_file, mode="w", encoding="utf-8") as file:
        json.dump(arg, file, indent=2)
        file.write("\n")
    os.replace(tmp_file, json_file)


def safe_remove(file_path, attempts=5, delay=0.1):
    """Attempt to remove a file with retries on permission error."""
    for _ in range(attempts):
        try:
            tmp = f"{file_path}.{uuid.uuid4()}.deleting"
            os.replace(file_path, tmp)  # atomic
            os.remove(tmp)
            return True
        except PermissionError:
            time.sleep(delay)

    return False


def main():
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_json(id_path, {'Server': orchestrator_id, 'Last seen': current_time})

    time.sleep(1)

    while True:
        try:
            if not os.path.exists(id_path):
                break

            if get_config_value('apps.orchestrator.kill_all'):
                safe_remove(id_path)
                break

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Update Status
            arg_1 = read_json(id_path)
            arg_1['Last seen'] = current_time
            write_json(id_path, arg_1)

            remove_old_instances(engine_instance_path)
            remove_old_instances(bridge_instance_path)
            remove_old_instances(orchestrator_instance_path)
            remove_old_instances(gateway_instance_path, 30)
            remove_old_instances(str(get_project_root() / "requests"), 5*60)

            if get_config_value('apps.orchestrator.auto_create_workers') \
              and get_config_value('apps.engine.kill_all') == False:
                replenish_instances(
                    "engine",
                    "engine",
                    lambda: file_counts(engine_instance_path),
                    int(get_config_value('apps.orchestrator.max_workers')),
                )

            # Bridges are per user session: every ResQ user contributes one
            # bridge running on their own ResQ GUI/license, so the cap counts
            # only this session's user and never trims other users' bridges.
            bridge_max_instances = max(0, min(int(get_config_value('apps.bridge.max_instances', 1)), 1))
            limit_user_instance_files(bridge_instance_path, session_user, bridge_max_instances)
            if get_config_value('apps.bridge.auto_create_instance', True) \
              and get_config_value('apps.bridge.kill_all', False) == False:
                replenish_instances(
                    "bridge",
                    f"bridge@{session_user}",
                    lambda: user_file_counts(bridge_instance_path, session_user),
                    bridge_max_instances,
                )

            # The Gateway is machine-wide rather than per session. Every
            # logged-in user's orchestrator may race to restore it, but only
            # one process can bind the configured port and publish a heartbeat.
            gateway_max_instances = max(
                0,
                min(int(get_config_value('apps.gateway.max_instances', 1)), 1),
            )
            if get_config_value('apps.gateway.auto_create_instance', True) \
              and get_config_value('apps.gateway.kill_all', False) == False:
                replenish_instances(
                    "gateway",
                    "gateway",
                    lambda: file_counts(gateway_instance_path),
                    gateway_max_instances,
                )

        except Exception as e:
            print(e)

        time.sleep(15)


if __name__ == "__main__":
    main()

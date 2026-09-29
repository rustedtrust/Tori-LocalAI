"""Small, bounded host capabilities exposed through Tori Conversation."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import ipaddress
import math
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import struct
import subprocess
import time
from typing import Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class SystemCapabilityError(RuntimeError):
    """A safe, user-facing system capability failure."""

    def __init__(self, message: str, *, code: str = "system_capability_error") -> None:
        super().__init__(message)
        self.code = code


class SystemCapabilityUnavailable(SystemCapabilityError):
    """A bounded capability is not available on this host."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="system_capability_unavailable")


@dataclass(frozen=True, slots=True)
class DiskUsage:
    path: str
    free_bytes: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class NetworkAddresses:
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryStatus:
    total_bytes: int
    used_bytes: int
    available_bytes: int
    used_percent: float


@dataclass(frozen=True, slots=True)
class CPUStatus:
    model: str | None
    logical_cpus: int | None
    utilization_percent: float | None
    load_average: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class GPUInfo:
    name: str
    memory_total_bytes: int | None
    memory_used_bytes: int | None
    memory_free_bytes: int | None
    utilization_percent: float | None
    temperature_celsius: float | None


@dataclass(frozen=True, slots=True)
class GPUStatus:
    gpus: tuple[GPUInfo, ...]


@dataclass(frozen=True, slots=True)
class UptimeStatus:
    uptime_seconds: float
    boot_time_epoch: float | None = None


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    service: str
    running: bool
    reachable: bool


@dataclass(frozen=True, slots=True)
class HealthSignal:
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class ToriHealth:
    signals: tuple[HealthSignal, ...]


@dataclass(frozen=True, slots=True)
class ServiceActionProposal:
    """An exact, allowlisted service mutation awaiting confirmation."""

    service: str
    action: str
    display_name: str
    unit: str
    scope: str


@dataclass(frozen=True, slots=True)
class ServiceActionResult:
    """The bounded result of one confirmed service action."""

    proposal: ServiceActionProposal
    succeeded: bool
    verified: bool
    text: str


@dataclass(frozen=True, slots=True)
class SystemRequest:
    operation: str
    path: str = "/"
    application: str | None = None
    service: str | None = None
    action: str | None = None


@dataclass(frozen=True, slots=True)
class SystemTurn:
    request: SystemRequest
    text: str
    code: str = "completed"
    proposal: ServiceActionProposal | None = None

    @property
    def succeeded(self) -> bool:
        return self.code == "completed"


def _discover_interface_ipv4_addresses() -> tuple[str, ...]:
    """Read local IPv4 assignments without contacting a remote service."""

    if os.name != "posix":
        return ()
    try:
        import fcntl

        request_code = 0x8915  # Linux SIOCGIFADDR; harmlessly unavailable elsewhere.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            addresses: set[str] = set()
            for _index, interface in socket.if_nameindex():
                request = struct.pack("256sH14s", interface.encode(), socket.AF_INET, b"")
                try:
                    result = fcntl.ioctl(probe.fileno(), request_code, request)
                except OSError:
                    continue
                addresses.add(socket.inet_ntoa(result[20:24]))
            return tuple(sorted(addresses))
    except (AttributeError, ImportError, OSError, struct.error, UnicodeError):
        return ()


def _format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    amount = float(max(0, value))
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{int(value)} B"


def _display_path(path: str) -> str:
    return "the main filesystem" if path == "/" else path


def _read_memory_status() -> MemoryStatus:
    """Read normalized memory totals from Linux's native memory counters."""

    counters: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            fields = value.strip().split()
            if not fields:
                continue
            try:
                counters[key] = int(fields[0]) * 1024
            except ValueError:
                continue
    except (OSError, UnicodeError):
        counters = {}
    total = counters.get("MemTotal", 0)
    available = counters.get("MemAvailable", counters.get("MemFree", 0))
    if total <= 0 or available < 0 or available > total:
        raise SystemCapabilityUnavailable("Memory status is unavailable on this host.")
    used = total - available
    return MemoryStatus(total, used, available, used / total * 100)


def _read_cpu_times() -> tuple[int, int]:
    line = next(
        (
            line for line in Path("/proc/stat").read_text(encoding="ascii").splitlines()
            if line.startswith("cpu ")
        ),
        "",
    )
    fields = line.split()[1:]
    if len(fields) < 4:
        raise SystemCapabilityUnavailable("CPU utilization is unavailable on this host.")
    try:
        values = [int(value) for value in fields]
    except ValueError as exc:
        raise SystemCapabilityUnavailable(
            "CPU utilization is unavailable on this host."
        ) from exc
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def _sample_cpu_utilization() -> float:
    try:
        first_total, first_idle = _read_cpu_times()
        time.sleep(0.1)
        second_total, second_idle = _read_cpu_times()
    except (OSError, UnicodeError):
        raise SystemCapabilityUnavailable(
            "CPU utilization is unavailable on this host."
        ) from None
    total_delta = second_total - first_total
    busy_delta = total_delta - (second_idle - first_idle)
    if total_delta <= 0 or busy_delta < 0:
        raise SystemCapabilityUnavailable("CPU utilization is unavailable on this host.")
    return min(100.0, max(0.0, busy_delta / total_delta * 100))


def _read_cpu_status() -> CPUStatus:
    model: str | None = None
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="ascii").splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip().casefold() in {"model name", "hardware"}:
                model = value.strip() or None
                if model is not None:
                    break
    except (OSError, UnicodeError):
        pass
    logical = os.cpu_count()
    try:
        load_average = tuple(float(value) for value in os.getloadavg())
    except (AttributeError, OSError):
        load_average = ()
    try:
        utilization = _sample_cpu_utilization()
    except SystemCapabilityError:
        utilization = None
    return CPUStatus(model, logical, utilization, load_average)


def _read_uptime_status() -> UptimeStatus:
    try:
        raw = Path("/proc/uptime").read_text(encoding="ascii").split()[0]
        seconds = float(raw)
    except (IndexError, OSError, UnicodeError, ValueError) as exc:
        raise SystemCapabilityUnavailable("Uptime is unavailable on this host.") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise SystemCapabilityUnavailable("Uptime is unavailable on this host.")
    return UptimeStatus(seconds, time.time() - seconds)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_LOCAL_OPENER = build_opener(ProxyHandler({}), _RejectRedirects())
_NVIDIA_SMI_PATHS = (
    "/usr/bin/nvidia-smi",
    "/usr/local/bin/nvidia-smi",
    "/opt/cuda/bin/nvidia-smi",
)
_NVIDIA_SMI_ARGUMENTS = (
    "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
    "--format=csv,noheader,nounits",
)
_SYSTEMCTL_PATHS = ("/usr/bin/systemctl", "/bin/systemctl")
_SUDO_PATHS = ("/usr/bin/sudo", "/bin/sudo")
_OLLAMA_SERVICE_HELPER_PATH = "/usr/local/libexec/tori-ollama-service"
_SERVICE_ACTIONS = frozenset({"start", "stop", "restart"})
_SERVICE_TARGETS = {
    "ollama": ("Ollama", "ollama.service", "system"),
    "radicale": ("Radicale", "tori-radicale.service", "user"),
}


def _trusted_systemctl_path() -> str | None:
    for candidate in _SYSTEMCTL_PATHS:
        path = Path(candidate)
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return candidate
        except OSError:
            continue
    return None


def _trusted_sudo_path() -> str | None:
    for candidate in _SUDO_PATHS:
        path = Path(candidate)
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return candidate
        except OSError:
            continue
    return None


def _trusted_ollama_service_helper_path() -> str | None:
    """Return only a root-owned, non-user-writable installed Ollama helper."""

    path = Path(_OLLAMA_SERVICE_HELPER_PATH)
    try:
        parent_metadata = path.parent.lstat()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != 0
            or parent_metadata.st_gid != 0
            or stat.S_IMODE(parent_metadata.st_mode) & 0o022
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or mode & 0o022
            or not os.access(path, os.X_OK)
        ):
            return None
    except OSError:
        return None
    return _OLLAMA_SERVICE_HELPER_PATH


def _trusted_nvidia_smi_path() -> str | None:
    for candidate in _NVIDIA_SMI_PATHS:
        path = Path(candidate)
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return candidate
        except OSError:
            continue
    return None


def _nvidia_smi_output(
    *,
    path_function: Callable[[], str | None],
    runner: Callable[..., object],
) -> str:
    executable = path_function()
    if executable is None:
        raise SystemCapabilityUnavailable("GPU status is unavailable on this host.")
    try:
        completed = runner(
            [executable, *_NVIDIA_SMI_ARGUMENTS],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            timeout=2,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        raise SystemCapabilityUnavailable("GPU status is unavailable on this host.") from exc
    if getattr(completed, "returncode", 1) != 0:
        raise SystemCapabilityUnavailable("GPU status is unavailable on this host.")
    output = getattr(completed, "stdout", "")
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    if not isinstance(output, str):
        raise SystemCapabilityUnavailable("GPU status is unavailable on this host.")
    return output


def _parse_gpu_number(raw: str, *, scale: float = 1.0) -> float | None:
    value = raw.strip()
    if not value or value.casefold() in {"n/a", "na", "[n/a]"}:
        return None
    try:
        number = float(value) * scale
    except ValueError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _read_gpu_status(
    *,
    path_function: Callable[[], str | None],
    runner: Callable[..., object],
) -> GPUStatus:
    rows = csv.reader(_nvidia_smi_output(path_function=path_function, runner=runner).splitlines())
    gpus: list[GPUInfo] = []
    for row in rows:
        if len(row) != 6:
            continue
        name = row[0].strip()
        if not name:
            continue
        total = _parse_gpu_number(row[1], scale=1024 * 1024)
        used = _parse_gpu_number(row[2], scale=1024 * 1024)
        free = _parse_gpu_number(row[3], scale=1024 * 1024)
        if free is None and total is not None and used is not None and used <= total:
            free = total - used
        utilization = _parse_gpu_number(row[4])
        temperature = _parse_gpu_number(row[5])
        if utilization is not None:
            utilization = min(100.0, utilization)
        gpus.append(GPUInfo(name, total, used, free, utilization, temperature))
    if not gpus:
        raise SystemCapabilityUnavailable("GPU status is unavailable on this host.")
    return GPUStatus(tuple(gpus))


def _probe_loopback_endpoint(url: str, *, ollama: bool) -> bool:
    try:
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        with _LOCAL_OPENER.open(request, timeout=1.5) as response:
            status = int(getattr(response, "status", response.getcode()))
            return status < 300 if ollama else status < 500
    except HTTPError as exc:
        return (exc.code < 300) if ollama else (exc.code < 500)
    except (OSError, URLError, TimeoutError, ValueError):
        return False


def _default_ollama_status() -> bool:
    return _probe_loopback_endpoint("http://127.0.0.1:11434/api/tags", ollama=True)


def _default_radicale_status() -> bool:
    return _probe_loopback_endpoint("http://127.0.0.1:5232/", ollama=False)


def _format_duration(seconds: float) -> str:
    remaining = max(0, int(seconds))
    days, remaining = divmod(remaining, 86400)
    hours, remaining = divmod(remaining, 3600)
    minutes, _seconds = divmod(remaining, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} day" + ("s" if days != 1 else ""))
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes and len(parts) < 2:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    return ", ".join(parts) if parts else "less than a minute"


class SystemCapabilities:
    """Native implementations for a deliberately tiny allowlisted surface."""

    _BRAVE_NAMES = ("brave-browser", "brave")
    _BRAVE_PATHS = (
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
        "/opt/brave.com/brave/brave-browser",
        "/opt/brave.com/brave/brave",
        "/snap/bin/brave",
        "/var/lib/flatpak/exports/bin/com.brave.Browser",
    )
    _DESKTOP_NAMES = {
        "dolphin": ("dolphin",),
        "terminal": ("x-terminal-emulator",),
        "lm_studio": ("lm-studio",),
    }
    _DESKTOP_PATHS = {
        "dolphin": ("/usr/bin/dolphin",),
        "terminal": (
            "/usr/bin/x-terminal-emulator",
            "/usr/bin/xfce4-terminal",
            "/usr/bin/konsole",
        ),
        "lm_studio": ("/usr/bin/lm-studio",),
    }
    _DESKTOP_LABELS = {
        "brave": "Brave",
        "dolphin": "Dolphin",
        "terminal": "a terminal",
        "lm_studio": "LM Studio",
    }

    def __init__(
        self,
        *,
        disk_usage_function: Callable[[str], object] = shutil.disk_usage,
        address_function: Callable[..., list[tuple[object, ...]]] = socket.getaddrinfo,
        hostname_function: Callable[[], str] = socket.gethostname,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        process_launcher: Callable[..., object] = subprocess.Popen,
        interface_address_function: Callable[[], Sequence[str]] = _discover_interface_ipv4_addresses,
        brave_fallback_resolver: Callable[[], str | None] | None = None,
        memory_status_function: Callable[[], MemoryStatus] = _read_memory_status,
        cpu_status_function: Callable[[], CPUStatus] = _read_cpu_status,
        gpu_status_function: Callable[[], GPUStatus] | None = None,
        nvidia_smi_path_function: Callable[[], str | None] = _trusted_nvidia_smi_path,
        nvidia_smi_runner: Callable[..., object] = subprocess.run,
        uptime_function: Callable[[], UptimeStatus] = _read_uptime_status,
        ollama_status_function: Callable[[], bool] = _default_ollama_status,
        radicale_status_function: Callable[[], bool] = _default_radicale_status,
        planning_status_function: Callable[[], object] | None = None,
        tori_health_function: Callable[[], ToriHealth] | None = None,
        systemctl_path_function: Callable[[], str | None] = _trusted_systemctl_path,
        systemctl_runner: Callable[..., object] = subprocess.run,
        sudo_path_function: Callable[[], str | None] = _trusted_sudo_path,
        ollama_service_helper_path_function: Callable[[], str | None] = _trusted_ollama_service_helper_path,
        ollama_service_runner: Callable[..., object] = subprocess.run,
        action_sleep_function: Callable[[float], None] = time.sleep,
    ) -> None:
        self._disk_usage = disk_usage_function
        self._address_function = address_function
        self._hostname = hostname_function
        self._resolve_executable = executable_resolver
        self._launch = process_launcher
        self._interface_addresses = interface_address_function
        self._use_interface_addresses = address_function is socket.getaddrinfo
        self._resolve_brave_fallback = brave_fallback_resolver or (
            lambda: next(
                (
                    path for path in self._BRAVE_PATHS
                    if Path(path).is_file() and os.access(path, os.X_OK)
                ),
                None,
            )
        )
        self._memory_status = memory_status_function
        self._cpu_status = cpu_status_function
        self._gpu_status = gpu_status_function or (
            lambda: _read_gpu_status(
                path_function=nvidia_smi_path_function,
                runner=nvidia_smi_runner,
            )
        )
        self._uptime = uptime_function
        self._ollama_status = ollama_status_function
        self._radicale_status = radicale_status_function
        self._planning_status = planning_status_function
        self._tori_health = tori_health_function
        self._systemctl_path = systemctl_path_function
        self._systemctl_runner = systemctl_runner
        self._sudo_path = sudo_path_function
        self._ollama_service_helper_path = ollama_service_helper_path_function
        self._ollama_service_runner = ollama_service_runner
        self._action_sleep = action_sleep_function

    def disk_usage(self, path: str = "/") -> DiskUsage:
        if not isinstance(path, str) or not path or "\x00" in path:
            raise SystemCapabilityError("That filesystem path is not valid.", code="invalid_path")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            raise SystemCapabilityError(
                "Disk usage requires an absolute existing filesystem path.",
                code="invalid_path",
            )
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.exists():
                raise FileNotFoundError(path)
            usage = self._disk_usage(str(resolved))
            total = int(getattr(usage, "total"))
            free = int(getattr(usage, "free"))
        except (OSError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            raise SystemCapabilityError(
                f"I couldn't read disk usage for {path}.", code="disk_usage_failed"
            ) from exc
        if total < 0 or free < 0 or free > total:
            raise SystemCapabilityError("The filesystem reported invalid disk usage.", code="disk_usage_failed")
        return DiskUsage(str(resolved), free, total)

    def network_addresses(self) -> NetworkAddresses:
        try:
            records = self._address_function(
                self._hostname(),
                None,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError):
            return NetworkAddresses(())
        candidates: set[ipaddress.IPv4Address] = set()
        for record in records:
            try:
                raw = record[4][0]
                address = ipaddress.ip_address(raw)
            except (IndexError, TypeError, ValueError):
                continue
            if (
                isinstance(address, ipaddress.IPv4Address)
                and not address.is_loopback
                and not address.is_unspecified
                and not address.is_multicast
                and not address.is_reserved
                and (address.is_private or address.is_link_local)
            ):
                candidates.add(address)
        if self._use_interface_addresses:
            for raw in self._interface_addresses():
                try:
                    address = ipaddress.ip_address(raw)
                except (TypeError, ValueError):
                    continue
                if (
                    isinstance(address, ipaddress.IPv4Address)
                    and not address.is_loopback
                    and not address.is_unspecified
                    and not address.is_multicast
                    and not address.is_reserved
                    and (address.is_private or address.is_link_local)
                ):
                    candidates.add(address)
        return NetworkAddresses(tuple(str(address) for address in sorted(candidates, key=int)))

    def open_application(self, application: str) -> str:
        if application == "brave":
            executable = None
            for name in self._BRAVE_NAMES:
                executable = self._resolve_executable(name)
                if executable:
                    break
            if not executable:
                executable = self._resolve_brave_fallback()
            if not isinstance(executable, str) or not executable:
                raise SystemCapabilityUnavailable("Brave is not installed or available on this desktop.")
            self._launch_desktop([executable], "Brave")
            return executable
        if application not in self._DESKTOP_NAMES:
            raise SystemCapabilityError("That desktop application is not supported.", code="unknown_application")
        executable = self._resolve_desktop_executable(application)
        if executable is None:
            label = self._DESKTOP_LABELS[application].capitalize()
            raise SystemCapabilityUnavailable(
                f"{label} is not installed or available on this desktop."
            )
        self._launch_desktop([executable], self._DESKTOP_LABELS[application])
        return executable

    def open_folder(self, path: str) -> str:
        if not isinstance(path, str) or not path or "\x00" in path:
            raise SystemCapabilityError("That directory path is not valid.", code="invalid_directory")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            raise SystemCapabilityError(
                "Folder opening requires an absolute existing directory.",
                code="invalid_directory",
            )
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SystemCapabilityError(
                "That directory was not found.", code="directory_not_found"
            ) from exc
        if not resolved.is_dir():
            raise SystemCapabilityError(
                "That path is not an existing directory.", code="invalid_directory"
            )
        executable = self._resolve_desktop_executable("dolphin")
        if executable is None:
            raise SystemCapabilityUnavailable(
                "Dolphin is not installed or available on this desktop."
            )
        self._launch_desktop([executable, str(resolved)], "Dolphin")
        return str(resolved)

    def service_action_proposal(self, service: str, action: str) -> ServiceActionProposal:
        target = _SERVICE_TARGETS.get(service)
        if target is None:
            raise SystemCapabilityError(
                "That service is not supported for actions.", code="unknown_service"
            )
        if action not in _SERVICE_ACTIONS:
            raise SystemCapabilityError(
                "That service action is not supported.", code="unknown_service_action"
            )
        display_name, unit, scope = target
        return ServiceActionProposal(service, action, display_name, unit, scope)

    def execute_service_action(self, proposal: ServiceActionProposal) -> ServiceActionResult:
        expected = self.service_action_proposal(proposal.service, proposal.action)
        if proposal != expected:
            raise SystemCapabilityError(
                "That service action is not supported.", code="invalid_service_action"
            )
        if proposal.service == "ollama":
            sudo = self._sudo_path()
            helper = self._ollama_service_helper_path()
            if sudo is None or helper is None:
                return ServiceActionResult(
                    proposal, False, False,
                    "Ollama service control is unavailable on this host.",
                )
            argv = [sudo, "-n", helper, proposal.action]
            runner = self._ollama_service_runner
        else:
            executable = self._systemctl_path()
            if executable is None:
                return ServiceActionResult(
                    proposal, False, False,
                    f"{proposal.display_name} could not be changed because service control is unavailable.",
                )
            argv = [executable]
            if proposal.scope == "user":
                argv.append("--user")
            argv.extend((proposal.action, proposal.unit))
            runner = self._systemctl_runner
        try:
            completed = runner(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, TimeoutError):
            return ServiceActionResult(
                proposal, False, False,
                f"{proposal.display_name} could not be {self._past_tense(proposal.action)}.",
            )
        if getattr(completed, "returncode", 1) != 0:
            return ServiceActionResult(
                proposal, False, False,
                f"{proposal.display_name} could not be {self._past_tense(proposal.action)}.",
            )
        expected_running = proposal.action != "stop"
        verified = self._wait_for_service_state(proposal.service, expected_running)
        if not verified:
            return ServiceActionResult(
                proposal, False, False,
                f"{proposal.display_name} was changed, but its expected state could not be verified.",
            )
        if proposal.service == "radicale" and expected_running:
            text = f"Radicale {self._past_tense(proposal.action)} successfully and Planning is reachable."
        elif proposal.service == "ollama" and expected_running:
            text = f"Ollama {self._past_tense(proposal.action)} successfully and its local endpoint is reachable."
        else:
            text = f"{proposal.display_name} {self._past_tense(proposal.action)} successfully."
        return ServiceActionResult(proposal, True, True, text)

    def _resolve_desktop_executable(self, application: str) -> str | None:
        for name in self._DESKTOP_NAMES[application]:
            executable = self._resolve_executable(name)
            if not isinstance(executable, str) or not executable:
                continue
            try:
                if str(Path(executable).resolve()) in {
                    str(Path(path).resolve()) for path in self._DESKTOP_PATHS[application]
                }:
                    return executable
            except (OSError, RuntimeError):
                continue
        for path in self._DESKTOP_PATHS[application]:
            candidate = Path(path)
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return path
            except OSError:
                continue
        return None

    def _launch_desktop(self, argv: list[str], label: str) -> None:
        try:
            self._launch(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise SystemCapabilityError(
                f"{label} could not be launched.", code="launch_failed"
            ) from exc

    def _wait_for_service_state(self, service: str, expected_running: bool) -> bool:
        for attempt in range(12):
            try:
                if self.service_status(service).running == expected_running:
                    return True
            except Exception:
                return False
            if attempt < 11:
                self._action_sleep(0.25)
        return False

    @staticmethod
    def _past_tense(action: str) -> str:
        return {"start": "started", "stop": "stopped", "restart": "restarted"}[action]

    def memory_status(self) -> MemoryStatus:
        status = self._memory_status()
        if status.total_bytes <= 0 or status.used_bytes < 0 or status.available_bytes < 0:
            raise SystemCapabilityUnavailable("Memory status is unavailable on this host.")
        return status

    def cpu_status(self) -> CPUStatus:
        status = self._cpu_status()
        if status.logical_cpus is not None and status.logical_cpus <= 0:
            raise SystemCapabilityUnavailable("CPU status is unavailable on this host.")
        return status

    def gpu_status(self) -> GPUStatus:
        return self._gpu_status()

    def uptime(self) -> UptimeStatus:
        status = self._uptime()
        if not math.isfinite(status.uptime_seconds) or status.uptime_seconds < 0:
            raise SystemCapabilityUnavailable("Uptime is unavailable on this host.")
        return status

    def service_status(self, service: str) -> ServiceStatus:
        if service not in {"ollama", "radicale"}:
            raise SystemCapabilityError(
                "That service is not supported for status checks.",
                code="unknown_service",
            )
        if service == "ollama":
            running = bool(self._ollama_status())
            return ServiceStatus(service, running, running)
        if self._planning_status is not None:
            try:
                planning = self._planning_status()
                availability = getattr(planning, "availability", None)
                value = getattr(availability, "value", availability)
                running = value == "available"
            except Exception:
                running = False
        else:
            running = bool(self._radicale_status())
        return ServiceStatus(service, running, running)

    def tori_health(self) -> ToriHealth:
        if self._tori_health is None:
            return ToriHealth((HealthSignal("Tori", "available"),))
        health = self._tori_health()
        if not isinstance(health, ToriHealth):
            raise SystemCapabilityUnavailable("Tori health is unavailable.")
        return health


class SystemConversationService:
    """Recognize only clear system requests and execute them without model authority."""

    def __init__(self, capabilities: SystemCapabilities | None = None) -> None:
        self._capabilities = capabilities or SystemCapabilities()

    def interpret(self, text: str) -> SystemRequest | None:
        normalized = " ".join(text.strip().split()).replace("’", "'")
        if normalized.casefold().startswith("tori,"):
            normalized = normalized[5:].strip()
        lowered = normalized.casefold()
        if _is_disk_request(lowered):
            path = _extract_absolute_path(normalized) or "/"
            return SystemRequest("disk_usage", path=path)
        if _is_network_request(lowered):
            return SystemRequest("network_addresses")
        if _is_brave_request(lowered):
            return SystemRequest("open_application", application="brave")
        application = _desktop_application_request(lowered)
        if application is not None:
            return SystemRequest("open_application", application=application)
        folder = _folder_request(normalized, lowered)
        if folder is not None:
            return SystemRequest("open_folder", path=folder)
        service_action = _is_service_action_request(lowered)
        if service_action is not None:
            action, service = service_action
            return SystemRequest("system.service_action", service=service, action=action)
        if _is_memory_request(lowered):
            return SystemRequest("system.memory_status")
        if _is_cpu_request(lowered):
            return SystemRequest("system.cpu_status")
        if _is_gpu_request(lowered):
            return SystemRequest("system.gpu_status")
        if _is_uptime_request(lowered):
            return SystemRequest("system.uptime")
        if _is_ollama_request(lowered):
            return SystemRequest("system.service_status", service="ollama")
        if _is_radicale_request(lowered):
            return SystemRequest("system.service_status", service="radicale")
        if _is_tori_health_request(lowered):
            return SystemRequest("system.health_status")
        return None

    def host_status(self) -> dict[str, object]:
        """Return bounded, read-only telemetry for the local UI.

        Each metric is independently optional: an unavailable GPU must never
        make CPU/RAM status, conversation, or browser polling fail.
        """

        document: dict[str, object] = {
            "cpu": {"available": False},
            "memory": {"available": False},
            "gpus": [],
        }
        try:
            cpu = self._capabilities.cpu_status()
            document["cpu"] = {
                "available": cpu.utilization_percent is not None,
                "utilization_percent": cpu.utilization_percent,
            }
        except SystemCapabilityError:
            pass
        except Exception:
            pass
        try:
            memory = self._capabilities.memory_status()
            document["memory"] = {
                "available": True,
                "used_bytes": memory.used_bytes,
                "total_bytes": memory.total_bytes,
                "used_percent": memory.used_percent,
            }
        except SystemCapabilityError:
            pass
        except Exception:
            pass
        try:
            gpu_status = self._capabilities.gpu_status()
            document["gpus"] = [
                {
                    "name": gpu.name,
                    "utilization_percent": gpu.utilization_percent,
                    "memory_used_bytes": gpu.memory_used_bytes,
                    "memory_total_bytes": gpu.memory_total_bytes,
                }
                for gpu in gpu_status.gpus
            ]
        except SystemCapabilityError:
            pass
        except Exception:
            pass
        return document

    def execute(self, request: SystemRequest) -> SystemTurn:
        if request.operation == "disk_usage":
            usage = self._capabilities.disk_usage(request.path)
            used = usage.total_bytes - usage.free_bytes
            percent = (used / usage.total_bytes * 100) if usage.total_bytes else 0
            text = (
                f"You have {_format_bytes(usage.free_bytes)} free out of "
                f"{_format_bytes(usage.total_bytes)} on {_display_path(request.path)} "
                f"({percent:.0f}% used)."
            )
        elif request.operation == "network_addresses":
            addresses = self._capabilities.network_addresses().addresses
            text = (
                f"Your LAN IP is {addresses[0]}."
                if len(addresses) == 1
                else f"Your LAN IPs are {', '.join(addresses)}."
                if addresses
                else "I couldn't determine a non-loopback LAN IP address."
            )
        elif request.operation == "open_application":
            self._capabilities.open_application(request.application or "")
            text = f"Opening {_application_label(request.application or '')}."
        elif request.operation == "open_folder":
            opened = self._capabilities.open_folder(request.path)
            text = f"Opening {opened} in Dolphin."
        elif request.operation == "system.service_action":
            raise SystemCapabilityError(
                "Service actions require explicit confirmation.",
                code="confirmation_required",
            )
        elif request.operation == "system.memory_status":
            status = self._capabilities.memory_status()
            text = (
                f"You're using {_format_bytes(status.used_bytes)} of "
                f"{_format_bytes(status.total_bytes)} RAM, with "
                f"{_format_bytes(status.available_bytes)} available "
                f"({status.used_percent:.0f}% used)."
            )
        elif request.operation == "system.cpu_status":
            status = self._capabilities.cpu_status()
            sentences: list[str] = []
            if status.model:
                processor = f"Your processor is {status.model}"
                if status.logical_cpus is not None:
                    processor += f" with {status.logical_cpus} logical CPUs"
                sentences.append(processor)
            if status.logical_cpus is not None:
                if not status.model:
                    sentences.append(f"You have {status.logical_cpus} logical CPUs")
            if status.utilization_percent is not None:
                sentences.append(
                    f"CPU utilization is around {status.utilization_percent:.0f}% right now"
                )
            if status.load_average:
                sentences.append(f"System load is {status.load_average[0]:.2f}")
            text = ". ".join(sentences) + ("." if sentences else "CPU status is unavailable.")
        elif request.operation == "system.gpu_status":
            status = self._capabilities.gpu_status()
            text = " ".join(_format_gpu(gpu, index, len(status.gpus)) for index, gpu in enumerate(status.gpus))
        elif request.operation == "system.uptime":
            status = self._capabilities.uptime()
            text = f"Your computer has been running for {_format_duration(status.uptime_seconds)}."
        elif request.operation == "system.service_status":
            status = self._capabilities.service_status(request.service or "")
            if status.service == "ollama":
                text = "Ollama is running." if status.running else "Ollama appears unavailable."
            else:
                text = (
                    "Radicale is running and Planning is reachable."
                    if status.running
                    else "Planning backend appears unavailable."
                )
        elif request.operation == "system.health_status":
            text = _format_tori_health(self._capabilities.tori_health())
        else:
            raise SystemCapabilityError("That system capability is not supported.", code="unknown_capability")
        return SystemTurn(request, text)

    def handle(self, text: str) -> SystemTurn | None:
        request = self.interpret(text)
        if request is None:
            return None
        try:
            if request.operation == "system.service_action":
                proposal = self._capabilities.service_action_proposal(
                    request.service or "", request.action or ""
                )
                return SystemTurn(
                    request,
                    _service_action_proposal_text(proposal),
                    proposal=proposal,
                )
            return self.execute(request)
        except SystemCapabilityError as exc:
            return SystemTurn(request, str(exc), exc.code)
        except Exception:
            return SystemTurn(
                request,
                _bounded_failure_for(request),
                "system_capability_unavailable",
            )

    def execute_service_action(self, proposal: ServiceActionProposal) -> ServiceActionResult:
        return self._capabilities.execute_service_action(proposal)


def _strip_terminal_punctuation(text: str) -> str:
    return text.rstrip(".!?").strip()


def _is_disk_request(text: str) -> bool:
    text = _normalize_host_information_request(text)
    return bool(
        text.startswith((
            "how much disk space", "how much free disk space", "how much free space",
            "how much space", "how much room",
        ))
        and (
            text.endswith("do i have left")
            or text.endswith("i have left")
            or text.endswith("is there")
            or text.endswith("is left")
            or re.search(
                r"\bis\s+(?:currently\s+)?left(?:\s+on\s+(?:my\s+)?host)?$",
                text,
            ) is not None
            or re.search(r"\bon\s+`?/", text) is not None
        )
    )


def _is_network_request(text: str) -> bool:
    text = _strip_terminal_punctuation(text)
    return text in {
        "what's my ip address",
        "what is my ip address",
        "what's my local ip",
        "what is my local ip",
        "what's the ip of this computer",
        "what is the ip of this computer",
        "what is my local ip address",
        "what's my local ip address",
    }


def _is_brave_request(text: str) -> bool:
    text = _strip_terminal_punctuation(text)
    return text in {
        "open brave",
        "open brave browser",
        "launch brave",
        "launch brave browser",
        "start brave",
        "start brave browser",
    }


def _desktop_application_request(text: str) -> str | None:
    text = _strip_terminal_punctuation(text)
    return {
        "open dolphin": "dolphin",
        "launch dolphin": "dolphin",
        "open a terminal": "terminal",
        "open terminal": "terminal",
        "launch a terminal": "terminal",
        "launch terminal": "terminal",
        "open lm studio": "lm_studio",
        "launch lm studio": "lm_studio",
    }.get(text)


_INSTALLATION_ROOT = Path(__file__).resolve().parents[2]
_KNOWN_FOLDER_ALIASES = {
    "open my tori project folder": str(_INSTALLATION_ROOT),
    "open the tori project folder": str(_INSTALLATION_ROOT),
    "open tori project folder": str(_INSTALLATION_ROOT),
    "open my tori project": str(_INSTALLATION_ROOT),
    "open the tori project": str(_INSTALLATION_ROOT),
    "open my projects folder": str(_INSTALLATION_ROOT.parent),
    "open the projects folder": str(_INSTALLATION_ROOT.parent),
    "open projects folder": str(_INSTALLATION_ROOT.parent),
}


def _folder_request(normalized: str, lowered: str) -> str | None:
    alias = _KNOWN_FOLDER_ALIASES.get(_strip_terminal_punctuation(lowered))
    if alias is not None:
        return alias
    candidate = _strip_terminal_punctuation(normalized)
    if not candidate.casefold().startswith("open "):
        return None
    path = candidate[5:].strip()
    if path.startswith("`") and path.endswith("`"):
        path = path[1:-1]
    if (
        not path.startswith("/")
        or not path
        or any(character.isspace() for character in path)
        or any(character in path for character in "\x00;|&$><")
    ):
        return None
    return path


def _is_service_action_request(text: str) -> tuple[str, str] | None:
    text = _strip_terminal_punctuation(text)
    return {
        "start ollama": ("start", "ollama"),
        "stop ollama": ("stop", "ollama"),
        "restart ollama": ("restart", "ollama"),
        "start radicale": ("start", "radicale"),
        "stop radicale": ("stop", "radicale"),
        "restart radicale": ("restart", "radicale"),
        "start the planning server": ("start", "radicale"),
        "stop the planning server": ("stop", "radicale"),
        "restart the planning server": ("restart", "radicale"),
        "start planning": ("start", "radicale"),
        "stop planning": ("stop", "radicale"),
        "restart planning": ("restart", "radicale"),
        "start the calendar backend": ("start", "radicale"),
        "stop the calendar backend": ("stop", "radicale"),
        "restart the calendar backend": ("restart", "radicale"),
    }.get(text)


def _application_label(application: str) -> str:
    return SystemCapabilities._DESKTOP_LABELS.get(application, "that application")


def _service_action_proposal_text(proposal: ServiceActionProposal) -> str:
    action = proposal.action.capitalize()
    scope = "systemd --user" if proposal.scope == "user" else "systemd"
    return (
        f"Action: {action} service.\n"
        f"Service: {proposal.display_name}.\n"
        f"System target: {proposal.unit}.\n"
        f"Control: {scope}.\n"
        "Explicit confirmation is required before anything changes."
    )


def _is_memory_request(text: str) -> bool:
    text = _normalize_host_information_request(text)
    if text in {
        "how much ram am i using",
        "how much memory am i using",
        "how much memory is free",
        "how much memory is available",
        "how much memory do i have free",
        "how much ram is free",
        "how much ram is available",
        "how much ram do i have free",
        "how much ram do i have",
        "how much memory do i have",
        "what's my memory usage",
        "what is my memory usage",
        "what's my ram usage",
        "what is my ram usage",
    }:
        return True
    return re.fullmatch(
        r"how much (?:system )?(?:ram|memory) (?:(?:am i|i am) using|"
        r"is (?:currently )?(?:in )?use(?: (?:right )?now)?"
        r"(?: on (?:my )?host)?)",
        text,
    ) is not None


def _normalize_host_information_request(text: str) -> str:
    """Remove bounded conversational framing before strict host-query matching."""

    normalized = _strip_terminal_punctuation(text).replace("i'm", "i am")
    while True:
        previous = normalized
        normalized = re.sub(
            r"^(?:(?:hi|hey|hello)\s+tori|tori|by the way|"
            r"before i (?:go|leave)|real quick)\s*,?\s*",
            "",
            normalized,
        )
        normalized = re.sub(
            r"^(?:can|could|would)\s+you\s+", "", normalized
        )
        normalized = re.sub(r"^(?:please\s+)?(?:tell me|check)\s+", "", normalized)
        normalized = re.sub(r"\s+(?:please|for me|real quick)$", "", normalized)
        if normalized == previous:
            return normalized.strip()


def _is_cpu_request(text: str) -> bool:
    text = _strip_terminal_punctuation(text)
    return text in {
        "what's my cpu usage",
        "what is my cpu usage",
        "how busy is the cpu",
        "what processor do i have",
        "what cpu do i have",
        "what's the system load",
        "what is the system load",
    }


def _is_gpu_request(text: str) -> bool:
    text = _strip_terminal_punctuation(text)
    return text in {
        "what gpu am i using",
        "what gpu do i have",
        "how much vram do i have",
        "how much vram do i have free",
        "how much vram is free",
        "what's my gpu usage",
        "what is my gpu usage",
        "what's my gpu temperature",
        "what is my gpu temperature",
        "how hot is my gpu",
    }


def _is_uptime_request(text: str) -> bool:
    text = _strip_terminal_punctuation(text)
    return text in {
        "how long has this computer been running",
        "what's the uptime",
        "what is the uptime",
        "when did this computer boot",
    }


def _is_ollama_request(text: str) -> bool:
    text = _strip_terminal_punctuation(text)
    return text in {
        "is ollama running",
        "is ollama up",
        "what's the ollama status",
        "what is the ollama status",
    }


def _is_radicale_request(text: str) -> bool:
    text = _strip_terminal_punctuation(text)
    return text in {
        "is radical running",
        "is radical up",
        "is radicale running",
        "is radicale up",
        "is the planning server running",
        "is the planning server up",
        "is planning running",
        "is planning up",
        "is my calendar backend up",
        "is my calendar backend running",
    }


def _is_tori_health_request(text: str) -> bool:
    text = _strip_terminal_punctuation(text)
    return text in {
        "is tori healthy",
        "how is tori doing",
        "is tori running okay",
        "is tori running ok",
    }


def _format_gpu(gpu: GPUInfo, index: int, count: int) -> str:
    label = gpu.name if count == 1 else f"GPU {index} ({gpu.name})"
    parts: list[str] = []
    if gpu.memory_used_bytes is not None and gpu.memory_total_bytes is not None:
        free = gpu.memory_free_bytes
        if free is None:
            free = max(0, gpu.memory_total_bytes - gpu.memory_used_bytes)
        parts.append(
            f"{label} is using {_format_bytes(gpu.memory_used_bytes)} of "
            f"{_format_bytes(gpu.memory_total_bytes)} VRAM, with "
            f"{_format_bytes(free)} free"
        )
    elif gpu.memory_total_bytes is not None:
        parts.append(f"{label} has {_format_bytes(gpu.memory_total_bytes)} of VRAM")
    else:
        parts.append(label)
    if gpu.utilization_percent is not None and gpu.temperature_celsius is not None:
        parts.append(
            f"GPU utilization is {gpu.utilization_percent:.0f}% and "
            f"temperature is {gpu.temperature_celsius:.0f}°C"
        )
    elif gpu.utilization_percent is not None:
        parts.append(f"GPU utilization is {gpu.utilization_percent:.0f}%")
    elif gpu.temperature_celsius is not None:
        parts.append(f"Temperature is {gpu.temperature_celsius:.0f}°C")
    return ". ".join(parts) + "."


def _format_tori_health(health: ToriHealth) -> str:
    if not health.signals:
        return "Tori health is unavailable."
    available = [
        signal for signal in health.signals
        if signal.status == "available" and signal.name != "Tori"
    ]
    unavailable = [
        signal for signal in health.signals
        if signal.status != "available" and signal.name != "Tori"
    ]
    if not unavailable:
        if not available:
            return "Tori is healthy."
        details = [_health_signal_phrase(signal, available=True) for signal in available]
        return f"Tori is healthy. {_join_phrases(details)}."
    if available:
        degraded = [_health_signal_phrase(signal, available=False) for signal in unavailable]
        return f"Tori is running, but {_join_phrases(degraded)}."
    return "Tori health is currently unavailable."


def _health_signal_phrase(signal: HealthSignal, *, available: bool) -> str:
    if available:
        return {
            "Conversation": "Conversation is available",
            "Planning": "Planning is connected",
            "Coding Work": "Coding Work is available",
            "Scheduled Work": "Scheduled Work is operational",
        }.get(signal.name, f"{signal.name} is available")
    if signal.status == "not_configured":
        return f"{signal.name} is not configured"
    return f"{signal.name} is unavailable"


def _join_phrases(phrases: list[str]) -> str:
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


def _bounded_failure_for(request: SystemRequest) -> str:
    messages = {
        "system.memory_status": "Memory status is unavailable right now.",
        "system.cpu_status": "CPU status is unavailable right now.",
        "system.gpu_status": "GPU status is unavailable on this host.",
        "system.uptime": "Uptime is unavailable right now.",
        "system.service_status": "That service status is unavailable right now.",
        "system.health_status": "Tori health is unavailable right now.",
        "system.service_action": "That service action is unavailable right now.",
    }
    return messages.get(request.operation, "That system capability is unavailable right now.")


def _extract_absolute_path(text: str) -> str | None:
    marker = " on "
    lowered = text.casefold()
    index = lowered.find(marker)
    if index < 0:
        return None
    candidate = text[index + len(marker):].strip().rstrip(".!?").strip("`")
    if candidate.startswith("/") and " " not in candidate:
        return candidate
    return None

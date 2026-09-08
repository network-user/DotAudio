"""Опрос устройства и выбор ускорителя для локальных моделей.

Модуль Qt-free и не тянет тяжёлых зависимостей: им пользуются и страница
моделей Whisper, и локальный ассистент, и всё, что появится позже. Здесь
только измеренные факты об этой машине - число потоков, объём ОЗУ, список
видеокарт с их памятью - и правила подбора сборки llama.cpp под них.

Видеокарты перечисляются по вендору, а не «есть ли CUDA»: одна и та же
логика должна отвечать и про NVIDIA, и про Radeon, и про встроенную Intel,
потому что дальше в проект будут добавляться другие модели и рантаймы.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, replace

VENDOR_NVIDIA = "nvidia"
VENDOR_AMD = "amd"
VENDOR_INTEL = "intel"
VENDOR_APPLE = "apple"
VENDOR_UNKNOWN = "unknown"

VENDOR_LABELS = {
    VENDOR_NVIDIA: "NVIDIA",
    VENDOR_AMD: "AMD",
    VENDOR_INTEL: "Intel",
    VENDOR_APPLE: "Apple",
    VENDOR_UNKNOWN: "Видеокарта",
}

# Названия адаптеров, по которым определяется вендор. Проверяется по порядку:
# у Intel Arc в имени бывает и «Intel», и «Arc», а у виртуальных адаптеров -
# ни того ни другого, и они честно остаются неизвестными.
_VENDOR_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (VENDOR_NVIDIA, ("nvidia", "geforce", "rtx ", "gtx ", "quadro", "tesla", "titan")),
    (VENDOR_AMD, ("amd", "radeon", "vega", "firepro", "ryzen graphics")),
    (VENDOR_INTEL, ("intel", "arc ", "iris", "uhd graphics", "hd graphics")),
    (VENDOR_APPLE, ("apple",)),
)

# Встроенное видео делит память с системой, поэтому «свободная VRAM» у него
# ничего не значит для выгрузки слоёв модели.
_INTEGRATED_MARKERS = ("uhd graphics", "hd graphics", "iris", "vega 8", "vega 7", "radeon graphics")

# Свежие результаты опроса живут недолго: карта могла занять память под
# другую задачу, а страница моделей показывает именно текущее состояние.
PROBE_TTL_SECONDS = 20.0

_probe_lock = threading.Lock()
_cached: tuple[float, "HardwareProfile"] | None = None


def _no_window_kwargs() -> dict:
    """Не показывать консольное окно, когда GUI спрашивает nvidia-smi."""

    if sys.platform != "win32":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _run(args: list[str], timeout: float = 6.0) -> str:
    try:
        finished = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return finished.stdout or ""


def vendor_of(name: str) -> str:
    """Вендор по названию адаптера."""

    low = (name or "").casefold()
    for vendor, markers in _VENDOR_MARKERS:
        if any(marker in low for marker in markers):
            return vendor
    return VENDOR_UNKNOWN


def _looks_integrated(name: str, vram_mb: int | None) -> bool:
    low = (name or "").casefold()
    if any(marker in low for marker in _INTEGRATED_MARKERS):
        return True
    # Дискретная карта с меньше чем 1,5 ГБ своей памяти встречается только
    # среди очень старых моделей; для выгрузки слоёв она всё равно бесполезна.
    return vram_mb is not None and vram_mb < 1536


@dataclass(frozen=True)
class GpuDevice:
    """Одна видеокарта такой, какой её видно с этой машины."""

    index: int
    name: str
    vendor: str = VENDOR_UNKNOWN
    vram_mb: int | None = None
    vram_free_mb: int | None = None
    driver: str = ""
    compute: str = ""
    integrated: bool = False
    source: str = ""

    @property
    def vendor_label(self) -> str:
        return VENDOR_LABELS.get(self.vendor, VENDOR_LABELS[VENDOR_UNKNOWN])

    @property
    def vram_gb(self) -> float | None:
        if self.vram_mb is None:
            return None
        return round(self.vram_mb / 1024, 1)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "vendor": self.vendor,
            "vendorLabel": self.vendor_label,
            "vramMb": self.vram_mb,
            "vramGb": self.vram_gb,
            "vramFreeMb": self.vram_free_mb,
            "driver": self.driver,
            "compute": self.compute,
            "integrated": self.integrated,
            "source": self.source,
        }


@dataclass(frozen=True)
class HardwareProfile:
    """Сводка машины: потоки, память, видеокарты, доступность рантаймов."""

    threads: int = 0
    ram_gb: float | None = None
    gpus: tuple[GpuDevice, ...] = ()
    platform: str = ""
    # Сколько CUDA-устройств видит именно CTranslate2 (движок Whisper). Это
    # не то же самое, что «карта есть»: без нужных runtime-библиотек он
    # вернёт ноль и уйдёт на CPU.
    cuda_runtime_devices: int = 0
    # Умеет ли установленная сборка llama.cpp выгружать слои на видеокарту.
    # Факт от самой библиотеки, а не вывод из наличия карты.
    llama_gpu_offload: bool | None = None
    notes: tuple[str, ...] = field(default=())

    @property
    def best_gpu(self) -> GpuDevice | None:
        """Карта с наибольшей собственной памятью; встроенная - в последнюю очередь."""

        usable = [gpu for gpu in self.gpus if not gpu.integrated]
        pool = usable or list(self.gpus)
        if not pool:
            return None
        return max(pool, key=lambda gpu: (gpu.vram_mb or 0, -gpu.index))

    @property
    def vram_mb(self) -> int | None:
        gpu = self.best_gpu
        return None if gpu is None else gpu.vram_mb

    @property
    def has_dedicated_gpu(self) -> bool:
        return any(not gpu.integrated for gpu in self.gpus)

    def as_dict(self) -> dict:
        """Плоский вид для QML и журналов.

        Ключи ``threads``/``ram_gb``/``cuda_devices``/``compute_label``
        сохранены: на них уже опирается страница моделей Whisper.
        """

        gpu = self.best_gpu
        return {
            "threads": self.threads,
            "ram_gb": self.ram_gb,
            "cuda_devices": self.cuda_runtime_devices,
            "compute_label": (
                "Видеокарта (CUDA)" if self.cuda_runtime_devices > 0 else "Процессор (CPU)"
            ),
            "gpus": [item.as_dict() for item in self.gpus],
            "gpuName": "" if gpu is None else gpu.name,
            "gpuVendor": "" if gpu is None else gpu.vendor,
            "gpuVramGb": None if gpu is None else gpu.vram_gb,
            "gpuLabel": gpu_label(gpu),
            "hasDedicatedGpu": self.has_dedicated_gpu,
            "llamaGpuOffload": self.llama_gpu_offload,
            "platform": self.platform,
            "notes": list(self.notes),
        }


def gpu_label(gpu: GpuDevice | None) -> str:
    """Короткая подпись карты для интерфейса."""

    if gpu is None:
        return "Видеокарта не найдена"
    vram = gpu.vram_gb
    if vram is None:
        return gpu.name
    return f"{gpu.name}, {vram:g} ГБ"


def physical_memory_gb() -> float | None:
    """Реальный объём ОЗУ; вне Windows или при отказе API - неизвестно."""

    if sys.platform != "win32":
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            size = os.sysconf("SC_PAGE_SIZE")
        except (AttributeError, ValueError, OSError):
            return None
        return round(pages * size / (1024**3), 1)
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetPhysicallyInstalledSystemMemory.argtypes = [ctypes.POINTER(wintypes.ULONGLONG)]
        kb = wintypes.ULONGLONG(0)
        if not kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)):
            return None
        return round(kb.value / (1024 * 1024), 1)
    except (OSError, AttributeError):
        return None


def ctranslate2_cuda_devices() -> int:
    """Сколько CUDA-устройств видит CTranslate2 прямо сейчас."""

    try:
        import ctranslate2

        return max(0, int(ctranslate2.get_cuda_device_count()))
    except Exception:
        return 0


def llama_gpu_offload_supported() -> bool | None:
    """Умеет ли установленная сборка llama.cpp считать на видеокарте.

    ``None`` значит, что библиотеки нет вовсе, и об этом нужно сказать
    иначе, чем про «сборка без ускорения».
    """

    try:
        import llama_cpp
    except Exception:
        return None
    try:
        return bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:
        return False


def _parse_nvidia_smi(raw: str) -> list[GpuDevice]:
    devices: list[GpuDevice] = []
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        index, name, total, free, driver, compute = parts[:6]

        def mb(value: str) -> int | None:
            digits = re.sub(r"[^0-9]", "", value)
            return int(digits) if digits else None

        devices.append(
            GpuDevice(
                index=int(index),
                name=name,
                vendor=VENDOR_NVIDIA,
                vram_mb=mb(total),
                vram_free_mb=mb(free),
                driver=driver,
                compute=compute,
                integrated=False,
                source="nvidia-smi",
            )
        )
    return devices


def nvidia_gpus() -> list[GpuDevice]:
    """Карты NVIDIA с точной памятью и compute capability."""

    raw = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.free,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ]
    )
    return _parse_nvidia_smi(raw)


def _registry_display_adapters() -> list[GpuDevice]:
    """Адаптеры из реестра Windows: работает для любого вендора.

    ``HardwareInformation.qwMemorySize`` даёт настоящий объём видеопамяти,
    в отличие от ``Win32_VideoController.AdapterRAM``, который обрезан
    четырьмя гигабайтами.
    """

    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    class_key = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    devices: list[GpuDevice] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, class_key) as root:
            position = 0
            while True:
                try:
                    child = winreg.EnumKey(root, position)
                except OSError:
                    break
                position += 1
                if not child.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, child) as entry:
                        name = _reg_str(winreg, entry, "DriverDesc")
                        if not name:
                            continue
                        vram = _reg_vram_mb(winreg, entry)
                        driver = _reg_str(winreg, entry, "DriverVersion")
                except OSError:
                    continue
                devices.append(
                    GpuDevice(
                        index=int(child),
                        name=name,
                        vendor=vendor_of(name),
                        vram_mb=vram,
                        driver=driver,
                        integrated=_looks_integrated(name, vram),
                        source="registry",
                    )
                )
    except OSError:
        return []
    return devices


def _reg_str(winreg, key, name: str) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value).strip()


def _reg_vram_mb(winreg, key) -> int | None:
    for name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
        try:
            value, kind = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        number: int | None = None
        if isinstance(value, int):
            number = value
        elif isinstance(value, bytes) and value:
            number = int.from_bytes(value, "little")
        if number:
            return int(number / (1024 * 1024))
    return None


def _merge_gpus(primary: list[GpuDevice], extra: list[GpuDevice]) -> tuple[GpuDevice, ...]:
    """Дополнить точные данные вендорной утилиты списком из системы.

    nvidia-smi знает про свои карты больше всех, но не видит Radeon и Intel.
    Совпадения ищутся по названию, чтобы одна карта не попала в список дважды.
    """

    merged = list(primary)
    known = {gpu.name.casefold() for gpu in merged}
    for gpu in extra:
        low = gpu.name.casefold()
        if any(low == name or low in name or name in low for name in known):
            continue
        merged.append(gpu)
        known.add(low)
    return tuple(replace(gpu, index=position) for position, gpu in enumerate(merged))


def list_gpus() -> tuple[GpuDevice, ...]:
    """Все видеокарты этой машины, каждая с тем, что удалось измерить."""

    return _merge_gpus(nvidia_gpus(), _registry_display_adapters())


def probe(refresh: bool = False) -> HardwareProfile:
    """Сводка устройства; повторный вызов отдаёт свежий кеш.

    Опрос запускает внешний процесс и читает реестр, поэтому его нельзя
    звать из обработчика кадра. Кеш живёт ``PROBE_TTL_SECONDS``.
    """

    global _cached
    now = time.monotonic()
    with _probe_lock:
        if not refresh and _cached is not None and now - _cached[0] < PROBE_TTL_SECONDS:
            return _cached[1]
    # DLL из pip-пакетов NVIDIA должны быть зарегистрированы до опроса
    # CTranslate2, иначе CUDA останется «нет» даже после установки.
    try:
        from dotaudio.cuda_runtime import register_cuda_dll_directories

        register_cuda_dll_directories()
    except Exception:
        pass
    gpus = list_gpus()
    notes: list[str] = []
    cuda_runtime = ctranslate2_cuda_devices()
    if cuda_runtime == 0 and any(gpu.vendor == VENDOR_NVIDIA for gpu in gpus):
        notes.append(
            "Карта NVIDIA есть, но CTranslate2 её не видит: Whisper пойдёт на процессоре."
        )
    profile = HardwareProfile(
        threads=os.cpu_count() or 0,
        ram_gb=physical_memory_gb(),
        gpus=gpus,
        platform=sys.platform,
        cuda_runtime_devices=cuda_runtime,
        llama_gpu_offload=llama_gpu_offload_supported(),
        notes=tuple(notes),
    )
    with _probe_lock:
        _cached = (time.monotonic(), profile)
    return profile


def reset_cache() -> None:
    """Сбросить кеш опроса; нужно тестам и после установки ускорения."""

    global _cached
    with _probe_lock:
        _cached = None


@dataclass(frozen=True)
class Accelerator:
    """Сборка llama.cpp под определённое железо.

    Новый ускоритель добавляется одной записью: индекс колёс, условие
    пригодности и подпись. Остальной код про вендоров ничего не знает.
    """

    id: str
    label: str
    detail: str
    wheel_index: str | None = None
    vendors: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    # Готовые колёса собраны не под все версии Python; заявлять установку
    # там, где её нет, нельзя.
    python_versions: tuple[tuple[int, int], ...] = ()
    priority: int = 0

    def suits(self, profile: HardwareProfile) -> bool:
        if self.platforms and profile.platform not in self.platforms:
            return False
        if not self.vendors:
            return True
        return any(gpu.vendor in self.vendors and not gpu.integrated for gpu in profile.gpus)

    def wheels_for_current_python(self) -> bool:
        if not self.python_versions:
            return True
        return sys.version_info[:2] in self.python_versions


# Индексы готовых колёс llama-cpp-python. Состав проверен по опубликованным
# индексам: под CPU есть сборки для всех поддерживаемых версий Python, под
# CUDA - для 3.10-3.12, а Vulkan и ROCm на момент проверки собраны не под
# каждую версию. Поэтому пригодность считается, а не заявляется.
CUDA_PYTHON = ((3, 10), (3, 11), (3, 12))
ACCELERATORS: tuple[Accelerator, ...] = (
    Accelerator(
        id="cuda",
        label="CUDA",
        detail="Видеокарты NVIDIA",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/cu124",
        vendors=(VENDOR_NVIDIA,),
        platforms=("win32", "linux"),
        python_versions=CUDA_PYTHON,
        priority=40,
    ),
    Accelerator(
        id="vulkan",
        label="Vulkan",
        detail="Любая карта с драйвером Vulkan: NVIDIA, Radeon, Intel Arc",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/vulkan",
        vendors=(VENDOR_NVIDIA, VENDOR_AMD, VENDOR_INTEL),
        platforms=("win32", "linux"),
        priority=30,
    ),
    Accelerator(
        id="rocm",
        label="ROCm",
        detail="Radeon на Linux и HIP-сборка для Windows",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/hip-radeon",
        vendors=(VENDOR_AMD,),
        platforms=("win32", "linux"),
        priority=25,
    ),
    Accelerator(
        id="metal",
        label="Metal",
        detail="Apple Silicon",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/metal",
        platforms=("darwin",),
        priority=35,
    ),
    Accelerator(
        id="cpu",
        label="Процессор",
        detail="Работает везде, скорость зависит от числа потоков",
        wheel_index="https://abetlen.github.io/llama-cpp-python/whl/cpu",
        priority=10,
    ),
)


def accelerator_options(profile: HardwareProfile | None = None) -> list[dict]:
    """Сборки llama.cpp по пригодности этому железу, лучшая первой."""

    profile = profile or probe()
    options: list[dict] = []
    for accelerator in ACCELERATORS:
        suits = accelerator.suits(profile)
        wheels = accelerator.wheels_for_current_python()
        if suits and not wheels:
            reason = (
                f"Готовой сборки под Python "
                f"{sys.version_info.major}.{sys.version_info.minor} нет"
            )
        elif suits:
            reason = accelerator.detail
        else:
            reason = "Нет подходящего устройства"
        options.append(
            {
                "id": accelerator.id,
                "label": accelerator.label,
                "detail": accelerator.detail,
                "available": bool(suits and wheels),
                "reason": reason,
                "wheelIndex": accelerator.wheel_index,
                "command": install_command(accelerator.id),
                "priority": accelerator.priority,
            }
        )
    options.sort(key=lambda item: (not item["available"], -item["priority"]))
    return options


def recommended_accelerator(profile: HardwareProfile | None = None) -> str:
    """Ускоритель, который стоит поставить на этой машине."""

    for option in accelerator_options(profile):
        if option["available"]:
            return str(option["id"])
    return "cpu"


def install_command(accelerator_id: str) -> str:
    """Команда установки сборки llama.cpp для показа пользователю."""

    for accelerator in ACCELERATORS:
        if accelerator.id != accelerator_id:
            continue
        if not accelerator.wheel_index:
            return "pip install llama-cpp-python"
        return (
            "pip install llama-cpp-python --upgrade --force-reinstall "
            f"--extra-index-url {accelerator.wheel_index}"
        )
    return ""


def install_arguments(accelerator_id: str) -> list[str]:
    """Аргументы pip для установки выбранной сборки без shell."""

    for accelerator in ACCELERATORS:
        if accelerator.id != accelerator_id:
            continue
        args = ["-m", "pip", "install", "llama-cpp-python", "--upgrade", "--force-reinstall"]
        if accelerator.wheel_index:
            args += ["--extra-index-url", accelerator.wheel_index]
        return args
    return []

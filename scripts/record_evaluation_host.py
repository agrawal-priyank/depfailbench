"""Record host facts separately from scientific manifests; never read secrets."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys


ALLOWED_ENV = ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA', 'GITHUB_JOB',
               'RUNNER_NAME', 'RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')


def optional_text(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def host_record():
    cpuinfo = optional_text('/proc/cpuinfo') or ''
    models = sorted({line.split(':', 1)[1].strip() for line in cpuinfo.splitlines()
                     if line.startswith('model name') and ':' in line})
    memory = {}
    for line in (optional_text('/proc/meminfo') or '').splitlines():
        key, _, value = line.partition(':')
        if key in {'MemTotal', 'MemAvailable'}:
            words = value.split()
            if len(words) == 2 and words[0].isdigit() and words[1] == 'kB':
                memory[key + '_bytes'] = int(words[0]) * 1024
    return {
        'schema_version': 1, 'captured_at_utc': datetime.now(timezone.utc).isoformat(),
        'platform': platform.platform(), 'machine': platform.machine(),
        'python': sys.version, 'cpu_models_reported_by_guest': models or None,
        'logical_cpus_os_count': os.cpu_count(),
        'process_affinity_logical_cpu_count': len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        'memory_reported_by_guest': memory or None,
        'cgroup_v2_cpu_max': optional_text('/sys/fs/cgroup/cpu.max'),
        'cgroup_v2_memory_max': optional_text('/sys/fs/cgroup/memory.max'),
        'os_release': optional_text('/etc/os-release'),
        'workflow_and_image': {k: os.environ[k] for k in ALLOWED_ENV if k in os.environ},
        'limitations': 'Guest-visible facts at capture; no guarantee of identical physical hosts, CPU allocation, or background load. Missing fields are unknown. Model-provider inference hardware is separate.',
        'model_api_calls': 0, 'generated_program_executions': 0,
    }


def write_record(output):
    record = host_record()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        handle.write(json.dumps(record, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    write_record(args.output)
    print(json.dumps({'host_metadata_saved': str(args.output), 'model_api_calls': 0}))

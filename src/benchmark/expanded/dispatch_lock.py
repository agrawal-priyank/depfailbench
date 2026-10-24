"""OS-released per-slot locks for the validated Linux/macOS execution hosts."""
from contextlib import contextmanager
from pathlib import Path
import fcntl
from .spending import DispatchPaused


@contextmanager
def slot_lock(output, identity):
    if not identity or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in identity):
        raise ValueError('invalid artifact identity')
    output = Path(output)
    directory = output.parent / ('.' + output.name + '_dispatch_locks')
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (identity + '.lock')).open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DispatchPaused('slot is still active; recovery or duplicate dispatch is blocked') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

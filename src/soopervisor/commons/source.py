import tarfile
import os.path
import shutil
from pathlib import Path
from itertools import chain
from glob import iglob
import subprocess

from click.exceptions import ClickException


def git_tracked_files():
    res = subprocess.run(['git', 'ls-tree', '-r', 'HEAD', '--name-only'],
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)

    if not res.returncode:
        return res.stdout.decode().splitlines(), None
    else:
        return None, res.stderr.decode().strip()


def git_is_dirty():
    """
    Returns True if there are git untracked files (new files that haven't been
    committed yet)
    """
    res = subprocess.run(['git', 'status', '--short'],
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)

    return not (res.returncode or '??' not in res.stdout.decode())


def is_relative_to(path, prefix):
    if prefix is None:
        return False

    try:
        Path(path).relative_to(prefix)
    except ValueError:
        return False
    else:
        return True


def is_relative_to_any(path, prefixes):
    return any(is_relative_to(path, prefix) for prefix in prefixes)


def glob_all(path, exclude=None):
    hidden = iglob(str(Path(path) / '**' / '.*'), recursive=True)
    normal = iglob(str(Path(path) / '**'), recursive=True)

    for path in chain(hidden, normal):
        if Path(path).is_file() and not is_relative_to(path, exclude):
            yield path


def copy(cmdr, src, dst, include=None, exclude=None):
    include = set() if include is None else set(include)
    exclude = set() if exclude is None else set(exclude)
    exclude_dirs = set(p for p in exclude if Path(p).is_dir())
    include_dirs = set(p for p in include if Path(p).is_dir())

    overlap = set(include) & set(exclude)

    if overlap:
        raise ClickException('include and exclude must not have '
                             f'overlapping elements: {overlap}')

    if git_is_dirty():
        cmdr.warn_on_exit('Your git repository contains untracked '
                          'files, which will be ignored when building the '
                          'Docker image. Commit them if needed.')

    tracked, error = git_tracked_files()

    if error:
        cmdr.warn_on_exit(
            f'Unable to get git tracked files: {error}. Everything '
            'will be included, except for files in the \'exclude\' section '
            'of soopervisor.yaml')

    for f in glob_all(path=src, exclude=dst):
        tracked_by_git = tracked is None or f in tracked
        excluded = f in exclude or is_relative_to_any(f, exclude_dirs)
        included = f in include or is_relative_to_any(f, include_dirs)
        # never include .git or .gitignore
        never_include = Path(f).name.startswith('.git') or '__pycache__' in f

        if ((tracked_by_git or included) and not excluded
                and not never_include):
            target = Path(dst, f)
            target.parent.mkdir(exist_ok=True, parents=True)
            shutil.copy(f, dst=target)
            print(f'Copying {f} -> {target}')


def compress_dir(src, dst):
    with tarfile.open(dst, "w:gz") as tar:
        tar.add(src, arcname=os.path.basename(src))

    shutil.rmtree(src)

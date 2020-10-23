"""
Schema
------

paths:
    # path to project directory
    project: .
    # path to products directory (if relative, it is to paths.project),
    # any generated file in this folder is considered a pipeline product
    products: output/
    # path conda environment file (if relative, it is to paths.project)
    environment: environment.yml

"""
import shutil
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, validator, Field
from jinja2 import Template
import yaml

from soopervisor.script.script import generate_script
from soopervisor.git_handler import GitRepo
from soopervisor.storage.LocalStorage import LocalStorage


class StorageConfig(BaseModel):
    """
    This section configures there to copy pipeline products after execution

    provider: str
        'box' for uploading files to box or 'local' to just copy files
        to a local directory. None to disable

    path: str
        Path where the files will be moved, defaults to runs/{{git}},
        where {{git}} will be replaced by the current git hash
    """
    paths: Optional[str]

    provider: Optional[str] = None
    path: Optional[str] = 'runs/{{git}}'
    credentials: Optional[str]

    def __init__(self, *, paths, **data) -> None:
        super().__init__(**data)
        self.paths = paths

    @validator('provider', always=True)
    def validate_provider(cls, v):
        valid = {'box', 'local', None}
        if v not in valid:
            raise ValueError(f'Provider must be one of: {valid}')
        return v

    def check(self):
        LocalStorage(self.path)

    def dict(self, *args, **kwargs):
        d = super().dict(*args, **kwargs)

        # only expand if storage is enabled
        if d['provider']:
            d['path'] = Template(d['path']).render(
                git=GitRepo(self.paths.project).get_git_hash())

        return d


class Paths(BaseModel):
    class Config:
        validate_assignment = True

    project: Optional[str] = '.'
    products: Optional[str] = 'output'
    environment: Optional[str] = 'environment.yml'

    def __init__(self, **data) -> None:
        super().__init__(**data)

    @validator('project', always=True)
    def project_must_be_absolute(cls, v):
        return str(Path(v).resolve())

    def dict(self, *args, **kwargs):
        d = super().dict(*args, **kwargs)
        d['environment'] = self._resolve_path(d['environment'])
        d['products'] = self._resolve_path(d['products'])
        return d

    def _resolve_path(self, path):
        if Path(path).is_absolute():
            return str(Path(path).resolve())
        else:
            return str(Path(self.project, path).resolve())

    def __str__(self):
        return ('Paths:'
                f'\n  * Project root: {self.project}'
                f'\n  * Products: {self.products}'
                f'\n  * Environment: {self.environment}')


class ScriptConfig(BaseModel):
    """
    Root section fo rthe confiuration file

    Parameters
    ----------
    paths : dict
        Section to configure important project paths

    cache_env : bool
        Create env again only if environment.yml has changed

    executor : str
        Which executor to use "local" or "docker"

    allow_incremental : bool
        If True, allows execution on non-empty product folders
    """
    # FIXME: defaults should favor convenience (less chance of errors)
    # vs speed. set cache_env to false
    paths: Optional[Paths] = Field(default_factory=Paths)
    cache_env: Optional[bool] = True
    args: Optional[str] = ''
    storage: StorageConfig = None
    executor: Optional[str] = 'local'
    allow_incremental: Optional[bool] = True
    environment_prefix: Optional[str] = None

    def __init__(self, **data) -> None:
        if 'storage' in data:
            storage = data.pop('storage')
        else:
            storage = {}

        super().__init__(**data)
        self.storage = StorageConfig(paths=self.paths, **storage)
        self.storage.check()

    @classmethod
    def from_path(cls, project):
        """
        Initializes a ScriptConfig from a directory. Looks for a
        project/soopervisor.yaml file, if it doesn't exist, it just
        initializes with default values
        """
        path = Path(project, 'soopervisor.yaml')

        if path.exists():
            with open(str(path)) as f:
                d = yaml.safe_load(f)

            config = cls(**d)

        else:
            config = cls()

        return config

    def to_script(self):
        return generate_script(config=self.dict())

    def dict(self, *args, **kwargs):
        d = super().dict(*args, **kwargs)
        if d['environment_prefix'] is not None:
            d['environment_prefix'] = self._resolve_path(
                d['environment_prefix'])
            d['environment_name'] = d['environment_prefix']
        else:
            with open(d['paths']['environment']) as f:
                env_spec = yaml.safe_load(f)

            d['environment_name'] = env_spec['name']

        return d

    def _resolve_path(self, path):
        if Path(path).is_absolute():
            return str(Path(path).resolve())
        else:
            return str(Path(self.paths.project, path).resolve())

    def save_script(self):
        """Save script to the project's root directory, returns script location
        """
        script = self.to_script()
        path_to_script = Path(self.paths.project, 'script.sh')
        path_to_script.write_text(script)
        return str(path_to_script)

    def clean_products(self):
        if Path(self.paths.products).exists():
            shutil.rmtree(self.paths.products)
            Path(self.paths.products).mkdir()

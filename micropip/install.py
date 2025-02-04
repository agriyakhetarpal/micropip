import asyncio
import importlib
from pathlib import Path

from ._compat import loadPackage, to_js
from ._vendored.packaging.src.packaging.markers import default_environment
from .constants import FAQ_URLS
from .logging import setup_logging
from .transaction import Transaction


async def install(
    requirements: str | list[str],
    index_urls: list[str] | str,
    keep_going: bool = False,
    deps: bool = True,
    credentials: str | None = None,
    pre: bool = False,
    *,
    constraints: list[str] | None = None,
    verbose: bool | int | None = None,
) -> None:
    with setup_logging().ctx_level(verbose) as logger:

        ctx = default_environment()
        if isinstance(requirements, str):
            requirements = [requirements]

        fetch_kwargs = {}

        if credentials:
            fetch_kwargs["credentials"] = credentials

        # Note: getsitepackages is not available in a virtual environment...
        # See https://github.com/pypa/virtualenv/issues/228 (issue is closed but
        # problem is not fixed)
        from site import getsitepackages

        wheel_base = Path(getsitepackages()[0])

        transaction = Transaction(
            ctx=ctx,  # type: ignore[arg-type]
            ctx_extras=[],
            keep_going=keep_going,
            deps=deps,
            pre=pre,
            fetch_kwargs=fetch_kwargs,
            verbose=verbose,
            index_urls=index_urls,
            constraints=constraints,
        )
        await transaction.gather_requirements(requirements)

        if transaction.failed:
            failed_requirements = ", ".join([f"'{req}'" for req in transaction.failed])
            raise ValueError(
                f"Can't find a pure Python 3 wheel for: {failed_requirements}\n"
                f"See: {FAQ_URLS['cant_find_wheel']}\n"
            )

        pyodide_packages, wheels = transaction.pyodide_packages, transaction.wheels

        package_names = [pkg.name for pkg in wheels + pyodide_packages]

        logger.debug(
            "Installing packages %r and wheels %r ",
            transaction.pyodide_packages,
            [w.filename for w in transaction.wheels],
        )

        if package_names:
            logger.info("Installing collected packages: %s", ", ".join(package_names))

        # Install PyPI packages
        # detect whether the wheel metadata is from PyPI or from custom location
        # wheel metadata from PyPI has SHA256 checksum digest.
        await asyncio.gather(*(wheel.install(wheel_base) for wheel in wheels))

        # Install built-in packages
        if pyodide_packages:
            # Note: branch never happens in out-of-browser testing because in
            # that case REPODATA_PACKAGES is empty.
            await asyncio.ensure_future(
                loadPackage(to_js([name for [name, _, _] in pyodide_packages]))
            )

        packages = [f"{pkg.name}-{pkg.version}" for pkg in pyodide_packages + wheels]

        if packages:
            logger.info("Successfully installed %s", ", ".join(packages))

        importlib.invalidate_caches()

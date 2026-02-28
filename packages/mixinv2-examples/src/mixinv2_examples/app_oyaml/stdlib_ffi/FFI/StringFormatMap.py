"""template.format_map(arguments) -> str"""

from mixinv2 import extern, public, resource


@extern
def template() -> str: ...


@extern
def arguments() -> object: ...


@public
@resource
def formatted(template: str, arguments: object) -> str:
    return template.format_map(arguments)

"""Debug script to trace kwargs flow."""
from ol import public, resource, scope, extern
from ol.runtime import Scope, evaluate

@public
@scope
class TestScope:
    @public
    @extern
    def outer_value() -> str:
        ...

    @public
    @scope
    class Inner:
        @public
        @extern
        def inner_value() -> str:
            ...
        
        @public
        @resource
        def combined(outer_value: str, inner_value: str) -> str:
            return f"{outer_value}+{inner_value}"

# Test
root = evaluate(TestScope)
outer_instance = root(outer_value="OUTER")
print(f"outer_instance.outer_value = {outer_instance.outer_value}")

inner_scope = outer_instance.Inner
print(f"inner_scope type = {type(inner_scope).__name__}")

inner_instance = inner_scope(inner_value="INNER")
print(f"inner_instance type = {type(inner_instance).__name__}")

try:
    result = inner_instance.combined
    print(f"result = {result}")
except Exception as e:
    print(f"ERROR: {e}")

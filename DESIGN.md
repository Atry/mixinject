# mixinject 设计文档

## 核心概念

我想要实现类似pytest fixture的使用体验，但是scope要用树状的，而且要支持mixin语义。类似 https://github.com/atry/mixin 和 https://github.com/mxmlnkn/ratarmount/pull/163 的方式来实现mixin。

**关键术语**：
- **Resource**: 一个命名的可注入值，可以通过`@resource`、`@patch`、`@patches`、`@aggregator`等装饰器定义
- **Proxy**: 代表一个资源命名空间的对象，通过属性访问（`.`操作符）来获取资源
- **Scope**: 资源的嵌套命名空间结构，类似文件系统的目录
- **Lexical Scope**: 资源解析时的查找链，从内层到外层扫描
- **Endo函数**: 形如`Callable[[T], T]`的函数，用于修改现有值

通过decorator来表示需要把一个callable启用依赖注入。

如果类比联合文件系统，应该把Proxy视为目录对象，把resource视为文件。而module、package、callable、ScopeDefinition视为挂载前的文件系统定义。编译（compile）后的结果是具体的Proxy对象，它实现了资源的访问。

依赖注入总是基于参数的名称而不是基于类型。参数解析算法类似 https://github.com/atry/mixin ，自动在lexical scope链中寻找依赖（从内层到外层）。如果需要访问复杂路径，则必须依赖显式的Proxy对象。

```python
@resource
def my_callable(uncle: Proxy) -> float:
  return uncle.path.to.resource
```

以上代码相当于根据uncle的名称在lexical scope链中搜索，找到第一个定义了uncle资源的Proxy，然后在该Proxy下寻找 `path/to/resource` 资源。
如果一个callable的返回值是另一个Proxy对象，那么该资源被视为类似 https://github.com/mxmlnkn/ratarmount/pull/163 的软链接的处理方式。

```python
@resource
def my_scope(uncle: Proxy) -> Proxy:
  return uncle.path.to.another_scope
```
这大致相当于符号链接的行为：在lexical scope链中找到第一个定义了uncle的Proxy，然后通过该Proxy访问其中的嵌套资源。

有一种特殊情况是当依赖项的名称和callable的名称相同时，表示跳过当前Proxy，在外层Proxy中寻找同名资源，而不是在当前Proxy内寻找。
```python
@resource
def my_callable(my_callable: float) -> float:
  return my_callable + 1.0
```
以上代码表示跳过当前Proxy，在lexical scope链中寻找上层（父）Proxy中定义的同名资源 `my_callable`。这实现了pytest fixture的同名依赖注入语义，用于访问外层定义的同名资源。

合并module和package时，使用类似 https://github.com/atry/mixin 和 https://github.com/mxmlnkn/ratarmount/pull/163 的算法。

合并N个同名callable时，必须正好有N-1个callable是`@patch` decorator，而正好有1个callable是`@resource` decorator或者`@aggregator` decorator。否则报错。

在整个框架的入口处（`resolve_root`或`resolve`），用户可以选择传入多个package、module、或者object，它们会被联合挂载到一个统一的根Proxy中，类似 https://github.com/mxmlnkn/ratarmount/pull/163的做法。


## Endo-only Resources as Parameters（最佳实践）

一个资源可以仅由`@patch`或`@patches`装饰器定义，而不需要`@resource`或`@aggregator`的基础定义。这种**endo-only resource**本质上是一个"参数"，它允许其他资源依赖该参数，同时参数的最终值来自outer scope的注入。

### 核心特点

**Endo-only patch通常是恒等函数**（`lambda x: x`），不做任何转换。这样做的关键目的是：**在词法域中注册这个资源名称，使其他资源能够通过lexical scope lookup找到它**。

当该资源被访问时，系统会：
1. 在lexical scope中查找这个资源名称
2. 找到outer scope中通过`simple_component`注入的基础值
3. 应用所有endo-only patch（通常只是恒等函数，所以值不变）
4. 将最终值传递给依赖它的资源

### 例子

```python
# config.py
from mixinject import patch, resource
from typing import Callable, Dict

@patch
def settings() -> Callable[[Dict[str, str]], Dict[str, str]]:
    """Endo-only resource: 恒等函数，不做任何转换

    存在的唯一目的是在词法域中注册'settings'这个资源名称
    """
    return lambda cfg: cfg  # 恒等函数

@resource
def connection_string(settings: Dict[str, str]) -> str:
    """其他资源依赖endo-only resource作为参数"""
    return f"{settings.get('host', 'localhost')}:{settings.get('port', '5432')}"

# main.py
from mixinject import resolve, simple_component, CachedProxy

# 通过simple_component提供基础值到outer scope
def outer_scope():
    yield CachedProxy(components=frozenset([
        simple_component(settings={"host": "db.example.com", "port": "3306"})
    ]))

root = resolve(outer_scope, config)
assert root.connection_string == "db.example.com:3306"
```

### 关键优势

1. **词法域注册**：即使不提供资源的基础实现，endo-only patch也会注册资源名称，使其在词法域中可查找
2. **灵活注入**：基础值可以在运行时通过outer scope的`simple_component`注入
3. **解耦模块**：模块不需要知道资源的具体值，只需声明它的存在

这个模式在以下场景很有用：
- **配置参数**：模块声明需要某个配置，但不定义其值
- **依赖注入**：将外部依赖注入到模块中而无需硬编码
- **多版本支持**：同一个模块可以与不同的注入值组合使用

## Proxy as Callable（已实现）

每一个Proxy对象同时也是Callable，支持直接参数注入。

### 实现

Proxy实现了`__call__(**kwargs)`方法，返回一个新的同类型Proxy对象，该对象包含原有的所有components加上通过kwargs提供的新值（作为`simple_component`）。

```python
# 创建一个空Proxy并注入值
proxy = CachedProxy(components=frozenset([]))
new_proxy = proxy(setting="value", count=42)

# 访问注入的值
assert new_proxy.setting == "value"
assert new_proxy.count == 42
```

### 主要用途

Proxy as Callable的主要用途是为**endo-only resources**提供base values。通过在outer scope中使用`Proxy.__call__`来注入参数值，然后模块中的资源可以通过同名参数lookup来访问这些值：

```python
# 在outer scope中提供base value
outer_proxy = CachedProxy(components=frozenset([])) \
    (db_config={"host": "localhost", "port": "5432"})

def outer_scope() -> Iterator[Proxy]:
    yield outer_proxy

# 模块中的资源可以通过同名参数获取这个值
class Database:
    @resource
    def db_config(db_config: dict) -> dict:
        """Same-name parameter: looks up from outer scope"""
        return db_config
```

callable除了可以用来定义resource之外，也可以用来定义和转换scope。